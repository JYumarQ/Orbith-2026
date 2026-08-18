from django.db import migrations

# `pages/aspirante/add_aspir.html` es un fragmento de modal (no extiende
# `base/base.html`): está pensado para cargarse por AJAX dentro del modal de
# la lista de Aspirantes, nunca para visitarse como página completa. Navegar
# ahí directamente rompía el layout y no ejecutaba ningún script del sitio
# (ni el widget del modo guiado). El resto de los enlaces de la Fase B ya
# apuntan a páginas reales que sí extienden base.html; se dejan igual.
URL_ANTERIOR = '/bolsa/add_aspir/'
URL_CORRECTA = '/bolsa/list_aspir/'


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(url_relacionada=URL_CORRECTA)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(url_relacionada=URL_ANTERIOR)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0004_instrucciones_fase_b'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
