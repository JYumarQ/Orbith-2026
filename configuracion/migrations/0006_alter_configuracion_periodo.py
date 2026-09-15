from django.db import migrations, models


def normalizar_periodo(apps, schema_editor):
    """
    Antes de este cambio, `periodo` admitía cualquier número >= 7. Ahora solo
    puede valer 15 (Quincenal) o 30 (Mensual), así que hay que reencasillar
    cualquier valor intermedio que pudiera existir en la base de datos:

      - menos de 15 días  -> 15 (Quincenal)
      - más de 15 días    -> 30 (Mensual)

    Se respeta la lectura que ya hacía el asistente de exportar contrato
    (`== 15` es Quincenal, el resto Mensual), salvo para valores por debajo de
    15 (7 o 10 días), que antes se reportaban como «Mensual» y ahora pasan a
    «Quincenal», que es lo correcto.
    """
    Configuracion = apps.get_model('configuracion', 'Configuracion')
    Configuracion.objects.filter(periodo__lt=15).update(periodo=15)
    Configuracion.objects.exclude(periodo__in=(15, 30)).update(periodo=30)


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0005_configuracion_modo_mantenimiento'),
    ]

    operations = [
        migrations.RunPython(normalizar_periodo, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='configuracion',
            name='periodo',
            field=models.PositiveIntegerField(
                choices=[(15, 'Quincenal'), (30, 'Mensual')],
                default=15,
                verbose_name='Período de Pago',
            ),
        ),
    ]
