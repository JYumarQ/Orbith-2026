from django.db import migrations

# Guías de Recordatorios (static/js/recorrido_recordatorios.js).
URL = '/notificaciones/notificaciones/lista/'
CAMBIOS = {
    'primer_recordatorio_completado': {
        'accesos': 'Ir a Recordatorios | ' + URL + '?tab=recordatorios&sub=sistema | primer_recordatorio_completado:sistema',
        'linea': 'En Notificaciones, "¿Cómo funciona?" → "Completar un recordatorio" te acompaña paso a paso.',
    },
    'primer_recordatorio_creado': {
        'accesos': ('Ir a Recordatorios | ' + URL + '?tab=recordatorios&sub=administracion'
                    ' | primer_recordatorio_creado:administracion'),
        'linea': 'En Notificaciones, "¿Cómo funciona?" → "Crear un recordatorio" te acompaña paso a paso.',
    },
}


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = cambio['accesos']
        if cambio['linea'] not in tarea.instrucciones:
            tarea.instrucciones = cambio['linea'] + '\n' + tarea.instrucciones
        tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, cambio in CAMBIOS.items():
        tarea = TareaGuia.objects.filter(codigo=codigo).first()
        if not tarea:
            continue
        tarea.accesos = ''
        tarea.instrucciones = tarea.instrucciones.replace(cambio['linea'] + '\n', '', 1)
        tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0033_guia_busqueda_prefijos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
