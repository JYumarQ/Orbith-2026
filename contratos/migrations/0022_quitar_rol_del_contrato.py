"""El rol de pago es del CARGO, no del contrato (decisión de RRHH del 23-10-2026).

`CAlta.rol` era una copia del rol del cargo que se hacía al crear o editar el
contrato, pero el movimiento de nómina no la actualizaba: tras pasar a un cargo con
otro rol, el contrato conservaba el rol viejo y el Word del contrato (y el salario
guardado, los informes y el Excel) salían con el salario de ese rol. Esta migración:

1. Borra la columna: desde ahora todo lee `cargo.rol`.
2. Recalcula el salario guardado (`salario_actual`) de todos los contratos con el rol
   de su cargo.

El «salario anterior» de los movimientos ya registrados se corrige en la 0023.

El cálculo es el de `contratos.salarios.calcular_salario`, que no depende de modelos.
"""

from decimal import Decimal

from django.db import migrations

from contratos.salarios import calcular_salario

CATEGORIAS_CUADRO = ('CDI', 'CEJ')


def _escala(apps):
    NSalario = apps.get_model('nomencladores', 'NSalario')
    return {(g, r, t): m for g, r, t, m in NSalario.objects.values_list(
        'grupo_escala_id', 'rol_id', 'tridente_id', 'monto')}


def recalcular_salarios(apps, schema_editor):
    CAlta = apps.get_model('contratos', 'CAlta')
    escala = _escala(apps)
    for fila in CAlta.objects.values(
            'pk', 'salario_actual', 'tipo_salario', 'tridente_id', 'cargo_id', 'cargo__rol_id',
            'cargo__ncargo__grupo_escala_id', 'cargo__ncargo__cat_ocupacional',
            'cargo__ncargo__salario_basico'):
        nuevo = calcular_salario(
            tipo_salario=fila['tipo_salario'],
            tiene_cargo=fila['cargo_id'] is not None,
            es_cuadro=fila['cargo__ncargo__cat_ocupacional'] in CATEGORIAS_CUADRO,
            grupo_escala_id=fila['cargo__ncargo__grupo_escala_id'],
            rol_id_cargo=fila['cargo__rol_id'],
            tridente_id=fila['tridente_id'],
            salario_basico=fila['cargo__ncargo__salario_basico'],
            buscar_monto=lambda g, r, t: escala.get((g, r, t)),
        )
        nuevo = Decimal(str(nuevo)) if nuevo is not None else None
        if nuevo != fila['salario_actual']:
            CAlta.objects.filter(pk=fila['pk']).update(salario_actual=nuevo)


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0021_mision_solo_en_calta_dias_importe'),
        ('nomencladores', '0013_nimportegradocientifico_npagoadicional'),
        ('strorganizativa', '0015_cargoplantilla_unique_cargo_por_departamento_y_plantilla'),
    ]

    operations = [
        migrations.RemoveField(model_name='calta', name='rol'),
        migrations.RunPython(recalcular_salarios, sin_operacion),
    ]
