from django.db import migrations

# Tarea nueva "Busca con prefijos" (Explorar), decidida por el usuario el
# 06-10-2026. La reconoce `progreso.middleware.busco_con_prefijo` y la enseña
# `static/js/recorrido_busqueda.js`.
CODIGO = 'primera_busqueda_prefijos'
DATOS = {
    'titulo': 'Busca con prefijos',
    'descripcion': 'Buscaste con un prefijo (E:, N:, CI:…) en Aspirantes, Bajas, Contratos o Subsanación.',
    'categoria': 'EXP',
    'modulo': 'Búsqueda',
    'url_relacionada': '/contrato/list_contrato/',
    'orden': 54,
    'accesos': (
        'En Contratos | /contrato/list_contrato/ | primera_busqueda_prefijos:contratos\n'
        'En Aspirantes | /bolsa/list_aspir/ | primera_busqueda_prefijos:aspirantes'
    ),
    'instrucciones': (
        'Los buscadores de Aspirantes, Bajas, Contratos y Subsanación entienden prefijos para buscar en un dato '
        'concreto. En esas pantallas, "¿Cómo funciona?" → "Buscar con prefijos" te acompaña paso a paso.\n'
        'E: expediente (E:8855) · N: nombre y apellidos (N:Juan Pérez) · CI: carnet, vale el principio · '
        'CA: cargo · U: unidad organizativa, vale parte del nombre · COD: código de regla, solo en Subsanación.\n'
        'Se pueden combinar: N:Juan U:Florida. Da igual mayúsculas o acentos.\n'
        'El botón "?" junto a cada buscador dice qué prefijos valen en esa pantalla.'
    ),
}


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.update_or_create(codigo=CODIGO, defaults=DATOS)


def revertir(apps, schema_editor):
    apps.get_model('progreso', 'TareaGuia').objects.filter(codigo=CODIGO).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0032_guia_subsanacion_accesos'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
