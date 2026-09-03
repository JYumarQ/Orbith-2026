from django.db import migrations

# 0007 decía que la Especialidad solo se habilita con Nivel Superior. Es
# incorrecto: en bolsa/forms.py (AspiranteForm.__init__) también se habilita
# con Técnico Medio (TM), solo que con una lista de especialidades distinta
# (`educ_superior=False` en vez de `True`). Con cualquier otro nivel el campo
# sigue deshabilitado.
INSTRUCCIONES_ANTERIORES = (
    'En el menú lateral, pulsa "Aspirante": te lleva directo al listado.\n'
    'Pulsa el botón "Nuevo": se abrirá una ventana con el formulario.\n'
    'Escribe el número de Carné de Identidad; el sexo y la edad se completan solos.\n'
    'Completa el Nombre y los dos Apellidos.\n'
    'Elige la Provincia y, después, el Municipio (el Municipio se habilita solo cuando ya elegiste la Provincia).\n'
    'Elige la Raza y el Nivel Educativo: son obligatorios para poder guardar.\n'
    'Si el Nivel Educativo es "Nivel Superior", puedes elegir además una Especialidad y, si corresponde, marcar "Título de Oro" (con cualquier otro nivel, ese campo queda deshabilitado).\n'
    'Revisa que ningún campo del formulario haya quedado marcado en rojo o en amarillo.\n'
    'Pulsa "Guardar" y confirma en el mensaje que aparece.'
)

INSTRUCCIONES_NUEVAS = (
    'En el menú lateral, pulsa "Aspirante": te lleva directo al listado.\n'
    'Pulsa el botón "Nuevo": se abrirá una ventana con el formulario.\n'
    'Escribe el número de Carné de Identidad; el sexo y la edad se completan solos.\n'
    'Completa el Nombre y los dos Apellidos.\n'
    'Elige la Provincia y, después, el Municipio (el Municipio se habilita solo cuando ya elegiste la Provincia).\n'
    'Elige la Raza y el Nivel Educativo: son obligatorios para poder guardar.\n'
    'Si el Nivel Educativo es "Técnico Medio" o "Nivel Superior", puedes elegir además una Especialidad (la lista cambia según el nivel; con cualquier otro nivel, ese campo queda deshabilitado).\n'
    'Si el Nivel Educativo es "Nivel Superior", puedes marcar además "Título de Oro" (con cualquier otro nivel, ese campo queda deshabilitado).\n'
    'Revisa que ningún campo del formulario haya quedado marcado en rojo o en amarillo.\n'
    'Pulsa "Guardar" y confirma en el mensaje que aparece.'
)


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(instrucciones=INSTRUCCIONES_NUEVAS)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(instrucciones=INSTRUCCIONES_ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0007_fix_paso1_y_titulo_oro_primer_aspirante'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
