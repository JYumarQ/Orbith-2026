"""Borra los hallazgos y los avisos de dos reglas eliminadas el 23-10-2026:

* CTR-007 «Grado científico no reflejado en el contrato» y
* CTR-019 «Importe del contrato distinto al del nomenclador».

Los importes de Maestría, Doctorado, CNCI e Instructor ya no se guardan en el
contrato (se leen siempre del nomenclador), así que esas diferencias ya no pueden
existir. Los importes antiguos que no encajaban los muestra la regla CTR-023.
"""

from django.db import migrations

CODIGOS = ('CTR-007', 'CTR-019')


def borrar(apps, schema_editor):
    apps.get_model('subsanacion', 'Hallazgo').objects.filter(codigo_regla__in=CODIGOS).delete()
    apps.get_model('notificaciones', 'Notificacion').objects.filter(codigo_regla__in=CODIGOS).delete()


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('subsanacion', '0006_alter_ejecucionanalisis_origen'),
        ('notificaciones', '0014_borrar_alertas_de_fichas_de_baja'),
    ]

    operations = [migrations.RunPython(borrar, sin_operacion)]
