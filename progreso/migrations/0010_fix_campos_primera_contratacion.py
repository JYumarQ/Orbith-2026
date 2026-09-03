from django.db import migrations

# Dos correcciones sobre el texto que dejó 0009:
#
# 1. "completa... el Cargo y los demás datos del contrato" no decía CUÁLES son
#    esos "demás datos" obligatorios. Verificado contra contratos/forms.py
#    (CAltaForm): Unidad/Departamento/Cargo y 'tipo' son ModelChoiceField sin
#    required=False (obligatorios por defecto); 'no_expediente' lo exige
#    clean_no_expediente(); 'reg_militar' y 'fecha_alta_entidad' se marcan
#    required=True explícitamente en __init__(); 'motivo' es obligatorio solo
#    si el Tipo de Contrato elegido lo exige (clean(), NTipoContrato.requiere_motivo);
#    'tridente' es obligatorio solo si el salario es Dinámico y el cargo no es
#    de Cuadro (misma regla).
#
# 2. Decía "completa la Fecha Efectiva" en la pantalla de Movimiento de
#    Nómina. En el asistente de primera contratación (is_wizard=True) el
#    campo Fecha Efectiva viene bloqueado y en gris (clase
#    'wizard-bloqueado' en movimiento_nomina.html): se autocompleta con la
#    F. de Contratación ya escrita en la pantalla anterior y no se puede
#    tocar. El campo que el usuario sí completa a mano ahí es la Fecha de
#    Solicitud.
INSTRUCCIONES_ANTERIORES = (
    'Ve al listado de Aspirantes.\n'
    'Haz clic sobre la fila del Aspirante que vas a contratar: se resalta y se activan los botones de arriba.\n'
    'Pulsa el botón verde "Contrato" (el del ícono de la firma).\n'
    'En la primera pantalla, completa la Unidad Organizativa, el Departamento, el Cargo y los demás datos del contrato, y pulsa "Continuar".\n'
    'En la segunda pantalla ("Movimiento de Nómina"), completa la Fecha Efectiva y pulsa "Confirmar Movimiento".\n'
    'Listo: el Aspirante pasa a estado "Activo" de forma automática, no hace falta hacer nada más.'
)

INSTRUCCIONES_NUEVAS = (
    'Ve al listado de Aspirantes.\n'
    'Haz clic sobre la fila del Aspirante que vas a contratar: se resalta y se activan los botones de arriba.\n'
    'Pulsa el botón verde "Contrato" (el del ícono de la firma).\n'
    'En la primera pantalla, elige la Unidad Organizativa, el Departamento y el Cargo (cada uno filtra al siguiente).\n'
    'Completa también el No. de Expediente, el Tipo de Contrato, el Registro Militar y la F. Alta Entidad: son obligatorios siempre.\n'
    'Si el Tipo de Contrato elegido lo exige, aparecerá el Motivo de Contrato: complétalo también.\n'
    'Si el salario es Dinámico y el cargo no es de Cuadro, elige además el Tridente.\n'
    'Pulsa "Continuar".\n'
    'En la segunda pantalla ("Movimiento de Nómina"), la Fecha Efectiva ya viene completada y bloqueada: no hay que tocarla. Escribe la Fecha de Solicitud y pulsa "Confirmar Movimiento".\n'
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
        ('progreso', '0009_fix_instrucciones_primera_contratacion'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
