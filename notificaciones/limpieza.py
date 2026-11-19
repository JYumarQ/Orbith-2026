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

Desde el 18-11-2026 se ejecuta sola una vez al día (`limpiar_si_toca`), al primer
acceso: antes solo la lanzaba el comando `escanear_incidencias`, que en el servidor
no está programado, y los avisos se acumulaban (14 000 eventos de más de 60 días).
"""

import logging
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Notificacion

logger = logging.getLogger(__name__)

DIAS_RETENCION_POR_DEFECTO = 60

#: Avisos de solicitud que siguen pendientes de decidir: no se purgan por viejos.
CODIGOS_SOLICITUD_PENDIENTE = ('SOL-NUEVA', 'SOL-PERS-NUEVA')


def purgar_notificaciones_antiguas(dias=DIAS_RETENCION_POR_DEFECTO):
    """Elimina físicamente:

    * Advertencias/Recordatorios (`tipo` ALERTA o RECORDATORIO) cuyo `estado` ya no es
      ACTIVA (RESUELTA o DESCARTADA) y cuya `fecha_resolucion` tiene más de `dias` días.
      Una `ACTIVA`, por vieja que sea, NUNCA se purga: sigue siendo un problema real.
    * Notificaciones tipo EVENTO cuya `fecha_creado` tiene más de `dias` días,
      independientemente de `leido` (un evento nunca "se resuelve", solo envejece),
      salvo las solicitudes que siguen sin decidir.

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
                  .exclude(codigo_regla__in=CODIGOS_SOLICITUD_PENDIENTE,
                           estado=Notificacion.Estado.ACTIVA)
                  .delete())

    return {'advertencias_y_recordatorios': inactivas, 'eventos': eventos}


def borrar_advertencias_informativas():
    """Borra las advertencias de las reglas Informativas. No avisan desde la 3.9.0
    (`avisos._registrar_notificacion_de_hallazgo`), pero las que ya existían no se
    cerraban nunca porque el problema se sigue detectando. Mira las reglas de cada
    momento: una regla que pase a Informativa en una versión futura también se limpia.
    Los problemas siguen viéndose en Subsanación."""
    from subsanacion.constantes import CRITICIDAD_INFORMATIVA
    from subsanacion.reglas import obtener_reglas

    informativas = [r.codigo for r in obtener_reglas(solo_activas=False)
                    if r.criticidad >= CRITICIDAD_INFORMATIVA]
    borradas, _ = Notificacion.objects.filter(
        tipo=Notificacion.Tipo.ALERTA, codigo_regla__in=informativas).delete()
    return borradas


def limpieza_diaria():
    """Todo lo que se limpia una vez al día."""
    resumen = purgar_notificaciones_antiguas()
    resumen['informativas'] = borrar_advertencias_informativas()
    return resumen


def limpiar_si_toca():
    """Lanza `limpieza_diaria` la primera vez de cada día que alguien abre Orbith
    (la llama el contador de la campana). `cache.add` solo escribe si la clave no
    existe, así que el resto de peticiones del día no hacen nada. Con varios procesos
    del servidor puede correr una vez por proceso: no pasa nada, es idempotente.
    Nunca rompe la petición que la dispara."""
    if not cache.add(f'notificaciones-limpieza-{timezone.localdate().isoformat()}', True, 60 * 60 * 26):
        return None
    try:
        # Punto de guardado propio: si algo falla en la base, la petición que la
        # disparó sigue funcionando.
        with transaction.atomic():
            resumen = limpieza_diaria()
    except Exception:                                   # noqa: BLE001
        logger.exception('Falló la limpieza diaria de notificaciones')
        return None
    logger.info('Limpieza diaria de notificaciones: %s', resumen)
    return resumen
