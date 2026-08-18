"""Notificaciones del ciclo de vida de una solicitud.

Sigue el patrón ya establecido en Orbith (ver el `save()` del modelo anterior y
`notificaciones/avisos.py`): una fila de `Notificacion` POR destinatario en vez de una
colectiva, `tipo` explícito, y la GenericForeignKey apuntando al objeto que se quiere
abrir desde la notificación.

Dos decisiones propias de este módulo:

* **La GFK apunta a la Solicitud, no al registro afectado.** La solicitud sobrevive a la
  operación —incluso cuando lo aprobado fue eliminar el registro—, así que el botón
  «Abrir registro» sigue llevando a algo que existe. Apuntar al registro dejaría rotas
  justo las notificaciones de las eliminaciones aprobadas.
* **No se usa `destinatarios_de_unidad()` para avisar de una solicitud nueva.** Esa
  función incluye al moderador de la unidad, que aquí es el propio autor —o peor, otro
  moderador de la misma unidad, que según las reglas del módulo no debe ver esta
  solicitud—. Una solicitud nueva es asunto de los administradores y de nadie más.
"""

import logging

from django.contrib.contenttypes.models import ContentType

from notificaciones.avisos import _registrar_notificacion
from notificaciones.models import Notificacion
from solicitudes.models import EstadoSolicitud

logger = logging.getLogger(__name__)

# Identifican la FASE del ciclo de vida que generó el aviso (una Solicitud pasa por
# «nueva» una sola vez, por «decisión» una o más veces si se reabre, y por «reabierta»
# cada vez que se devuelve a espera). Ocupan `codigo_regla`, igual que una regla de
# Subsanación o un detector de Recordatorios: es lo que engancha estos avisos a la
# `UniqueConstraint` de `Notificacion.Meta` (que solo protege filas con
# `codigo_regla != ''`) y a la protección de concurrencia de `_registrar_notificacion`.
# Antes estas filas se creaban con `bulk_create()` y `codigo_regla=''` (el valor por
# defecto de un EVENTO), sin ninguna clave natural que las distinguiera de un alta o una
# baja de contrato — así que no podían protegerse sin arriesgar bloquear esos otros
# eventos, que sí deben poder repetirse para el mismo registro a lo largo del tiempo.
CODIGO_NUEVA = 'SOL-NUEVA'
CODIGO_DECISION = 'SOL-DECISION'
CODIGO_REABIERTA = 'SOL-REABIERTA'


def _administradores():
    """Todos los administradores activos.

    Se avisa a todos y no solo a los de una unidad porque un administrador tiene control
    sobre toda la aplicación, y porque las solicitudes de NCargo no tienen unidad de la
    que partir (es un nomenclador global).
    """
    from usuarios.models import CustomUser
    return CustomUser.objects.filter(es_admin=True, is_active=True)


def _crear(solicitud, destinatarios, codigo, titulo, mensaje):
    """Una fila de `Notificacion` por destinatario, para la fase `codigo` del ciclo de
    vida de `solicitud`.

    Reutiliza `notificaciones.avisos._registrar_notificacion` — el MISMO punto de
    escritura, con la MISMA protección de concurrencia, que ya usan Advertencias y
    Recordatorios — en vez de `bulk_create()` sin deduplicar. `object_id` es el pk de
    la propia solicitud (nunca se reutiliza), así que `(solicitud, destinatario, codigo)`
    es una clave natural real: dos avisos «nueva solicitud» para la MISMA solicitud y el
    MISMO destinatario son, por definición, el mismo hecho notificado dos veces — nunca
    un caso legítimo de repetición, a diferencia de un alta/baja de contrato.
    """
    destinatarios = list(destinatarios)
    if not destinatarios:
        # Degradar, nunca fallar: que no haya a quién avisar no puede impedir que la
        # solicitud se cree o se decida. Queda en el log para poder diagnosticarlo.
        logger.warning(
            'Solicitud %s: «%s» sin ningún destinatario que notificar.',
            solicitud.pk, titulo)
        return

    tipo_ct = ContentType.objects.get_for_model(solicitud)
    for destinatario in destinatarios:
        _registrar_notificacion(
            tipo_ct=tipo_ct, object_id=str(solicitud.pk), destinatario=destinatario,
            codigo_regla=codigo, clave_extra='',
            defaults={
                'titulo': titulo,
                'mensaje': mensaje,
                'tipo': Notificacion.Tipo.EVENTO,
                'estado': Notificacion.Estado.ACTIVA,
                'unidad': solicitud.unidad,
            },
        )


def avisar_nueva_solicitud(solicitud):
    """Al enviar: se avisa a los administradores, que son quienes deciden."""
    autor = solicitud.solicitante_nombre or 'Un moderador'
    _crear(
        solicitud,
        _administradores(),
        CODIGO_NUEVA,
        titulo='Nueva Solicitud Pendiente',
        mensaje=f'{autor} solicitó: {solicitud.etiqueta_operacion} — {solicitud.descriptor}.',
    )


def avisar_decision(solicitud):
    """Al aprobar o rechazar: se avisa al Moderador que la envió.

    El texto usa el descriptor congelado, no el registro real, porque tras aprobar una
    eliminación ese registro ya no existe.
    """
    if solicitud.solicitante is None:
        return

    if solicitud.estado == EstadoSolicitud.APROBADA:
        titulo = 'Solicitud aprobada'
        mensaje = f'Se aprobó la solicitud "{solicitud.descriptor}".'
    elif solicitud.estado == EstadoSolicitud.RECHAZADA:
        titulo = 'Solicitud rechazada'
        mensaje = f'Se rechazó la solicitud "{solicitud.descriptor}".'
        if solicitud.motivo_decision:
            mensaje = f'{mensaje} Motivo: {solicitud.motivo_decision}'
    else:
        return

    _crear(solicitud, [solicitud.solicitante], CODIGO_DECISION, titulo=titulo, mensaje=mensaje)


def avisar_devuelta_a_espera(solicitud):
    """Al devolver una rechazada a En Espera: el autor debe saber que se reabrió."""
    if solicitud.solicitante is None:
        return
    _crear(
        solicitud,
        [solicitud.solicitante],
        CODIGO_REABIERTA,
        titulo='Solicitud reabierta',
        mensaje=f'La solicitud "{solicitud.descriptor}" volvió a quedar en espera de revisión.',
    )
