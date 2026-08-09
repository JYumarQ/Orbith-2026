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

from notificaciones.models import Notificacion
from solicitudes.models import EstadoSolicitud

logger = logging.getLogger(__name__)


def _administradores():
    """Todos los administradores activos.

    Se avisa a todos y no solo a los de una unidad porque un administrador tiene control
    sobre toda la aplicación, y porque las solicitudes de NCargo no tienen unidad de la
    que partir (es un nomenclador global).
    """
    from usuarios.models import CustomUser
    return CustomUser.objects.filter(es_admin=True, is_active=True)


def _crear(solicitud, destinatarios, titulo, mensaje):
    destinatarios = list(destinatarios)
    if not destinatarios:
        # Degradar, nunca fallar: que no haya a quién avisar no puede impedir que la
        # solicitud se cree o se decida. Queda en el log para poder diagnosticarlo.
        logger.warning(
            'Solicitud %s: «%s» sin ningún destinatario que notificar.',
            solicitud.pk, titulo)
        return

    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=titulo,
            mensaje=mensaje,
            tipo=Notificacion.Tipo.EVENTO,
            content_type=ContentType.objects.get_for_model(solicitud),
            object_id=str(solicitud.pk),
            unidad=solicitud.unidad,
            destinatario=destinatario,
        )
        for destinatario in destinatarios
    ])


def avisar_nueva_solicitud(solicitud):
    """Al enviar: se avisa a los administradores, que son quienes deciden."""
    autor = solicitud.solicitante_nombre or 'Un moderador'
    _crear(
        solicitud,
        _administradores(),
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

    _crear(solicitud, [solicitud.solicitante], titulo=titulo, mensaje=mensaje)


def avisar_devuelta_a_espera(solicitud):
    """Al devolver una rechazada a En Espera: el autor debe saber que se reabrió."""
    if solicitud.solicitante is None:
        return
    _crear(
        solicitud,
        [solicitud.solicitante],
        titulo='Solicitud reabierta',
        mensaje=f'La solicitud "{solicitud.descriptor}" volvió a quedar en espera de revisión.',
    )
