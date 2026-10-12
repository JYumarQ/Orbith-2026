from django.db import migrations

# "Completa tu primer cierre mensual" tiene recorrido visual (static/js/recorrido_cierre.js).
CODIGO = 'primer_cierre_declarado'
ACCESOS = (
    'Declarar en el Gestor | /estructuras/gestor/ | primer_cierre_declarado:gestor\n'
    'Ver Cierres Mensuales | /cierres/ | primer_cierre_declarado:cierres'
)
LINEA = (
    'En el Gestor de Plantilla, "¿Cómo funciona?" → "Declarar el cierre mensual" te acompaña paso a paso. '
    'Se declara del día 20 al 25 de cada mes.'
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
        ('progreso', '0036_guia_hallazgo_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
