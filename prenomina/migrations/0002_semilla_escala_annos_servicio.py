"""Siembra la escala de años de servicio con la hoja «Rangos» del Excel de RRHH.

Los 30 tramos vienen del fichero real que usa RRHH hoy. Se cargan como **datos**,
no como constantes en el código, porque la escala cambia con las resoluciones
salariales y el Administrador tiene que poder corregirla sin desplegar.

La migración es idempotente y no pisa nada: si un tramo ya existe se deja como
está. Así, reaplicarla sobre una base donde el Administrador ya ajustó cuantías
no le deshace el trabajo.
"""

from decimal import Decimal

from django.db import migrations

# Años → cuantía, tal como está en la hoja «Rangos». Los cinco primeros suben de
# 200 en 200; a partir del sexto, de 80 en 80.
TRAMOS = [
    (1, '200'), (2, '400'), (3, '600'), (4, '800'), (5, '1000'),
    (6, '1080'), (7, '1160'), (8, '1240'), (9, '1320'), (10, '1400'),
    (11, '1480'), (12, '1560'), (13, '1640'), (14, '1720'), (15, '1800'),
    (16, '1880'), (17, '1960'), (18, '2040'), (19, '2120'), (20, '2200'),
    (21, '2280'), (22, '2360'), (23, '2440'), (24, '2520'), (25, '2600'),
    (26, '2680'), (27, '2760'), (28, '2840'), (29, '2920'), (30, '3000'),
]


def sembrar(apps, schema_editor):
    Escala = apps.get_model('prenomina', 'NEscalaAnnosServicio')
    existentes = set(Escala.objects.values_list('annos', flat=True))
    nuevos = [Escala(annos=annos, cuantia=Decimal(cuantia))
              for annos, cuantia in TRAMOS if annos not in existentes]
    if nuevos:
        Escala.objects.bulk_create(nuevos)


def vaciar(apps, schema_editor):
    """Solo borra los tramos sembrados, por si el Administrador añadió otros."""
    Escala = apps.get_model('prenomina', 'NEscalaAnnosServicio')
    Escala.objects.filter(annos__in=[annos for annos, _ in TRAMOS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('prenomina', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(sembrar, vaciar),
    ]
