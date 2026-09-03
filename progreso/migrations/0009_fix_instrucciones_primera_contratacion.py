from django.db import migrations

# 0004 describía la contratación como un único paso ("pulsa el botón 'Contrato'
# de su fila... completa los datos... confirma el asistente"), como si cada
# fila tuviera su propio botón y todo se guardara de una sola vez. En realidad
# (contratos/views.py: ContratoCreateView.form_valid + finalizar_contrato_wizard):
# - No hay un botón por fila: hay que hacer clic en la fila para seleccionarla,
#   lo que activa una barra de botones compartida arriba (list_aspir.html).
# - Es un asistente de DOS pantallas: la primera (Registrar Contrato) solo
#   guarda un borrador en la sesión, sin tocar la base de datos; el contrato
#   se guarda de verdad recién en la segunda pantalla (Movimiento de Nómina),
#   al pulsar "Confirmar Movimiento".
# - El Aspirante pasa de estado "Aspirante" a "Activo" automáticamente al
#   guardar el contrato (CAlta.save() -> actualizar_aspirante()); el usuario
#   no tiene que cambiar ningún estado a mano.
INSTRUCCIONES_ANTERIORES = (
    'Ve al listado de Aspirantes.\n'
    'Selecciona un Aspirante y pulsa el botón "Contrato" de su fila.\n'
    'Completa los datos del contrato: cargo, tipo de contrato y fecha de alta.\n'
    'Confirma el asistente para finalizar la contratación.'
)

INSTRUCCIONES_NUEVAS = (
    'Ve al listado de Aspirantes.\n'
    'Haz clic sobre la fila del Aspirante que vas a contratar: se resalta y se activan los botones de arriba.\n'
    'Pulsa el botón verde "Contrato" (el del ícono de la firma).\n'
    'En la primera pantalla, completa la Unidad Organizativa, el Departamento, el Cargo y los demás datos del contrato, y pulsa "Continuar".\n'
    'En la segunda pantalla ("Movimiento de Nómina"), completa la Fecha Efectiva y pulsa "Confirmar Movimiento".\n'
    'Listo: el Aspirante pasa a estado "Activo" de forma automática, no hace falta hacer nada más.'
)


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primera_contratacion').update(instrucciones=INSTRUCCIONES_NUEVAS)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primera_contratacion').update(instrucciones=INSTRUCCIONES_ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0008_fix_especialidad_primer_aspirante'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
