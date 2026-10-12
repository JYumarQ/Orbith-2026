from django.db import migrations

# Guías visuales de los Anexos (static/js/recorrido_anexos.js): un acceso por anexo.
CODIGO = 'exportar_anexos'
ACCESOS = (
    'Anexo 14 | /informes-anexo/anexo14/ | exportar_anexos:anexo14\n'
    'Anexo 14A | /informes-anexo/anexo14a/ | exportar_anexos:anexo14a\n'
    'Anexo 14B | /informes-anexo/anexo14b/ | exportar_anexos:anexo14b'
)
LINEA = (
    'Cada anexo tiene su "¿Cómo funciona?" junto al título, que recorre la pantalla y te acompaña a exportarlo; '
    'al terminar, te ofrece seguir en el anexo que te falte. El botón "?" explica qué es cada anexo.'
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
        ('progreso', '0028_guia_exportar_contratos_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
