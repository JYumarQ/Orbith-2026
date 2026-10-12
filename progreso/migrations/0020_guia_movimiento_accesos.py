from django.db import migrations

# El movimiento de nómina se pide desde la lista de Contratos o desde el
# Gestor de Plantilla, y se termina en Mov. Nómina. Cada entrada tiene su
# recorrido visual (static/js/recorrido_movimiento.js), que acompaña de una
# pantalla a la otra. El panel de la Guía ofrece las dos entradas.
ACCESOS = (
    'Desde Contratos | /contrato/list_contrato/ | primer_movimiento_interno:contratos\n'
    'Desde el Gestor | /estructuras/gestor/ | primer_movimiento_interno:gestor'
)

PASO_ANTERIOR = 'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.'
PASO_NUEVO = (
    'Se pide desde la lista de Contratos o desde la columna Contratos del Gestor de Plantilla, '
    'y se termina en Mov. Nómina. En esas pantallas, "¿Cómo funciona?" te acompaña paso a paso '
    'de una a otra. Aquí se describe el camino de Contratos: en el menú lateral, pulsa "Contrato".'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primer_movimiento_interno').first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if PASO_ANTERIOR in tarea.instrucciones:
        tarea.instrucciones = tarea.instrucciones.replace(PASO_ANTERIOR, PASO_NUEVO, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo='primer_movimiento_interno').first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(PASO_NUEVO, PASO_ANTERIOR, 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0019_guia_contratacion_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
