"""La sábana de Contratos ya no pregunta por las unidades (24-10-2026): exporta lo
que se ve en la lista, con sus filtros. Se actualiza la instrucción de la Guía."""

from django.db import migrations

VIEJO = 'Elige si quieres todas las unidades o solo algunas y confirma: se descarga el Excel.'
NUEVO = ('Se descarga el Excel con lo que se ve en la lista: si antes filtras (por unidad, '
         'tipo de contrato…) o buscas a alguien, solo sale eso.')


def actualizar(apps, schema_editor, viejo=VIEJO, nuevo=NUEVO):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for tarea in TareaGuia.objects.filter(codigo='exportar_lista_contratos'):
        if viejo in (tarea.instrucciones or ''):
            tarea.instrucciones = tarea.instrucciones.replace(viejo, nuevo)
            tarea.save(update_fields=['instrucciones'])


def deshacer(apps, schema_editor):
    actualizar(apps, schema_editor, viejo=NUEVO, nuevo=VIEJO)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0039_anexos_17'),
    ]

    operations = [
        migrations.RunPython(actualizar, deshacer),
    ]
