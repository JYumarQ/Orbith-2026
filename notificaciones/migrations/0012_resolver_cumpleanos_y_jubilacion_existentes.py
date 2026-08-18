"""Migración de datos: resuelve las notificaciones `REC-CUMPLE`/`REC-JUBILACION`
`ACTIVA` que ya existían cuando se retiraron esos dos detectores de
`notificaciones/recordatorios.py::DETECTORES` (decisión de RRHH: no eran una de las
categorías que querían conservar — ver auditoría del sistema de avisos).

Sin este paso quedarían huérfanas para siempre: el código que las resolvía
(`_resolver_notificaciones_obsoletas`, comparando contra `claves_vigentes`) ya no las
vuelve a evaluar, porque sus detectores ya no corren. Al marcarlas `RESUELTA` aquí, las
purga automáticamente `notificaciones/limpieza.py::purgar_notificaciones_antiguas()` a
los 60 días, sin necesidad de borrarlas a mano.

No toca `leido` (mismo criterio que `_resolver_notificaciones_obsoletas`) ni ninguna
otra fila — ni siquiera otras `REC-CUMPLE`/`REC-JUBILACION` que ya estuvieran
`RESUELTA` o `DESCARTADA`.
"""

from django.db import migrations
from django.utils import timezone


def resolver(apps, schema_editor):
    Notificacion = apps.get_model('notificaciones', 'Notificacion')

    Notificacion.objects.filter(
        codigo_regla__in=['REC-CUMPLE', 'REC-JUBILACION'],
        estado='ACT',
    ).update(estado='RES', fecha_resolucion=timezone.now())


def sin_operacion(apps, schema_editor):
    # No hay un "deshacer" con sentido: no se puede saber si una fila que hoy está
    # RESUELTA ya lo estaba antes de esta migración o la resolvió ella.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0011_recodificar_eventos_de_contratacion_y_plantilla'),
    ]

    operations = [
        migrations.RunPython(resolver, sin_operacion),
    ]
