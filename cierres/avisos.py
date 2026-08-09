"""Notificaciones del ciclo de cierres.

Sigue el patrón de `notificaciones/avisos.py`: una fila por destinatario,
deduplicada por `(content_type, object_id, destinatario, codigo_regla,
clave_extra)` con `update_or_create()`, y **nunca falla**. Si no hay a quién
avisar se registra un `warning` y se sigue: que una unidad no tenga moderador
asignado no puede impedir que se declare su cierre.

`clave_extra` es siempre el período (`2026-08`), así que el aviso de agosto y el
de septiembre son filas distintas, pero repetir el barrido tres veces el mismo
día no crea tres avisos.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from notificaciones.destinatarios import destinatarios_de_unidad
from notificaciones.models import Notificacion
from subsanacion.constantes import CRITICIDAD_ALTA, CRITICIDAD_MEDIA

from .constantes import (CODIGO_DESACTUALIZADA, CODIGO_ULTIMO_DIA,
                         CODIGO_VENTANA_ABIERTA, DIA_FIN_VENTANA)
from .models import EstadoUnidad

logger = logging.getLogger(__name__)


def _content_type_unidad():
    from strorganizativa.models import UnidadOrganizativa
    return ContentType.objects.get_for_model(UnidadOrganizativa)


def _emitir(*, unidad, codigo, clave_extra, titulo, mensaje, severidad,
            tipo=Notificacion.Tipo.RECORDATORIO, fecha_objetivo=None):
    """Crea o actualiza el aviso para cada destinatario de la unidad.

    Se apunta a la Unidad Organizativa y no al cierre porque el aviso existe
    justamente cuando el cierre todavía NO existe.
    """
    destinatarios = list(destinatarios_de_unidad(unidad))
    if not destinatarios:
        logger.warning(
            'Cierre %s de la unidad %s sin destinatarios a los que avisar '
            '(sin moderador asignado ni administradores activos).',
            clave_extra, unidad)
        return 0

    tipo_ct = _content_type_unidad()
    for destinatario in destinatarios:
        existente = Notificacion.objects.filter(
            content_type=tipo_ct, object_id=str(unidad.pk), destinatario=destinatario,
            codigo_regla=codigo, clave_extra=clave_extra,
        ).first()
        if existente and existente.estado == Notificacion.Estado.DESCARTADA:
            continue

        Notificacion.objects.update_or_create(
            content_type=tipo_ct, object_id=str(unidad.pk), destinatario=destinatario,
            codigo_regla=codigo, clave_extra=clave_extra,
            defaults={
                'titulo': titulo,
                'mensaje': mensaje,
                'tipo': tipo,
                'origen': Notificacion.Origen.SISTEMA,
                'estado': Notificacion.Estado.ACTIVA,
                'severidad': severidad,
                'fecha_resolucion': None,
                'fecha_objetivo': fecha_objetivo,
                'unidad': unidad,
            },
        )
    return len(destinatarios)


def _resolver(unidad, codigo, clave_extra):
    """Marca como resuelto un aviso que ya no aplica. No toca `leido`."""
    Notificacion.objects.filter(
        content_type=_content_type_unidad(),
        object_id=str(unidad.pk),
        codigo_regla=codigo,
        clave_extra=clave_extra,
        estado=Notificacion.Estado.ACTIVA,
    ).update(estado=Notificacion.Estado.RESUELTA, fecha_resolucion=timezone.now())


# --------------------------------------------------------------------------
# Puntos de entrada
# --------------------------------------------------------------------------

def avisar_ventana_abierta(unidad, periodo, hoy):
    """Se abrió la ventana (día 20) y la unidad todavía no ha declarado."""
    dias = DIA_FIN_VENTANA - hoy.day
    plazo = 'Hoy es el último día.' if dias <= 0 else f'Le quedan {dias} día(s).'
    return _emitir(
        unidad=unidad,
        codigo=CODIGO_VENTANA_ABIERTA,
        clave_extra=periodo.clave,
        titulo=f'Declare su plantilla — {periodo.etiqueta}',
        mensaje=(f'La unidad «{unidad.descripcion}» debe declarar que su información '
                 f'está actualizada para el cierre de {periodo.etiqueta}. {plazo}'),
        severidad=CRITICIDAD_MEDIA,
        fecha_objetivo=hoy.replace(day=DIA_FIN_VENTANA),
    )


def avisar_ultimo_dia(unidad, periodo, hoy):
    """Queda un día para que se cierre la ventana."""
    return _emitir(
        unidad=unidad,
        codigo=CODIGO_ULTIMO_DIA,
        clave_extra=periodo.clave,
        titulo=f'Último aviso: cierre de {periodo.etiqueta}',
        mensaje=(f'El plazo para declarar la unidad «{unidad.descripcion}» termina el '
                 f'día {DIA_FIN_VENTANA}. Si no declara, quedará como Desactualizada.'),
        severidad=CRITICIDAD_ALTA,
        fecha_objetivo=hoy.replace(day=DIA_FIN_VENTANA),
    )


def avisar_desactualizada(unidad, periodo, meses_pendientes):
    """La unidad perdió el plazo. Se avisa una vez por período pendiente."""
    if meses_pendientes > 1:
        detalle = f'Arrastra {meses_pendientes} meses sin declarar.'
    else:
        detalle = 'Puede regularizarla cualquier día desde el Gestor de Plantilla.'
    return _emitir(
        unidad=unidad,
        codigo=CODIGO_DESACTUALIZADA,
        clave_extra=periodo.clave,
        titulo=f'Unidad desactualizada — {periodo.etiqueta}',
        mensaje=(f'La unidad «{unidad.descripcion}» no declaró el cierre de '
                 f'{periodo.etiqueta} dentro del plazo establecido. {detalle}'),
        severidad=CRITICIDAD_ALTA,
        tipo=Notificacion.Tipo.ALERTA,
    )


def avisar_declaracion(cierre, estado):
    """Tras declarar: se resuelven los avisos de ese período.

    No emite nada nuevo — la declaración no es un problema del que avisar, es la
    desaparición de uno. Si la unidad todavía arrastra meses, el barrido del día
    siguiente volverá a avisar del que toque.
    """
    unidad = cierre.unidad
    clave = cierre.periodo.clave
    for codigo in (CODIGO_VENTANA_ABIERTA, CODIGO_ULTIMO_DIA, CODIGO_DESACTUALIZADA):
        _resolver(unidad, codigo, clave)

    if estado.estado == EstadoUnidad.ACTUALIZADA:
        logger.info('Unidad %s al día tras declarar %s.', unidad, clave)
