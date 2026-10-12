# Escrita a mano el 2026-10-07 (equivale a la que generaría makemigrations).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0006_preferenciasusuario_reporte_aprobado_por_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='preferenciasusuario',
            name='mostrar_distincion',
            field=models.BooleanField(default=True, verbose_name='Mostrar mi distinción del mes'),
        ),
    ]
