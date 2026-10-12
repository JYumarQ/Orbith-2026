from django.db import migrations

# La contratación se puede hacer desde tres pantallas y cada una tiene ya su
# recorrido visual (static/js/recorrido_contratacion.js). El panel de la Guía
# ofrece las tres con un botón cada una, y el primer paso escrito lo explica.
ACCESOS = (
    'Desde Aspirantes | /bolsa/list_aspir/ | primera_contratacion:aspirantes\n'
    'Desde el Gestor | /estructuras/gestor/ | primera_contratacion:gestor\n'
    'Desde Contratos | /contrato/list_contrato/ | primera_contratacion:contratos'
)

PASO_ANTERIOR = 'En el menú lateral, pulsa "Aspirante": te lleva directo al listado.'
PASO_NUEVO = (
    'Hay tres caminos: desde Aspirantes (seleccionas la fila y pulsas "Contrato"), desde el '
    'Gestor de Plantilla (eliges el cargo y pulsas "+") o desde Contratos (botón "Nuevo"). En '
    'las tres pantallas, "¿Cómo funciona?" te acompaña paso a paso. Aquí se describe el de '
    'Aspirantes: en el menú lateral, pulsa "Aspirante".'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primera_contratacion').first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if PASO_ANTERIOR in tarea.instrucciones:
        tarea.instrucciones = tarea.instrucciones.replace(PASO_ANTERIOR, PASO_NUEVO, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primera_contratacion').first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(PASO_NUEVO, PASO_ANTERIOR, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0018_tareaguia_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
