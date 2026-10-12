import logging

from .models import Actividad
from .servicios import registrar_actividad

logger = logging.getLogger(__name__)


def al_revisar_hallazgo(sender, hallazgo, estado_anterior, estado_nuevo, usuario, nota, automatica, **kwargs):
    """XP por revisar un hallazgo a mano (no los cierres automáticos).

    `hallazgo_revisado` se despacha con `Signal.send()` normal: una excepción
    aquí rompería la revisión real, por eso todo va en try/except (igual que
    en `progreso/receptores.py`).
    """
    try:
        if not automatica and usuario is not None:
            registrar_actividad(usuario, Actividad.HALLAZGO_REVISADO, detalle=hallazgo)
    except Exception:
        logger.exception("Error en receptor del Ranking para hallazgo_revisado")


def al_finalizar_analisis(sender, ejecucion, **kwargs):
    """XP por lanzar un análisis completo de Subsanación desde la interfaz
    (`lanzada_por` es null en los de consola o programados)."""
    try:
        if ejecucion.lanzada_por is not None:
            registrar_actividad(ejecucion.lanzada_por, Actividad.ANALISIS_SUBSANACION)
    except Exception:
        logger.exception("Error en receptor del Ranking para analisis_finalizado")
