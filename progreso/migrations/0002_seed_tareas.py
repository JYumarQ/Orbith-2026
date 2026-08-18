from django.db import migrations

# Catálogo inicial deliberadamente pequeño: cada tarea representa una acción
# de negocio real y significativa, no un clic o un contador arbitrario. Ver
# progreso/servicios.py y los puntos de instrumentación en cada app para el
# código que completa cada una.
TAREAS = [
    # (codigo, titulo, descripcion, categoria, modulo, orden)
    ('primer_aspirante', 'Crea tu primer Aspirante',
     'Registraste a tu primer Aspirante en Orbith.', 'PRI', 'Aspirantes', 10),
    ('primera_contratacion', 'Realiza tu primera contratación',
     'Completaste el proceso de contratación de un Aspirante.', 'PRI', 'Contratos', 20),
    ('primer_movimiento_nomina', 'Registra tu primer movimiento de nómina',
     'Registraste un movimiento de nómina para un trabajador.', 'PRI', 'Contratos', 30),
    ('primera_baja', 'Completa tu primer proceso de baja',
     'Completaste el trámite administrativo de una baja.', 'PRI', 'Contratos', 40),

    ('primer_informe_generado', 'Genera tu primer informe',
     'Generaste un informe con Informe Inteligente.', 'EXP', 'Informe Inteligente', 50),
    ('primera_exportacion_pdf', 'Exporta tu primer PDF',
     'Exportaste información de Orbith a PDF.', 'EXP', 'Exportaciones', 60),
    ('primera_exportacion_word', 'Exporta tu primer documento Word',
     'Exportaste información de Orbith a Word.', 'EXP', 'Exportaciones', 70),
    ('primera_exportacion_excel', 'Exporta tu primer Excel',
     'Exportaste información de Orbith a Excel.', 'EXP', 'Exportaciones', 80),
    ('primer_analisis_subsanacion', 'Ejecuta tu primer análisis de Subsanación',
     'Lanzaste un análisis de integridad de datos en Subsanación.', 'EXP', 'Subsanación', 90),

    ('primera_revision_hallazgo', 'Revisa manualmente tu primer hallazgo',
     'Revisaste manualmente un hallazgo detectado por Subsanación.', 'DOM', 'Subsanación', 100),
    ('primer_informe_favorito', 'Guarda tu primer informe como favorito',
     'Guardaste un informe de Informe Inteligente como favorito.', 'DOM', 'Informe Inteligente', 110),
    ('primer_cierre_declarado', 'Completa tu primer cierre mensual',
     'Declaraste actualizada tu unidad para el cierre mensual.', 'DOM', 'Cierres', 120),
]


def crear_tareas(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    for codigo, titulo, descripcion, categoria, modulo, orden in TAREAS:
        TareaGuia.objects.update_or_create(
            codigo=codigo,
            defaults={
                'titulo': titulo,
                'descripcion': descripcion,
                'categoria': categoria,
                'modulo': modulo,
                'orden': orden,
            },
        )


def eliminar_tareas(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo__in=[codigo for codigo, *_ in TAREAS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_tareas, eliminar_tareas),
    ]
