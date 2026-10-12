from django.db import migrations

# "Revisa manualmente tu primer hallazgo" tiene recorrido visual
# (static/js/recorrido_subsanacion.js).
CODIGO = 'primera_revision_hallazgo'
ACCESOS = 'Ir a Subsanación | /subsanacion/ | primera_revision_hallazgo:subsanacion'
LINEA = 'En Subsanación, "¿Cómo funciona?" → "Revisar un hallazgo" te acompaña paso a paso.'


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
        ('progreso', '0035_guia_reporte_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
