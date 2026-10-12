from django.db import migrations

# Categoría "Exportar": una tarea por sección, reconocidas por la ruta de la
# vista (progreso/middleware.py::EXPORTACION_POR_RUTA y EXPORTACION_POR_MODULO).
# Sustituye a "Exporta tu primer PDF / Word / Excel", que contaban cualquier
# exportación de la aplicación. Por decisión del usuario se BORRAN (con los
# logros que tuviera cada uno): todos empiezan de cero en la categoría nueva.
ANTIGUAS = ['primera_exportacion_pdf', 'primera_exportacion_word', 'primera_exportacion_excel']

NUEVAS = [
    {
        'codigo': 'exportar_informe_inteligente', 'orden': 60, 'partes': 'pdf,word,excel',
        'titulo': 'Exporta un Informe Inteligente',
        'descripcion': 'Exportaste un Informe Inteligente a PDF, a Word y a Excel.',
        'modulo': 'Informe Inteligente', 'url_relacionada': '/informe-inteligente/',
        'accesos': 'Ir al Informe Inteligente | /informe-inteligente/ | exportar_informe_inteligente:informe',
        'instrucciones': (
            'En el menú lateral, dentro de "Informes", pulsa "Informe Inteligente". Allí, "¿Cómo funciona?" → '
            '"Exportar a PDF, Word o Excel" te acompaña paso a paso.\n'
            'Genera un informe: los botones de exportar aparecen sobre la tabla de resultados.\n'
            'Exporta el informe en los tres formatos: PDF, Word y Excel. Pueden ser informes distintos.\n'
            'Si el informe no cabe en un PDF o un Word, Orbith te avisa antes y te propone alternativas.'
        ),
    },
    {
        'codigo': 'exportar_informes_rrhh', 'orden': 61, 'partes': 'pdf,word,excel',
        'titulo': 'Exporta un Informe RRHH',
        'descripcion': 'Exportaste Informes RRHH a PDF, a Word y a Excel.',
        'modulo': 'Informes RRHH', 'url_relacionada': '/informes/economia/',
        'accesos': 'Ir a Informes RRHH | /informes/economia/ | exportar_informes_rrhh:informes',
        'instrucciones': (
            'En el menú lateral, dentro de "Informes", pulsa "Informes RRHH". Allí, "¿Cómo funciona?" → '
            '"Exportar este informe" te acompaña paso a paso.\n'
            'Con los botones PDF, Word y Excel de la barra superior se descarga el informe tal como lo ves.\n'
            'Exporta en los tres formatos. Cuenta cualquiera de los siete informes: por ejemplo, el PDF del '
            'Consolidado, el Word de Misiones y el Excel de Altas y Bajas.'
        ),
    },
    {
        'codigo': 'exportar_lista_contratos', 'orden': 62, 'partes': '',
        'titulo': 'Exporta la lista de contratos',
        'descripcion': 'Exportaste la lista de contratos a Excel.',
        'modulo': 'Contratos', 'url_relacionada': '/contrato/list_contrato/', 'accesos': '',
        'instrucciones': (
            'En el menú lateral, pulsa "Contrato".\n'
            'Pulsa el botón "Exportar a Excel" de la lista.\n'
            'Elige si quieres todas las unidades o solo algunas y confirma: se descarga el Excel.'
        ),
    },
    {
        'codigo': 'exportar_contrato_modificacion', 'orden': 63, 'partes': 'creacion,modificacion',
        'titulo': 'Exporta un contrato y una modificación',
        'descripcion': 'Exportaste un Contrato de Trabajo y una Modificación al contrato en Word.',
        'modulo': 'Contratos', 'url_relacionada': '/contrato/list_contrato/', 'accesos': '',
        'instrucciones': (
            'En el menú lateral, pulsa "Contrato".\n'
            'Haz clic en la fila de un trabajador y pulsa el botón "Exportar Contrato".\n'
            'Elige el tipo de documento: "Contrato de Trabajo (Creación)" o "Modificación al Contrato de Trabajo" '
            '(esta pide escribir en Observaciones el motivo del cambio), y descárgalo.\n'
            'Exporta los dos tipos para completar la tarea.'
        ),
    },
    {
        'codigo': 'exportar_movimiento_nomina', 'orden': 64, 'partes': '',
        'titulo': 'Exporta un movimiento de nómina',
        'descripcion': 'Exportaste el documento de un movimiento de nómina en Word.',
        'modulo': 'Contratos', 'url_relacionada': '/contrato/list_contrato/', 'accesos': '',
        'instrucciones': (
            'En el menú lateral, pulsa "Contrato".\n'
            'Haz doble clic en la fila de un trabajador: se abre su histórico.\n'
            'Haz clic en un movimiento de la tabla y pulsa "Exportar Movimiento".\n'
            'También cuenta el documento que Orbith ofrece al confirmar un alta, un movimiento de nómina o una baja.'
        ),
    },
    {
        'codigo': 'exportar_historico_trabajador', 'orden': 65, 'partes': '',
        'titulo': 'Exporta el histórico de un trabajador',
        'descripcion': 'Exportaste en PDF el histórico completo de un trabajador.',
        'modulo': 'Contratos', 'url_relacionada': '/contrato/list_contrato/', 'accesos': '',
        'instrucciones': (
            'En el menú lateral, pulsa "Contrato".\n'
            'Haz doble clic en la fila de un trabajador: se abre su histórico.\n'
            'Pulsa "Exportar Todo": el PDF con todos sus movimientos se abre en otra pestaña.'
        ),
    },
    {
        'codigo': 'exportar_anexos', 'orden': 66, 'partes': '14,14a,14b',
        'titulo': 'Exporta los Anexos 14, 14A y 14B',
        'descripcion': 'Exportaste a Excel los Anexos 14, 14A y 14B.',
        'modulo': 'Anexos', 'url_relacionada': '/informes-anexo/anexo14/', 'accesos': '',
        'instrucciones': (
            'En el menú lateral, despliega "Gestor de Plantilla" y abre "Anexo 14".\n'
            'Pulsa "Solo Anexo 14" para descargar su Excel. El botón "Anexo 14 y 14A" descarga los dos en un '
            'mismo libro y cuenta para ambos.\n'
            'Haz lo mismo en "Anexo 14A" y en "Anexo 14B".'
        ),
    },
    {
        'codigo': 'exportar_prenomina', 'orden': 67, 'partes': '',
        'titulo': 'Exporta un reporte de Pre-Nómina',
        'descripcion': 'Exportaste a Excel un reporte de Pre-Nómina.',
        'modulo': 'Pre-Nómina', 'url_relacionada': '/prenomina/', 'accesos': '',
        'para_observador': False,
        'instrucciones': (
            'En el menú lateral, pulsa "Pre-Nómina".\n'
            'Abre un reporte de la lista.\n'
            'Pulsa "Exportar", arriba del reporte: se descarga en Excel.'
        ),
    },
]


def aplicar(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    # Borra también, en cascada, los logros que tuviera cada usuario.
    TareaGuia.objects.filter(codigo__in=ANTIGUAS).delete()
    for datos in NUEVAS:
        datos = dict(datos)
        codigo = datos.pop('codigo')
        TareaGuia.objects.update_or_create(codigo=codigo, defaults={'categoria': 'EXR', **datos})


def revertir(apps, schema_editor):
    """Quita las tareas nuevas y recrea las antiguas, pero SIN los logros que
    tenían los usuarios: esos se borraron al aplicar."""
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo__in=[d['codigo'] for d in NUEVAS]).delete()
    for orden, (codigo, formato) in zip((60, 70, 80), (('pdf', 'PDF'), ('word', 'Word'), ('excel', 'Excel'))):
        TareaGuia.objects.update_or_create(
            codigo=f'primera_exportacion_{codigo}',
            defaults={
                'titulo': f'Exporta tu primer {formato}' if codigo == 'pdf' else (
                    'Exporta tu primer documento Word' if codigo == 'word' else 'Exporta tu primer Excel'),
                'descripcion': f'Exportaste información de Orbith a {formato}.',
                'categoria': 'EXP', 'modulo': 'Exportaciones', 'url_relacionada': '/informe-inteligente/',
                'orden': orden,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0026_guia_partes_categoria_exportar'),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
