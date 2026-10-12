from django.db import migrations

# "Ejecuta tu primer análisis de Subsanación" tiene recorrido visual
# (static/js/recorrido_subsanacion.js).
CODIGO = 'primer_analisis_subsanacion'
ACCESOS = 'Ir a Subsanación | /subsanacion/ | primer_analisis_subsanacion:subsanacion'
ANTERIOR = 'En el menú lateral, pulsa "Subsanación".'
NUEVO = (
    'En el menú lateral, pulsa "Subsanación". El botón "¿Cómo funciona?" junto al título te acompaña '
    'paso a paso.'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if ANTERIOR in tarea.instrucciones and NUEVO not in tarea.instrucciones:
        tarea.instrucciones = tarea.instrucciones.replace(ANTERIOR, NUEVO, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(NUEVO, ANTERIOR, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0031_tarea_en_desarrollo'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
