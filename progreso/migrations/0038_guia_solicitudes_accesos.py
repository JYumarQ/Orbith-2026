from django.db import migrations

# Guías de Solicitudes (static/js/recorrido_solicitudes.js): enviar (Moderador) y
# decidir (Administrador).
CAMBIOS = {
    'primera_solicitud_enviada': {
        'accesos': (
            'Desde el Gestor | /estructuras/gestor/ | primera_solicitud_enviada:gestor\n'
            'Ver mis solicitudes | /solicitudes/?tab=espera | primera_solicitud_enviada:solicitudes'
        ),
        'linea': ('En el Gestor de Plantilla, "¿Cómo funciona?" → "Enviar una solicitud de cambio" te acompaña '
                  'paso a paso editando un cargo.'),
    },
    'primera_solicitud_decidida': {
        'accesos': 'Ir a Solicitudes | /solicitudes/?tab=espera | primera_solicitud_decidida:solicitudes',
        'linea': 'En Solicitudes, "¿Cómo funciona?" → "Decidir una solicitud" te acompaña paso a paso.',
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
        ('progreso', '0037_guia_cierre_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
