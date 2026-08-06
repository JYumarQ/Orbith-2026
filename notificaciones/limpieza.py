"""Purga automática de notificaciones antiguas.

Sustituye la filosofía "nunca borrar, conservar historial" de rondas anteriores por
"bandeja siempre enfocada en lo vigente": Advertencias y Recordatorios resueltos se
conservan `dias` días (para que el usuario aún pueda ver "esto se resolvió hace poco")
y después se eliminan físicamente; los EVENTO (Notificaciones normales) no tienen
concepto de resolución, así que se purgan directamente por antigüedad de creación,
leídos o no.

Vive en su propio módulo (no en `avisos.py` ni `escaneo.py`) porque es una
responsabilidad distinta: no detecta ni resuelve nada, solo limpia lo que ya quedó
inactivo.
"""

from datetime import timedelta

from django.utils import timezone

from .models import Notificacion

DIAS_RETENCION_POR_DEFECTO = 60


def purgar_notificaciones_antiguas(dias=DIAS_RETENCION_POR_DEFECTO):
    """Elimina físicamente:

    * Advertencias/Recordatorios (`tipo` ALERTA o RECORDATORIO) cuyo `estado` ya no es
      ACTIVA (RESUELTA o DESCARTADA) y cuya `fecha_resolucion` tiene más de `dias` días.
      Una `ACTIVA`, por vieja que sea, NUNCA se purga: sigue siendo un problema real.
    * Notificaciones tipo EVENTO cuya `fecha_creado` tiene más de `dias` días,
      independientemente de `leido` (un evento nunca "se resuelve", solo envejece).

    Devuelve `{'advertencias_y_recordatorios': N, 'eventos': M}`.
    """
    limite = timezone.now() - timedelta(days=dias)

    inactivas, _ = (Notificacion.objects
                     .filter(tipo__in=[Notificacion.Tipo.ALERTA, Notificacion.Tipo.RECORDATORIO])
                     .exclude(estado=Notificacion.Estado.ACTIVA)
                     .filter(fecha_resolucion__lt=limite)
                     .delete())

    eventos, _ = (Notificacion.objects
                  .filter(tipo=Notificacion.Tipo.EVENTO, fecha_creado__lt=limite)
                  .delete())

    return {'advertencias_y_recordatorios': inactivas, 'eventos': eventos}
