from django.db import migrations

# El texto anterior solo mencionaba CI, sexo, nombre y apellidos, y decía
# "Guarda el formulario" sin más. En la práctica el formulario también exige
# Provincia, Municipio, Raza y Nivel Educativo: un usuario nuevo que seguía
# la guía al pie de la letra se topaba con el modal sin poder guardar y sin
# saber por qué. Se reescribe con lenguaje sencillo, pensado para alguien sin
# experiencia previa con Orbith ni con formularios web.
INSTRUCCIONES_ANTERIORES = (
    'Ve al menú "Aspirante" en la barra lateral.\n'
    'Haz clic en el botón para agregar un nuevo Aspirante.\n'
    'Completa el Documento de Identidad, el sexo, el nombre y los apellidos.\n'
    'Guarda el formulario.'
)

INSTRUCCIONES_NUEVAS = (
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


def corregir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(instrucciones=INSTRUCCIONES_NUEVAS)


def revertir(apps, schema_editor):
    TareaGuia = apps.get_model('progreso', 'TareaGuia')
    TareaGuia.objects.filter(codigo='primer_aspirante').update(instrucciones=INSTRUCCIONES_ANTERIORES)


class Migration(migrations.Migration):

    dependencies = [
        ('progreso', '0005_fix_url_primer_aspirante'),
    ]

    operations = [
        migrations.RunPython(corregir, revertir),
    ]
