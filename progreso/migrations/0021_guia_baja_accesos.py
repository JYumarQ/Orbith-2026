from django.db import migrations

# La baja se da desde la lista de Contratos o desde el Gestor de Plantilla,
# con el mismo Formulario de Baja (antes había dos copias distintas; se dejó
# solo la completa). Cada entrada tiene su recorrido visual
# (static/js/recorrido_baja.js) y el panel de la Guía ofrece las dos.
ACCESOS = (
    'Desde Contratos | /contrato/list_contrato/ | primera_baja:contratos\n'
    'Desde el Gestor | /estructuras/gestor/ | primera_baja:gestor'
)

PASO_ANTERIOR = 'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.'
PASO_NUEVO = (
    'Se da desde la lista de Contratos o desde la columna Contratos del Gestor de Plantilla, con '
    'el mismo formulario. En esas pantallas, "¿Cómo funciona?" te acompaña paso a paso. Aquí se '
    'describe el camino de Contratos: en el menú lateral, pulsa "Contrato".'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primera_baja').first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if PASO_ANTERIOR in tarea.instrucciones:
        tarea.instrucciones = tarea.instrucciones.replace(PASO_ANTERIOR, PASO_NUEVO, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primera_baja').first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(PASO_NUEVO, PASO_ANTERIOR, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0020_guia_movimiento_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
