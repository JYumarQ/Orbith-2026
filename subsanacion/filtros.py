"""Filtros y búsqueda del listado de hallazgos.

Vive en su propio módulo para que la vista HTML y las exportaciones a Excel y PDF de
la Fase 2 usen exactamente la MISMA función: es la única forma de garantizar que lo
que el usuario exporta es lo que está viendo en pantalla.
"""

import re

from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField, Q, TextField
from django.db.models.functions import Cast

from core.busqueda import interpretar, normalizar, sin_acentos, solo_digitos_sin_ceros

from .constantes import CLAVES_MODULOS, ETIQUETA_CRITICIDAD, MODULO_EXTRAS
from .models import Hallazgo
from .permisos import es_administrador, unidades_visibles


def _lista_de(request, parametro, validos=None, convertir=None):
    """Lee un parámetro repetido de la URL y descarta los valores no reconocidos.

    Descartar en silencio en vez de fallar es deliberado: un enlace guardado en
    favoritos con un filtro que ya no existe debe seguir mostrando el listado, no un
    error.
    """
    valores = []
    for crudo in request.GET.getlist(parametro):
        crudo = (crudo or '').strip()
        if not crudo:
            continue
        if convertir is not None:
            try:
                crudo = convertir(crudo)
            except (TypeError, ValueError):
                continue
        if validos is not None and crudo not in validos:
            continue
        valores.append(crudo)
    return valores


def filtrar_hallazgos(request):
    """Devuelve `(queryset, filtros_aplicados)` según los parámetros de la URL.

    Por defecto muestra los hallazgos VIGENTES y ABIERTOS (pendientes o en revisión),
    para que la bandeja enseñe trabajo real y no histórico ya cerrado.
    """
    parametros = request.GET

    criticidades = _lista_de(request, 'criticidad', ETIQUETA_CRITICIDAD, int)
    modulos = _lista_de(request, 'modulo', CLAVES_MODULOS)
    estados = _lista_de(request, 'estado', dict(Hallazgo.ESTADOS))
    busqueda = (parametros.get('q') or '').strip()

    solo_criticos = parametros.get('solo_criticos') in ('1', 'on', 'true')
    incluir_archivados = parametros.get('archivados') in ('1', 'on', 'true')

    # Sin `select_related` de la GenericForeignKey a propósito: el listado no resuelve
    # el objeto apuntado, así que no dispara consultas por fila y tolera que el
    # registro original haya sido borrado. `content_type` sí se precarga porque el
    # botón «Abrir registro» lo necesita para construir la url.
    consulta = Hallazgo.objects.select_related('content_type')

    # Alcance por rol (`subsanacion/permisos.py`): un Moderador solo ve hallazgos de
    # sus propias Unidades Organizativas. Un hallazgo SIN unidad (algunos globales,
    # de Configuración o de Usuarios) queda fuera de su alcance — mismo criterio que
    # ya usa `notificaciones/escaneo.py` para repartir avisos: sin unidad, es cosa
    # del Administrador. Se aplica ANTES que cualquier otro filtro para que ninguno
    # de los de abajo pueda ensanchar el alcance por error.
    if not es_administrador(request.user):
        uo_ids_visibles = unidades_visibles(request.user).values_list('pk', flat=True)
        consulta = consulta.filter(unidad_organizativa_id__in=uo_ids_visibles)

    if not incluir_archivados:
        consulta = consulta.filter(vigente=True)

    if estados:
        consulta = consulta.filter(estado__in=estados)
    else:
        consulta = consulta.filter(estado__in=Hallazgo.ESTADOS_ABIERTOS)

    if solo_criticos:
        from .constantes import CRITICIDAD_CRITICA
        consulta = consulta.filter(criticidad=CRITICIDAD_CRITICA)
    elif criticidades:
        consulta = consulta.filter(criticidad__in=criticidades)

    if modulos:
        consulta = consulta.filter(modulo__in=modulos)
    else:
        # «Todas» no incluye Extras: son datos complementarios (ver
        # `reglas/extras.py`), no problemas de calidad, y mezclarlos aquí es ruido.
        # Solo aparecen si el usuario los pide explícitamente filtrando por la
        # categoría Extras (mismo criterio que ya excluye Extras del índice de
        # salud en `servicios.finalizar_ejecucion()`).
        consulta = consulta.exclude(modulo=MODULO_EXTRAS)

    if busqueda:
        consulta = aplicar_busqueda(consulta, busqueda)

    filtros = {
        'q': busqueda,
        'criticidades': criticidades,
        'modulos': modulos,
        'estados': estados,
        'solo_criticos': solo_criticos,
        'archivados': incluir_archivados,
        'hay_filtros': bool(
            busqueda or criticidades or modulos or estados
            or solo_criticos or incluir_archivados),
    }
    return consulta, filtros


def querystring_sin_pagina(request):
    """La querystring actual sin `pagina` (ni `filas`, que lo pone el pie común de la
    tabla), para construir los enlaces de paginación."""
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    parametros.pop('filas', None)
    codificada = parametros.urlencode()
    return f'&{codificada}' if codificada else ''


def querystring_completa(request):
    """La querystring de filtros y búsqueda, sin paginación, para los enlaces de descarga.

    Igual que la anterior pero sin el `&` inicial, porque aquí se pega detrás de un `?`.
    Es lo que hace que el Excel y el PDF contengan exactamente lo que hay en pantalla.
    """
    parametros = request.GET.copy()
    parametros.pop('pagina', None)
    return parametros.urlencode()


# ---------------------------------------------------------------------------
# Búsqueda (texto libre y prefijos, ver `core/busqueda.py`)
# ---------------------------------------------------------------------------

#: Prefijos que entiende Subsanación. Son todos los que existen.
PREFIJOS_SUBSANACION = ('E', 'N', 'CI', 'CA', 'U', 'COD')


def _por_cargo(valor):
    """Hallazgos cuyo registro afectado ocupa (o es) un cargo que contiene `valor`.

    El cargo no está en el título del hallazgo, así que se busca en el registro
    real: el contrato, el contrato del aspirante, la baja o el cargo de plantilla.
    Son subconsultas que solo se ejecutan cuando se usa `CA:`. Un hallazgo de
    Configuración o de Usuarios no tiene cargo y no aparece.
    """
    from bolsa.models import Aspirante
    from contratos.models import CAlta, CBaja
    from strorganizativa.models import CargoPlantilla

    texto = normalizar(valor)

    def ids(consulta, campo_cargo, campo_id='pk'):
        return (consulta.alias(_cargo=sin_acentos(campo_cargo))
                .filter(_cargo__contains=texto)
                .annotate(_id=Cast(campo_id, CharField())).values('_id'))

    tipos = ContentType.objects.get_for_models(CAlta, CBaja, Aspirante, CargoPlantilla)
    return (
        Q(content_type=tipos[CAlta],
          object_id__in=ids(CAlta.objects, 'cargo__ncargo__descripcion'))
        | Q(content_type=tipos[CBaja],
            object_id__in=ids(CBaja.objects, 'cargo__ncargo__descripcion'))
        | Q(content_type=tipos[Aspirante],
            object_id__in=ids(CAlta.objects, 'cargo__ncargo__descripcion', 'aspirante_id'))
        | Q(content_type=tipos[CargoPlantilla],
            object_id__in=ids(CargoPlantilla.objects, 'ncargo__descripcion'))
    )


def aplicar_busqueda(consulta, texto):
    """Filtra los hallazgos por lo escrito en el buscador.

    La búsqueda NO hace JOIN al registro original (el listado no resuelve la
    GenericForeignKey): se busca sobre los campos denormalizados. Por eso cada regla
    escribe en el título el nombre, el carnet y el expediente con un formato fijo
    (`formato.py`): «Apellidos, Nombre (carnet) · Expediente 00158 · …». Los
    prefijos se apoyan en ese formato para buscar en el trozo exacto del título.
    """
    busqueda = interpretar(texto)
    consulta = consulta.alias(_titulo=sin_acentos('titulo'))

    # Texto libre: palabra por palabra, cada una en ALGUNO de los campos y todas a
    # la vez. Así «Nombre Apellido» y «Apellido Nombre» encuentran lo mismo, aunque
    # el título ponga los apellidos primero.
    if busqueda.libre:
        consulta = consulta.alias(
            _detalle=sin_acentos('detalle'),
            _datos=sin_acentos(Cast('datos', TextField())))
        for palabra in busqueda.libre.split():
            normal = normalizar(palabra)
            consulta = consulta.filter(
                Q(_titulo__contains=normal) | Q(_detalle__contains=normal)
                | Q(_datos__contains=normal) | Q(codigo_regla__icontains=palabra))

    for valor in busqueda.valores('E'):
        numero = solo_digitos_sin_ceros(valor)
        if numero is not None:
            # «Expediente 0*158» y que no siga otra cifra: E:158 no es el 1580.
            consulta = consulta.filter(
                _titulo__regex=r'expediente 0*%s(\D|$)' % numero)
        else:
            consulta = consulta.filter(_titulo__contains='expediente ' + normalizar(valor))

    for valor in busqueda.valores('CI'):
        consulta = consulta.filter(titulo__contains='(' + valor.replace(' ', ''))

    for valor in busqueda.valores('N'):
        # Solo en el trozo del nombre: lo que va antes del carnet o del primer «·».
        for palabra in valor.split():
            consulta = consulta.filter(
                _titulo__regex=r'^[^(·]*' + re.escape(normalizar(palabra)))

    for valor in busqueda.valores('CA'):
        consulta = consulta.filter(_por_cargo(valor))

    if busqueda.valores('U'):
        consulta = consulta.alias(_unidad=sin_acentos('unidad_organizativa__descripcion'))
        for valor in busqueda.valores('U'):
            consulta = consulta.filter(_unidad__contains=normalizar(valor))

    for valor in busqueda.valores('COD'):
        consulta = consulta.filter(codigo_regla__istartswith=valor.replace(' ', ''))

    return consulta
