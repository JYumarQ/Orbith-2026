from django.db import migrations

# Tareas del Moderador con recorrido visual (static/js/recorrido_movimiento.js):
# "Cede tu contrato" se hace desde Contratos o desde el Gestor (solo la fase 1
# del movimiento) y "Recibe tu contrato" en Mov. Nómina (solo la fase 2).
CAMBIOS = {
    'primer_movimiento_cedido': {
        'accesos': (
            'Desde Contratos | /contrato/list_contrato/ | primer_movimiento_cedido:contratos\n'
            'Desde el Gestor | /estructuras/gestor/ | primer_movimiento_cedido:gestor'
        ),
        'anterior': 'En el menú lateral, pulsa "Contrato": se abre la lista de contratos.',
        'nuevo': (
            'Se hace desde la lista de Contratos o desde la columna Contratos del Gestor de Plantilla. '
            'En esas pantallas, "¿Cómo funciona?" → "Ceder un contrato a otro moderador" te acompaña '
            'paso a paso. Aquí se describe el camino de Contratos: en el menú lateral, pulsa "Contrato".'
        ),
    },
    'primer_movimiento_recibido': {
        'accesos': 'Ir a Mov. Nómina | /contrato/movimientos/nomina/ | primer_movimiento_recibido:movnomina',
        'anterior': 'En el menú lateral, pulsa "Mov. Nómina".',
        'nuevo': (
            'En el menú lateral, pulsa "Mov. Nómina". Allí, "¿Cómo funciona?" → "Recibir un contrato '
            'de otro moderador" te acompaña paso a paso.'
        ),
    },
}


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = cambio['accesos']
        if cambio['anterior'] in tarea.instrucciones:
            tarea.instrucciones = tarea.instrucciones.replace(cambio['anterior'], cambio['nuevo'], 1)
        tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = ''
        tarea.instrucciones = tarea.instrucciones.replace(cambio['nuevo'], cambio['anterior'], 1)
        tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0021_guia_baja_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
