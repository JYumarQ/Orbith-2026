from django.db import migrations

# "Aprende a reportar un problema" tiene recorrido visual (static/js/recorrido_reporte.js).
# El formulario está en una ventana común a todas las pantallas: el acceso lleva al
# Dashboard y la guía empieza allí, por la foto de perfil.
CODIGO = 'primer_reporte_problema'
ACCESOS = 'Empezar la guía | / | primer_reporte_problema:global'
LINEA = (
    'En la ventana "Acerca de Orbith", el enlace "¿Cómo funciona?" bajo "Reportar problema" te '
    'acompaña paso a paso.'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if LINEA not in tarea.instrucciones:
        tarea.instrucciones = LINEA + '\n' + tarea.instrucciones
    tarea.save(update_fields=['accesos', 'instrucciones'])


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ''
    tarea.instrucciones = tarea.instrucciones.replace(LINEA + '\n', '', 1)
    tarea.save(update_fields=['accesos', 'instrucciones'])


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0034_guia_recordatorios_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
