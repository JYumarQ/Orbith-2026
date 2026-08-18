import logging

from .servicios import completar_tarea

logger = logging.getLogger(__name__)


def al_revisar_hallazgo(sender, hallazgo, estado_anterior, estado_nuevo, usuario, nota, automatica, **kwargs):
    """Completa `primera_revision_hallazgo` solo ante una revisión MANUAL
    (`automatica=False`) — un cierre automático del motor de Subsanación al
    guardar un formulario normal no cuenta como "el usuario revisó un
    hallazgo a propósito".

    Todo el cuerpo va envuelto en try/except: `hallazgo_revisado` se despacha
    con `Signal.send()` normal (ver `subsanacion/servicios.py`), no
    `send_robust()`, así que una excepción sin capturar aquí se propagaría
    hacia el emisor y rompería la revisión real del hallazgo.
    """
    try:
        if not automatica and usuario is not None:
            completar_tarea(usuario, 'primera_revision_hallazgo')
    except Exception:
        logger.exception("Error en receptor de progreso para hallazgo_revisado")


def al_finalizar_analisis(sender, ejecucion, **kwargs):
    """Completa `primer_analisis_subsanacion` al terminar un barrido completo.

    Igual que `al_revisar_hallazgo`: `analisis_finalizado` se despacha con
    `Signal.send()` normal, así que esta función nunca debe dejar escapar una
    excepción — rompería la finalización real del análisis.
    """
    try:
        # `lanzada_por` es null para ejecuciones de comando de consola o
        # programadas (`EjecucionAnalisis.origen`); solo cuenta como "el
        # usuario ejecutó un análisis" cuando lo lanzó él mismo desde la interfaz.
        usuario = ejecucion.lanzada_por
        if usuario is not None:
            completar_tarea(usuario, 'primer_analisis_subsanacion')
    except Exception:
        logger.exception("Error en receptor de progreso para analisis_finalizado")
