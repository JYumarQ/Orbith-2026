"""Unidades Temporales: sus cargos van, por defecto, FUERA de la plantilla aprobada.

Decisión de RRHH del 16-11-2026:

* Un cargo nuevo en una unidad de tipo Temporal nace «Fuera de Plantilla»
  (`CargoPlantillaForm.__init__`, que ya lo hacía). Es solo el valor inicial: quien
  lo crea o edita puede meterlo en plantilla.
* Los cargos que ya existían en unidades Temporales pasan a «Fuera de Plantilla» al
  actualizar (migración `strorganizativa.0018`).
* Al cambiar el tipo de una unidad (pasa a Temporal o deja de serlo), «Editar Unidad»
  pregunta si mover también sus cargos; aquí está lo que ejecuta la respuesta.
* Subsanación (EST-012) lista los cargos de unidades Temporales que sigan dentro de
  la plantilla, para confirmarlos o corregirlos.

Dos cosas impiden mover un cargo, y nunca se fuerzan:

* **Sacarlo de la plantilla** con un contrato activo que ocupa plaza (Indeterminado):
  una plaza que no es plantilla no puede sostenerlo. Misma regla que
  `CargoPlantillaForm.clean`.
* **La pareja**: el departamento ya tiene el mismo cargo en el otro lado (la base
  no admite dos iguales en el mismo lado, ver `CargoPlantilla.Meta`).
"""

from .models import CargoPlantilla

MOTIVO_CONTRATO = 'tiene un contrato que ocupa plaza (Indeterminado)'
MOTIVO_PAREJA_FUERA = 'el departamento ya tiene ese mismo cargo fuera de la plantilla'
MOTIVO_PAREJA_DENTRO = 'el departamento ya tiene ese mismo cargo dentro de la plantilla'


def es_temporal(unidad):
    """¿La unidad es de un tipo marcado «Es temporal»?"""
    return bool(unidad is not None and unidad.tipo_id and unidad.tipo.es_temporal)


def cargos_de(unidad, en_plantilla):
    """Cargos de la unidad que están en ese lado de la plantilla."""
    return CargoPlantilla.objects.filter(
        departamento__unidad_organizativa=unidad, en_plantilla=en_plantilla)


def _con_contrato_que_ocupa_plaza(cargo_ids):
    from contratos.models import CAlta
    return set(CAlta.objects.filter(
        cargo_id__in=cargo_ids, aspirante__estado='ACTIVO', tipo__ocupa_plaza=True,
    ).values_list('cargo_id', flat=True))


def mover_cargos(unidad, a_plantilla):
    """Pasa los cargos de `unidad` al lado indicado (`a_plantilla=False` = sacarlos).

    Devuelve `(movidos, no_movidos)`: cuántos cambió y la lista `[(cargo, motivo)]` de
    los que dejó como estaban. Guarda cargo a cargo con `save()` para que Auditoría
    registre cada cambio y Subsanación revise el cargo al momento.
    """
    candidatos = list(cargos_de(unidad, en_plantilla=not a_plantilla)
                      .select_related('ncargo', 'departamento'))
    if not candidatos:
        return 0, []

    con_contrato = set() if a_plantilla else _con_contrato_que_ocupa_plaza([c.pk for c in candidatos])
    ya_en_destino = set(cargos_de(unidad, en_plantilla=a_plantilla)
                        .values_list('departamento_id', 'ncargo_id'))

    movidos, no_movidos = 0, []
    for cargo in candidatos:
        if cargo.pk in con_contrato:
            no_movidos.append((cargo, MOTIVO_CONTRATO))
            continue
        if (cargo.departamento_id, cargo.ncargo_id) in ya_en_destino:
            no_movidos.append((cargo, MOTIVO_PAREJA_DENTRO if a_plantilla else MOTIVO_PAREJA_FUERA))
            continue
        cargo.en_plantilla = a_plantilla
        cargo.save()
        ya_en_destino.add((cargo.departamento_id, cargo.ncargo_id))
        movidos += 1
    return movidos, no_movidos


def resumen_del_movimiento(movidos, no_movidos, a_plantilla):
    """Frase para el aviso tras guardar la unidad."""
    lado = 'dentro de la plantilla' if a_plantilla else 'Fuera de Plantilla'
    partes = []
    if movidos:
        partes.append('%d cargo%s pas%s a %s' % (
            movidos, '' if movidos == 1 else 's', 'ó' if movidos == 1 else 'aron', lado))
    if no_movidos:
        nombres = '; '.join('%s (%s)' % (cargo.ncargo.descripcion, motivo)
                            for cargo, motivo in no_movidos[:4])
        partes.append('%d no se movi%s: %s%s' % (
            len(no_movidos), 'ó' if len(no_movidos) == 1 else 'eron', nombres,
            '…' if len(no_movidos) > 4 else ''))
    return '. '.join(partes) + '.' if partes else ''
