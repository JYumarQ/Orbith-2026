"""Los cargos de las unidades Temporales pasan a «Fuera de Plantilla» (decisión de RRHH
del 16-11-2026). Hasta ahora solo nacían así los cargos NUEVOS; los que ya existían
seguían contando en la plantilla aprobada.

No se toca (y Subsanación lo avisa con EST-012) el cargo que:
* tiene un contrato activo que ocupa plaza (Indeterminado): una plaza fuera de la
  plantilla no puede sostenerlo;
* ya tiene su pareja fuera de la plantilla en el mismo departamento.

Solo cambia `en_plantilla` de esos cargos: ni contratos, ni plazas aprobadas, ni
personas. Mismas reglas que `strorganizativa.plantilla_temporal.mover_cargos`.
"""
from django.db import migrations


def sacar_de_plantilla(apps, schema_editor):
    CargoPlantilla = apps.get_model('strorganizativa', 'CargoPlantilla')
    CAlta = apps.get_model('contratos', 'CAlta')

    candidatos = list(CargoPlantilla.objects.filter(
        departamento__unidad_organizativa__tipo__es_temporal=True, en_plantilla=True,
    ).values_list('pk', 'departamento_id', 'ncargo_id'))
    if not candidatos:
        return

    con_contrato = set(CAlta.objects.filter(
        cargo_id__in=[pk for pk, _, _ in candidatos],
        aspirante__estado='ACTIVO', tipo__ocupa_plaza=True,
    ).values_list('cargo_id', flat=True))
    ya_fuera = set(CargoPlantilla.objects.filter(
        departamento__unidad_organizativa__tipo__es_temporal=True, en_plantilla=False,
    ).values_list('departamento_id', 'ncargo_id'))

    a_mover = []
    for pk, departamento_id, ncargo_id in candidatos:
        if pk in con_contrato or (departamento_id, ncargo_id) in ya_fuera:
            continue
        ya_fuera.add((departamento_id, ncargo_id))
        a_mover.append(pk)
    CargoPlantilla.objects.filter(pk__in=a_mover).update(en_plantilla=False)


class Migration(migrations.Migration):

    dependencies = [
        ('strorganizativa', '0017_nomencladores_orden_y_proteccion'),
        ('contratos', '0030_escrito_a_mano_en_movimiento'),
        ('nomencladores', '0015_orden_inicial'),
    ]

    operations = [
        migrations.RunPython(sacar_de_plantilla, migrations.RunPython.noop),
    ]
