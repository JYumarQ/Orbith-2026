from django.db import migrations

# "Consulta los Informes RRHH" tiene recorrido visual (static/js/recorrido_informes_rrhh.js).
CODIGO = 'primer_informe_rrhh'
ACCESOS = 'Ir a Informes RRHH | /informes/economia/ | primer_informe_rrhh:informes'
ANTERIOR = (
    'En el menú lateral, dentro de "Informes", pulsa "Informes RRHH": se abre el '
    'Consolidado de la Fuerza de Trabajo.'
)
NUEVO = (
    'En el menú lateral, dentro de "Informes", pulsa "Informes RRHH": se abre el '
    'Consolidado de la Fuerza de Trabajo. El botón "¿Cómo funciona?" junto al título te '
    'acompaña paso a paso, y el botón "?" junto al selector explica el informe que tienes abierto.'
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
        ('progreso', '0024_guia_exportar_favorito_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
