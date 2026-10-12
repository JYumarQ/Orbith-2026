from django.db import migrations

# Exportar (una sola guía para PDF, Word y Excel) y Guardar como favorito tienen
# recorrido visual en el Informe Inteligente (static/js/recorrido_informe.js).
ANTERIOR_EXPORTAR = (
    'Genera primero un informe en Informe Inteligente: los botones de exportar solo '
    'aparecen cuando hay resultados en pantalla.'
)
NUEVO_EXPORTAR = (
    'En el menú lateral, dentro de "Informes", pulsa "Informe Inteligente". Allí, '
    '"¿Cómo funciona?" → "Exportar a PDF, Word o Excel" te acompaña paso a paso. Los '
    'botones de exportar solo aparecen cuando hay un informe generado en pantalla.'
)

CAMBIOS = {
    'primera_exportacion_pdf': {
        'accesos': 'Ir al Informe Inteligente | /informe-inteligente/ | primera_exportacion_pdf:informe',
        'anterior': ANTERIOR_EXPORTAR,
        'nuevo': NUEVO_EXPORTAR,
    },
    'primera_exportacion_word': {
        'accesos': 'Ir al Informe Inteligente | /informe-inteligente/ | primera_exportacion_word:informe',
        'anterior': ANTERIOR_EXPORTAR,
        'nuevo': NUEVO_EXPORTAR,
    },
    'primera_exportacion_excel': {
        'accesos': 'Ir al Informe Inteligente | /informe-inteligente/ | primera_exportacion_excel:informe',
        'anterior': ANTERIOR_EXPORTAR,
        'nuevo': NUEVO_EXPORTAR,
    },
    'primer_informe_favorito': {
        'accesos': 'Ir al Informe Inteligente | /informe-inteligente/ | primer_informe_favorito:informe',
        'anterior': 'Ve a Informes → Informe Inteligente y arma el informe que sueles consultar.',
        'nuevo': (
            'En el menú lateral, dentro de "Informes", pulsa "Informe Inteligente" y arma el '
            'informe que sueles consultar. "¿Cómo funciona?" → "Guardar como favorito" te '
            'acompaña paso a paso.'
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
        ('progreso', '0023_guia_informe_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
