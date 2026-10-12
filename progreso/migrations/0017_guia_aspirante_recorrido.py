from django.db import migrations

# La lista de Aspirantes tiene ahora un recorrido visual (botón "¿Cómo
# funciona?" junto al título, ver static/js/recorrido_aspirante.js). El primer
# paso escrito de la tarea lo menciona para que se pueda repetir sin volver a
# la Guía.
PASO_ANTERIOR = 'En el menú lateral, pulsa "Aspirante": te lleva directo al listado.'
PASO_NUEVO = (
    'En el menú lateral, pulsa "Aspirante": te lleva directo al listado. '
    'El botón "¿Cómo funciona?" junto al título te acompaña paso a paso por la lista y el formulario.'
)


def _cambiar(apps, viejo, nuevo):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primer_aspirante').first()
    if tarea and viejo in tarea.instrucciones:
        tarea.instrucciones = tarea.instrucciones.replace(viejo, nuevo, 1)
        tarea.save(update_fields=['instrucciones'])


def aplicar(apps, schema_editor):
    _cambiar(apps, PASO_ANTERIOR, PASO_NUEVO)


def revertir(apps, schema_editor):
    _cambiar(apps, PASO_NUEVO, PASO_ANTERIOR)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0016_guia_roles_y_tareas_nuevas'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
