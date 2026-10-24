"""Triángulos de problemas en el Gestor de plantilla y en la lista de Contratos
(decisión de RRHH del 23-10-2026, Fase 2).

Solo LEEN los hallazgos de Subsanación, que la revisión por registro
(`subsanacion.por_registro`) mantiene al día al guardar y el análisis diario
completa. Su coste no depende de cuántos contratos haya: una consulta agrupada
sobre los hallazgos abiertos, que son pocos.

* Rojo = algún hallazgo abierto de criticidad Crítica. Sube en cascada: contrato →
  cargo → departamento → unidad (y su unidad principal).
* Ámbar = algún hallazgo abierto de criticidad Alta, sin ninguno Crítico. Solo se
  ve en el contrato o en el cargo que lo tiene: no sube.
* Lo silenciado en Subsanación («Ignorado», «Falso positivo») no cuenta.
* La fila de un contrato incluye también los problemas de la ficha del trabajador.
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .constantes import CRITICIDAD_ALTA, CRITICIDAD_CRITICA

CRITICO = 'critico'
ALTO = 'alto'


def _abiertos():
    from .models import Hallazgo
    return Hallazgo.objects.filter(vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS,
                                   criticidad__lte=CRITICIDAD_ALTA)


def _nivel(criticidad):
    return CRITICO if criticidad <= CRITICIDAD_CRITICA else ALTO


def _tipos():
    from bolsa.models import Aspirante
    from contratos.models import CAlta
    from strorganizativa.models import CargoPlantilla
    return (ContentType.objects.get_for_model(CAlta),
            ContentType.objects.get_for_model(Aspirante),
            ContentType.objects.get_for_model(CargoPlantilla))


def problemas_por_contrato(contratos):
    """`{contrato_id: {'nivel': 'critico'|'alto', 'total': N}}` para los contratos
    dados (instancias o pares `(pk, aspirante_id)`), con los de su ficha."""
    pares = [(c.pk, c.aspirante_id) if hasattr(c, 'pk') else tuple(c) for c in contratos]
    if not pares:
        return {}
    tipo_contrato, tipo_ficha, _ = _tipos()
    por_ficha = {}
    for pk, aspirante_id in pares:
        por_ficha.setdefault(str(aspirante_id), []).append(pk)

    resultado = {}
    filas = _abiertos().filter(
        Q(content_type=tipo_contrato, object_id__in=[str(pk) for pk, _ in pares])
        | Q(content_type=tipo_ficha, object_id__in=list(por_ficha))
    ).values_list('content_type_id', 'object_id', 'criticidad')
    for tipo_id, object_id, criticidad in filas:
        destino = [int(object_id)] if tipo_id == tipo_contrato.pk else por_ficha.get(object_id, [])
        for pk in destino:
            actual = resultado.setdefault(pk, {'criticidad': criticidad, 'total': 0})
            actual['criticidad'] = min(actual['criticidad'], criticidad)
            actual['total'] += 1
    return {pk: {'nivel': _nivel(d['criticidad']), 'total': d['total']}
            for pk, d in resultado.items()}


def problemas_por_cargo(cargo_ids):
    """`{cargo_id: 'critico'|'alto'}` por los hallazgos PROPIOS del cargo."""
    _, _, tipo_cargo = _tipos()
    resultado = {}
    for object_id, criticidad in _abiertos().filter(
            content_type=tipo_cargo, object_id__in=[str(i) for i in cargo_ids]
    ).values_list('object_id', 'criticidad'):
        anterior = resultado.get(int(object_id))
        if anterior != CRITICO:
            resultado[int(object_id)] = _nivel(criticidad)
    return resultado


def cascada_critica():
    """Qué unidades, departamentos y cargos llevan el triángulo ROJO porque algo por
    debajo tiene un problema Crítico. `{'unidades': set, 'departamentos': set,
    'cargos': set}`. Recorre solo los hallazgos críticos abiertos."""
    from contratos.models import CAlta
    from strorganizativa.models import CargoPlantilla, UnidadOrganizativa

    tipo_contrato, tipo_ficha, tipo_cargo = _tipos()
    criticos = _abiertos().filter(criticidad__lte=CRITICIDAD_CRITICA).values_list(
        'content_type_id', 'object_id')
    contratos, fichas, cargos = set(), set(), set()
    for tipo_id, object_id in criticos:
        if not object_id:
            continue
        if tipo_id == tipo_contrato.pk:
            contratos.add(object_id)
        elif tipo_id == tipo_ficha.pk:
            fichas.add(object_id)
        elif tipo_id == tipo_cargo.pk:
            cargos.add(object_id)

    cargo_ids = set(CAlta.objects.filter(
        Q(pk__in=contratos) | Q(aspirante_id__in=fichas), cargo__isnull=False
    ).values_list('cargo_id', flat=True))
    cargo_ids |= {int(c) for c in cargos}

    departamentos, unidades = set(), set()
    for dpto_id, unidad_id in CargoPlantilla.objects.filter(pk__in=cargo_ids).values_list(
            'departamento_id', 'departamento__unidad_organizativa_id'):
        departamentos.add(dpto_id)
        unidades.add(unidad_id)
    # La unidad principal también se marca si alguna de sus subunidades lo está.
    unidades |= set(UnidadOrganizativa.objects.filter(
        direcciones_hijas__in=unidades).values_list('pk', flat=True))
    return {'unidades': unidades, 'departamentos': departamentos, 'cargos': cargo_ids}


def hallazgos_del_registro(modelo, objeto):
    """Hallazgos abiertos Críticos y Altos de un contrato (con los de su ficha) o de
    un cargo, ordenados de más a menos grave, para la ventana del ⚠️."""
    tipo_contrato, tipo_ficha, tipo_cargo = _tipos()
    if modelo == 'contrato':
        filtro = (Q(content_type=tipo_contrato, object_id=str(objeto.pk))
                  | Q(content_type=tipo_ficha, object_id=str(objeto.aspirante_id)))
    else:
        filtro = Q(content_type=tipo_cargo, object_id=str(objeto.pk))
    return list(_abiertos().filter(filtro).order_by('criticidad', 'codigo_regla'))


def marcar(objetos, niveles, modelo_ventana=None):
    """Pone en cada objeto `nivel_problema` ('critico'|'alto'|None) y, si se indica
    `modelo_ventana` ('contrato'|'cargo'), `url_problemas` para abrir su ventana.
    `niveles` = `{pk: 'critico'|'alto'}` o `{pk: {'nivel': ..., 'total': ...}}`.
    Devuelve la lista (las plantillas la recorren igual que el queryset)."""
    from django.urls import reverse

    objetos = list(objetos)
    for objeto in objetos:
        valor = niveles.get(objeto.pk)
        if isinstance(valor, dict):
            objeto.total_problemas = valor['total']
            valor = valor['nivel']
        objeto.nivel_problema = valor
        objeto.url_problemas = (reverse('subsanacion:problemas_registro',
                                        args=[modelo_ventana, objeto.pk])
                                if valor and modelo_ventana else '')
    return objetos


def niveles_de_cargos(cargo_ids, cascada=None):
    """Rojo si el cargo tiene un problema crítico propio o por debajo (cascada);
    ámbar si solo tiene uno Alto propio. La ventana se abre solo si hay problemas
    propios del cargo; si el rojo viene de sus contratos, se ven en ellos."""
    cascada = cascada if cascada is not None else cascada_critica()
    propios = problemas_por_cargo(cargo_ids)
    niveles = {}
    for pk in cargo_ids:
        if pk in cascada['cargos'] or propios.get(pk) == CRITICO:
            niveles[pk] = CRITICO
        elif propios.get(pk) == ALTO:
            niveles[pk] = ALTO
    return niveles, propios


def contratos_con_problemas(nivel):
    """Ids de contrato (como texto) con problemas abiertos para el filtro de la lista:
    `nivel` = 'criticos' (alguno Crítico), 'altos' (alguno Alto y ninguno Crítico)
    o 'todos'. Incluye los de la ficha del trabajador."""
    from contratos.models import CAlta

    tipo_contrato, tipo_ficha, _ = _tipos()
    peor = {}
    filas = _abiertos().filter(content_type__in=[tipo_contrato, tipo_ficha]).values_list(
        'content_type_id', 'object_id', 'criticidad')
    por_ficha = {}
    for tipo_id, object_id, criticidad in filas:
        if tipo_id == tipo_contrato.pk:
            peor[object_id] = min(peor.get(object_id, 99), criticidad)
        else:
            por_ficha[object_id] = min(por_ficha.get(object_id, 99), criticidad)
    if por_ficha:
        for pk, aspirante_id in CAlta.objects.filter(
                aspirante_id__in=list(por_ficha)).values_list('pk', 'aspirante_id'):
            clave = str(pk)
            peor[clave] = min(peor.get(clave, 99), por_ficha[str(aspirante_id)])
    if nivel == 'criticos':
        return [pk for pk, c in peor.items() if c <= CRITICIDAD_CRITICA]
    if nivel == 'altos':
        return [pk for pk, c in peor.items() if c > CRITICIDAD_CRITICA]
    return list(peor)
