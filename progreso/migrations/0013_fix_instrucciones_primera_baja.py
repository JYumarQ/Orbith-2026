from django.db import migrations

# El texto original (0004) decía "Selecciona el trabajador y pulsa 'Dar de
# Baja'... Indica la fecha y la causa de la baja... Confirma la baja", como si
# hubiera una sola fecha y un solo paso de confirmación. Verificado contra
# contratos/views.py (ContratoDeleteView.post) y
# templates/pages/contrato/list_contrato.html (#modalBajaContrato):
# - Hay que hacer clic en la fila para seleccionarla (no hay botón por fila).
# - El formulario pide DOS fechas obligatorias (Fecha de Baja y Fecha de
#   Documento) y una Causa de Baja obligatoria (lista desplegable); la Fecha
#   de Baja no puede ser anterior al último movimiento de nómina registrado.
# - Tras pulsar "Confirmar Baja" en el formulario, aparece una segunda
#   confirmación (SweetAlert) antes de guardar de verdad.
INSTRUCCIONES_ANTERIORES = (
    'Ve al listado de Contratos.\n'
    'Selecciona el trabajador y pulsa "Dar de Baja".\n'
    'Indica la fecha y la causa de la baja.\n'
    'Confirma la baja.'
)

INSTRUCCIONES_NUEVAS = (
    'Ve a Contrato → Lista de Contratos.\n'
    'Haz clic sobre la fila del trabajador para seleccionarlo: se activan los botones de arriba.\n'
    'Pulsa el botón rojo "Dar de Baja".\n'
    'En el Formulario de Baja, completa la Fecha de Baja, la Fecha de Documento y la Causa de Baja: las tres son obligatorias. La Fecha de Baja no puede ser anterior al último movimiento de nómina registrado del trabajador.\n'
    'Observaciones y los interruptores "Cobró sistema de pago" / "Completar cargo" son opcionales.\n'
    'Pulsa "Confirmar Baja" y, en el mensaje que aparece, confirma de nuevo con "Sí, dar de baja".\n'
    'Al terminar, el sistema te ofrece exportar el PDF del movimiento generado.'
)


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primera_baja').update(instrucciones=INSTRUCCIONES_NUEVAS)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primera_baja').update(instrucciones=INSTRUCCIONES_ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0012_fix_fecha_solicitud_movimientos'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
