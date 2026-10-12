from django.db import migrations

# "Genera tu primer informe" tiene recorrido visual (static/js/recorrido_informe.js).
CODIGO = 'primer_informe_generado'
ACCESOS = 'Ir al Informe Inteligente | /informe-inteligente/ | primer_informe_generado:informe'
ANTERIOR = 'Ve a Informes → Informe Inteligente.'
NUEVO = (
    'En el menú lateral, dentro de "Informes", pulsa "Informe Inteligente". '
    'El botón "¿Cómo funciona?" de la cabecera te acompaña paso a paso.'
)


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    tarea = TareaGuia.objects.filter(codigo=CODIGO).first()
    if not tarea:
        return
    tarea.accesos = ACCESOS
    if ANTERIOR in tarea.instrucciones:
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
        ('progreso', '0022_guia_ceder_recibir_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
