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


def al_corregir_hallazgo(sender, hallazgo, estado_anterior, estado_nuevo, usuario, nota, automatica, **kwargs):
    """XP por CORREGIR un hallazgo (18-11-2026): se cierra solo al guardar el
    registro arreglado (revisión por registro), y lo cobra quien lo guardó, si es
    moderador de la unidad del hallazgo. Los que cierra el análisis diario no dan XP:
    no se sabe quién los arregló."""
    try:
        from auditoria.middleware import get_current_user
        from subsanacion.models import Hallazgo
        from subsanacion.por_registro import en_revision_por_registro

        if not (automatica and estado_nuevo == Hallazgo.CORREGIDO and en_revision_por_registro()):
            return
        quien = get_current_user()
        if quien is None or not getattr(quien, 'is_authenticated', False):
            return
        if hallazgo.unidad_organizativa_id and not quien.unidades.filter(pk=hallazgo.unidad_organizativa_id).exists():
            return
        registrar_actividad(quien, Actividad.HALLAZGO_CORREGIDO, detalle=hallazgo)
    except Exception:
        logger.exception("Error en receptor del Ranking al corregir un hallazgo")


def al_finalizar_analisis(sender, ejecucion, **kwargs):
    """XP por lanzar un análisis completo de Subsanación desde la interfaz
    (`lanzada_por` es null en los de consola o programados)."""
    try:
        if ejecucion.lanzada_por is not None:
            registrar_actividad(ejecucion.lanzada_por, Actividad.ANALISIS_SUBSANACION)
    except Exception:
        logger.exception("Error en receptor del Ranking para analisis_finalizado")
