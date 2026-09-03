from django.db import migrations

# Las cinco tareas del Informe Inteligente estaban desactualizadas:
#
# * Los botones de exportación se llaman «PDF», «Word» y «Excel» a secas (ver
#   partials/tabla_resultados.html), no «Exportar a PDF».
# * Solo aparecen DESPUÉS de generar el informe y si hay al menos una fila;
#   el texto anterior no lo decía y quien pulsaba antes no encontraba el botón.
# * La de Excel mandaba al Anexo 14, un módulo distinto, cuando el propio
#   Informe Inteligente exporta a Excel igual que a PDF y Word.
# * La de favoritos no mencionaba que el botón está deshabilitado hasta generar
#   el informe al menos una vez, que es la duda más habitual.
# * Ninguna reflejaba el selector de fecha (consultar un cierre mensual) ni que
#   los favoritos se pueden editar y compartir.
TEXTOS_ANTERIORES = {
    'primer_informe_generado': (
        '/informe-inteligente/',
        'Ve a Informes → Informe Inteligente.\n'
        'Elige el tipo de informe que quieres consultar.\n'
        'Selecciona los campos y filtros que te interesan.\n'
        'Pulsa "Generar informe" para ver los resultados.'
    ),
    'primera_exportacion_pdf': (
        '/informe-inteligente/',
        'Genera un informe en Informe Inteligente (o cualquier reporte de Orbith).\n'
        'Con los resultados en pantalla, pulsa el botón "Exportar a PDF".\n'
        'Descarga el archivo generado.'
    ),
    'primera_exportacion_word': (
        '/informe-inteligente/',
        'Genera un informe en Informe Inteligente.\n'
        'Con los resultados en pantalla, pulsa el botón "Exportar a Word".\n'
        'Descarga el archivo generado.'
    ),
    'primera_exportacion_excel': (
        '/informes-anexo/anexo14/',
        'Ve a Plantilla → Anexo 14.\n'
        'Con la información en pantalla, pulsa el botón "Excel" de la barra de exportación.\n'
        'Descarga el archivo generado.'
    ),
    'primer_informe_favorito': (
        '/informe-inteligente/',
        'Ve a Informes → Informe Inteligente.\n'
        'Configura un informe con los campos que sueles usar.\n'
        'Pulsa "Guardar como favorito" y ponle un nombre.'
    ),
}

TEXTOS_NUEVOS = {
    'primer_informe_generado': (
        '/informe-inteligente/',
        'Ve a Informes → Informe Inteligente.\n'
        'En "¿Sobre qué desea informar?", elige el tipo de datos: Contratos, Bajas, Plantilla, Aspirantes o Movimientos de Nómina.\n'
        'En el panel 1, marca los campos que quieres ver como columnas. Salen en el mismo orden en que los marcas.\n'
        'Si necesitas acotar, añade filtros en el panel 2. Todos los filtros se cumplen a la vez.\n'
        'Pulsa "Generar informe": arriba verás un resumen y debajo la tabla.\n'
        'Cada panel tiene un icono de ayuda (?) que explica esa parte si tienes dudas.'
    ),
    'primera_exportacion_pdf': (
        '/informe-inteligente/',
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "PDF".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.'
    ),
    'primera_exportacion_word': (
        '/informe-inteligente/',
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Word".\n'
        'El documento se descarga con las mismas columnas, filtros y orden que ves en pantalla.'
    ),
    'primera_exportacion_excel': (
        '/informe-inteligente/',
        'Genera primero un informe en Informe Inteligente: los botones de exportar solo aparecen cuando hay resultados en pantalla.\n'
        'Sobre la tabla de resultados, pulsa el botón "Excel".\n'
        'El archivo se descarga con las mismas columnas, filtros y orden que ves en pantalla.\n'
        'Otros módulos, como Plantilla → Anexo 14, tienen su propio botón de Excel.'
    ),
    'primer_informe_favorito': (
        '/informe-inteligente/',
        'Ve a Informes → Informe Inteligente y arma el informe que sueles consultar.\n'
        'Pulsa "Generar informe": el botón "Guardar como favorito" está apagado hasta que lo generes al menos una vez.\n'
        'Pulsa "Guardar como favorito", ponle un nombre y guárdalo.\n'
        'Lo encontrarás en "Mis favoritos e historial", arriba a la derecha. Desde ahí puedes volver a abrirlo, renombrarlo con el lápiz, o enviárselo a otro usuario con el botón de compartir.'
    ),
}


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, (url, instrucciones) in TEXTOS_NUEVOS.items():
        TareaGuia.objects.filter(codigo=codigo).update(
            url_relacionada=url, instrucciones=instrucciones)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, (url, instrucciones) in TEXTOS_ANTERIORES.items():
        TareaGuia.objects.filter(codigo=codigo).update(
            url_relacionada=url, instrucciones=instrucciones)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0013_fix_instrucciones_primera_baja'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
