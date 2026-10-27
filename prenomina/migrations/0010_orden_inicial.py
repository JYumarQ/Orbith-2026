"""Orden inicial de los nomencladores de Pre-Nómina arrastrables (27-10-2026).

A-Z por su descripción, sin distinguir mayúsculas ni acentos. Solo numera la
columna `orden`: los códigos y las plantillas de los reportes no cambian.
"""
import unicodedata

from django.db import migrations


def _clave(texto):
    descompuesto = unicodedata.normalize('NFKD', ' '.join(str(texto or '').split()).lower())
    return ''.join(c for c in descompuesto if not unicodedata.combining(c))


def ordenar(apps, schema_editor):
    for nombre in ('NPagoHoras', 'NPagoImporte', 'NClaveAusencia'):
        Modelo = apps.get_model('prenomina', nombre)
        registros = sorted(Modelo.objects.all(), key=lambda r: (_clave(r.descripcion), r.codigo))
        for posicion, registro in enumerate(registros, start=1):
            if registro.orden != posicion:
                registro.orden = posicion
                registro.save(update_fields=['orden'])


class Migration(migrations.Migration):

    dependencies = [
        ('prenomina', '0009_nomencladores_orden_y_proteccion'),
    ]

    operations = [
        migrations.RunPython(ordenar, migrations.RunPython.noop),
    ]
