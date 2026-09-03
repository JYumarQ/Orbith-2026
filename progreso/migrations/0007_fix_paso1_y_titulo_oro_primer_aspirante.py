from django.db import migrations

# Dos correcciones sobre el texto que dejó 0006:
#
# 1. El paso 1 decía "entra en 'Aspirante' y luego en 'Lista de Aspirantes'",
#    como si hubiera un submenú de dos niveles. En el menú lateral real
#    (templates/base/sidebar.html) "Aspirante" es un único enlace que lleva
#    directo al listado (`list_aspir`) — no existe ese segundo clic.
# 2. No se avisaba que "Título de Oro" solo se puede marcar si el Nivel
#    Educativo es "Nivel Superior" (el campo se deshabilita solo si se elige
#    otro nivel, ver static/js/aspirante_formulario.js). Un usuario que lo
#    marcaba antes de elegir el nivel se encontraba con que se le desmarcaba
#    solo, sin que la guía se lo explicara.
INSTRUCCIONES_ANTERIORES = (
    'En el menú lateral, entra en "Aspirante" y luego en "Lista de Aspirantes".\n'
    'Pulsa el botón "Nuevo": se abrirá una ventana con el formulario.\n'
    'Escribe el número de Carné de Identidad; el sexo y la edad se completan solos.\n'
    'Completa el Nombre y los dos Apellidos.\n'
    'Elige la Provincia y, después, el Municipio (el Municipio se habilita solo cuando ya elegiste la Provincia).\n'
    'Elige la Raza y el Nivel Educativo: son obligatorios para poder guardar.\n'
    'Si el Nivel Educativo es "Nivel Superior", puedes elegir además una Especialidad.\n'
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
    'Si el Nivel Educativo es "Nivel Superior", puedes elegir además una Especialidad y, si corresponde, marcar "Título de Oro" (con cualquier otro nivel, ese campo queda deshabilitado).\n'
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
        ('progreso', '0006_fix_instrucciones_primer_aspirante'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
