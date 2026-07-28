from django.db import migrations


def poblar_valor_numerico(apps, schema_editor):
    NGrupoEscala = apps.get_model('nomencladores', 'NGrupoEscala')
    roman_values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}

    for grupo in NGrupoEscala.objects.all():
        result = 0
        prev_value = 0
        valido = True
        for char in reversed(grupo.nivel.upper()):
            if char not in roman_values:
                result = 999
                valido = False
                break
            current_value = roman_values[char]
            if current_value >= prev_value:
                result += current_value
            else:
                result -= current_value
            prev_value = current_value
        grupo.valor_numerico_db = result if valido else 999
        grupo.save(update_fields=['valor_numerico_db'])


def revertir(apps, schema_editor):
    # Nada que revertir: el campo se elimina con la migración de esquema.
    pass


class Migration(migrations.Migration):
    dependencies = [
         ('nomencladores', '0010_ngrupoescala_valor_numerico_db'),  # ← Django lo rellena solo al crear con --empty
    ]
    operations = [
        migrations.RunPython(poblar_valor_numerico, revertir),
    ]