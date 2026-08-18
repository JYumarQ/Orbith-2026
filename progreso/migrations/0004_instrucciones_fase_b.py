from django.db import migrations

# Contenido de la Fase B: instrucciones paso a paso + enlace directo al
# módulo correspondiente, para cada tarea ya sembrada en
# 0002_seed_tareas.py. Verificado contra las plantillas y URLs reales de
# Orbith (no inventado): botones, rutas y textos existentes hoy en la app.
INSTRUCCIONES = {
    'primer_aspirante': (
        '/bolsa/add_aspir/',
        'Ve al menú "Aspirante" en la barra lateral.\n'
        'Haz clic en el botón para agregar un nuevo Aspirante.\n'
        'Completa el Documento de Identidad, el sexo, el nombre y los apellidos.\n'
        'Guarda el formulario.'
    ),
    'primera_contratacion': (
        '/bolsa/list_aspir/',
        'Ve al listado de Aspirantes.\n'
        'Selecciona un Aspirante y pulsa el botón "Contrato" de su fila.\n'
        'Completa los datos del contrato: cargo, tipo de contrato y fecha de alta.\n'
        'Confirma el asistente para finalizar la contratación.'
    ),
    'primer_movimiento_nomina': (
        '/contrato/movimientos/nomina/',
        'Ve a Contrato → Mov. Nómina.\n'
        'Selecciona el trabajador al que vas a aplicar el movimiento.\n'
        'Ajusta los datos que cambian (cargo, salario, unidad u otros) y la fecha efectiva.\n'
        'Guarda el movimiento.'
    ),
    'primera_baja': (
        '/contrato/list_contrato/',
        'Ve al listado de Contratos.\n'
        'Selecciona el trabajador y pulsa "Dar de Baja".\n'
        'Indica la fecha y la causa de la baja.\n'
        'Confirma la baja.'
    ),
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
    'primer_analisis_subsanacion': (
        '/subsanacion/',
        'Ve a Administración → Subsanación.\n'
        'Pulsa "Ejecutar nuevo análisis".\n'
        'Espera a que termine de revisar cada módulo.\n'
        'Consulta el índice de salud y los hallazgos detectados.'
    ),
    'primera_revision_hallazgo': (
        '/subsanacion/',
        'Ve a Administración → Subsanación.\n'
        'En el listado de hallazgos, pulsa "Ver detalle" sobre uno de ellos.\n'
        'Cambia su estado (revisado, corregido, ignorado, falso positivo) desde el modal.\n'
        'Si vas a ignorarlo o marcarlo falso positivo, deja una nota antes de guardar.'
    ),
    'primer_informe_favorito': (
        '/informe-inteligente/',
        'Ve a Informes → Informe Inteligente.\n'
        'Configura un informe con los campos que sueles usar.\n'
        'Pulsa "Guardar como favorito" y ponle un nombre.'
    ),
    'primer_cierre_declarado': (
        '/estructuras/gestor/',
        'Ve a Plantilla → Gestor de Plantilla.\n'
        'Selecciona tu Unidad Organizativa.\n'
        'Pulsa "Declarar actualizada" para el cierre del mes en curso.'
    ),
}


def cargar_instrucciones(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, (url, instrucciones) in INSTRUCCIONES.items():
        TareaGuia.objects.filter(codigo=codigo).update(
            url_relacionada=url, instrucciones=instrucciones,
        )


def vaciar_instrucciones(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo__in=INSTRUCCIONES.keys()).update(
        url_relacionada='', instrucciones='',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0003_tareaguia_instrucciones'),
    ]

    operations = [
        migrations.RunPython(cargar_instrucciones, vaciar_instrucciones),
    ]
