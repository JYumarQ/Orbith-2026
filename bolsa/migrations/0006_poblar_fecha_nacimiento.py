from django.db import migrations
from datetime import date


def poblar_fecha_nacimiento(apps, schema_editor):
    Aspirante = apps.get_model('bolsa', 'Aspirante')

    for aspirante in Aspirante.objects.all():
        ci = (aspirante.doc_identidad or "").strip()
        if len(ci) < 7 or not ci[:7].isdigit():
            continue

        yy, mm, dd = int(ci[0:2]), int(ci[2:4]), int(ci[4:6])
        digito_siglo = int(ci[6])
        century = 1900 if digito_siglo <= 5 else 2000

        try:
            aspirante.fecha_nacimiento = date(century + yy, mm, dd)
            aspirante.save(update_fields=['fecha_nacimiento'])
        except ValueError:
            continue


def revertir(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
    ('bolsa', '0005_aspirante_fecha_nacimiento'),  # ← Depende de la migración de esquema
    ]
    operations = [
        migrations.RunPython(poblar_fecha_nacimiento, revertir),
    ]