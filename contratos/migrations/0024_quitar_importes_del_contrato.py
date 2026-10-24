"""Los importes de Maestría, Doctorado, CNCI e Instructor dejan de guardarse en el
contrato: el nomenclador manda (decisión de RRHH del 23-10-2026).

Antes de borrar las cuatro columnas, cada importe guardado se compara con lo que
dice el nomenclador:

* CNCI / Instructor con importe y SIN entrada elegida: si hay UNA entrada de ese
  tipo con el mismo importe, se enlaza sola. Si no, el importe queda anotado en
  `ImporteSinNomenclador` (sin importe de nomenclador) para que RRHH le asigne la
  entrada correcta; la regla CTR-023 lo muestra.
* Importe distinto del nomenclador (entrada elegida con otra cuantía, o Maestría /
  Doctorado distinto del importe del grado del trabajador): queda anotado con los
  dos importes, para que RRHH lo revise.

Las entradas de CNCI e Instructor que usan contratos pasan a PROTECT: no se pueden
borrar mientras algún contrato las tenga.
"""

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def clasificar_importes(apps, schema_editor):
    CAlta = apps.get_model('contratos', 'CAlta')
    NPagoAdicional = apps.get_model('nomencladores', 'NPagoAdicional')
    NImporteGradoCientifico = apps.get_model('nomencladores', 'NImporteGradoCientifico')
    ImporteSinNomenclador = apps.get_model('contratos', 'ImporteSinNomenclador')

    cero = Decimal('0.00')
    por_grado = dict(NImporteGradoCientifico.objects.values_list('grado', 'importe'))
    entradas = {}
    for pk, tipo, importe in NPagoAdicional.objects.values_list('pk', 'tipo', 'importe'):
        entradas.setdefault((tipo, importe), []).append(pk)

    pendientes = []
    for c in CAlta.objects.select_related('aspirante', 'cnci_nomenclador', 'instructor_nomenclador'):
        for concepto, tipo, fk in (('cnci', 'CNC', 'cnci_nomenclador'),
                                   ('instructor', 'INS', 'instructor_nomenclador')):
            guardado = getattr(c, concepto) or cero
            entrada = getattr(c, fk)
            if entrada is None:
                if not guardado:
                    continue
                candidatas = entradas.get((tipo, guardado), [])
                if len(candidatas) == 1:
                    CAlta.objects.filter(pk=c.pk).update(**{f'{fk}_id': candidatas[0]})
                else:
                    pendientes.append(ImporteSinNomenclador(
                        contrato_id=c.pk, concepto=concepto, importe_antiguo=guardado))
            elif guardado != entrada.importe:
                pendientes.append(ImporteSinNomenclador(
                    contrato_id=c.pk, concepto=concepto, importe_antiguo=guardado,
                    importe_nomenclador=entrada.importe))

        grado = c.aspirante.grado_cientifico if c.aspirante_id else None
        for concepto, clave in (('maestria', 'MC'), ('doctorado', 'DC')):
            guardado = getattr(c, concepto) or cero
            esperado = (por_grado.get(clave) or cero) if grado == clave else cero
            if guardado != esperado:
                pendientes.append(ImporteSinNomenclador(
                    contrato_id=c.pk, concepto=concepto, importe_antiguo=guardado,
                    importe_nomenclador=esperado))

    ImporteSinNomenclador.objects.bulk_create(pendientes)


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contratos', '0023_corregir_salario_anterior_de_movimientos'),
        ('nomencladores', '0013_nimportegradocientifico_npagoadicional'),
    ]

    operations = [
        migrations.CreateModel(
            name='ImporteSinNomenclador',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('concepto', models.CharField(choices=[('cnci', 'CNCI'), ('instructor', 'Instructor'), ('maestria', 'Maestría'), ('doctorado', 'Doctorado')], max_length=12)),
                ('importe_antiguo', models.DecimalField(decimal_places=2, max_digits=10)),
                ('importe_nomenclador', models.DecimalField(blank=True, decimal_places=2, help_text='Lo que dice el nomenclador; vacío si el contrato no tenía entrada.', max_digits=10, null=True)),
                ('fecha', models.DateField(auto_now_add=True)),
                ('contrato', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='importes_sin_nomenclador', to='contratos.calta')),
            ],
            options={
                'verbose_name': 'Importe antiguo sin nomenclador',
                'verbose_name_plural': 'Importes antiguos sin nomenclador',
                'constraints': [models.UniqueConstraint(fields=('contrato', 'concepto'), name='unique_importe_antiguo_por_concepto')],
            },
        ),
        migrations.RunPython(clasificar_importes, sin_operacion),
        migrations.RemoveField(model_name='calta', name='cnci'),
        migrations.RemoveField(model_name='calta', name='doctorado'),
        migrations.RemoveField(model_name='calta', name='instructor'),
        migrations.RemoveField(model_name='calta', name='maestria'),
        migrations.AlterField(
            model_name='calta',
            name='cnci_nomenclador',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contratos_cnci', to='nomencladores.npagoadicional', verbose_name='CNCI (nomenclador)'),
        ),
        migrations.AlterField(
            model_name='calta',
            name='instructor_nomenclador',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contratos_instructor', to='nomencladores.npagoadicional', verbose_name='Instructor (nomenclador)'),
        ),
    ]
