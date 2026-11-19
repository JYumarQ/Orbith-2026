"""Migración de datos: pone en orden los avisos que ya había (decisiones del 18-11-2026).

* Los eventos informativos (altas, bajas, cargos nuevos, cambios salariales…) pasan
  a leídos: desde ahora se ven agrupados en «Actividad de hoy» y no cuentan en la
  campana. No se borra ninguno.
* Se borran las advertencias de las reglas Informativas: desde la 3.9.0 no avisan,
  pero las que ya existían no se cerraban nunca (el problema se sigue detectando).
  Siguen viéndose en Subsanación.
* «Solicitud nueva» de solicitudes que ya se aprobaron o rechazaron: se cierran
  para todos (ya no hay nada que hacer). Los avisos de solicitudes retiradas (que ya
  no existen) se borran.
* Eventos de más de 60 días y avisos resueltos hace más de 60 días: se borran, que
  es la regla de siempre (`notificaciones/limpieza.py`), que en el servidor no se
  estaba aplicando. Se hace aquí para que el primer acceso tras actualizar no lo pague.
"""

from datetime import timedelta

from django.db import migrations
from django.utils import timezone

#: Reglas Informativas a fecha de esta migración. Las que pasen a Informativas más
#: adelante las borra la limpieza diaria, que mira las reglas de cada momento.
INFORMATIVAS = (
    'ASP-005', 'ASP-006', 'ASP-008', 'ASP-009', 'CAL-003', 'CAL-004', 'CTR-012',
    'CTR-015', 'EST-004', 'EST-005', 'EST-006', 'EST-007', 'EXT-001', 'EXT-002',
    'MOV-006', 'USR-002', 'USR-003')


def ordenar(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Notificacion = apps.get_model('notificaciones', 'Notificacion')
    Solicitud = apps.get_model('solicitudes', 'Solicitud')
    SolicitudPersonalizada = apps.get_model('solicitudes', 'SolicitudPersonalizada')
    ahora = timezone.now()

    Notificacion.objects.filter(tipo='EVE', leido=False, codigo_regla__startswith='EVT-').update(leido=True)
    Notificacion.objects.filter(tipo='ALE', codigo_regla__in=INFORMATIVAS).delete()

    for modelo, codigo, pendientes in ((Solicitud, 'SOL-NUEVA', ('E', 'R')),
                                       (SolicitudPersonalizada, 'SOL-PERS-NUEVA', ('ABI',))):
        tipo = ContentType.objects.filter(app_label='solicitudes', model=modelo.__name__.lower()).first()
        if tipo is None:
            continue
        decididas = [str(pk) for pk in modelo.objects.exclude(estado__in=pendientes).values_list('pk', flat=True)]
        Notificacion.objects.filter(
            content_type=tipo, object_id__in=decididas, codigo_regla=codigo, estado='ACT',
        ).update(estado='RES', fecha_resolucion=ahora, leido=True)
        # Las de solicitudes que se retiraron (ya no existen).
        existentes = [str(pk) for pk in modelo.objects.values_list('pk', flat=True)]
        Notificacion.objects.filter(content_type=tipo).exclude(object_id__in=existentes).delete()

    limite = ahora - timedelta(days=60)
    (Notificacion.objects.filter(tipo='EVE', fecha_creado__lt=limite)
     .exclude(codigo_regla__in=('SOL-NUEVA', 'SOL-PERS-NUEVA'), estado='ACT').delete())
    Notificacion.objects.filter(tipo__in=['ALE', 'REC'], fecha_resolucion__lt=limite).exclude(estado='ACT').delete()


def sin_operacion(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notificaciones', '0015_notificacion_autor'),
        ('solicitudes', '0005_solicitud_personalizada'),
    ]

    operations = [migrations.RunPython(ordenar, sin_operacion)]
