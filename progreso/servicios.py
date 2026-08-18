import logging

from .models import TareaGuia, TareaGuiaUsuario

logger = logging.getLogger(__name__)


def completar_tarea(usuario, codigo_tarea):
    """Único punto de escritura de la Guía de Orbith. Idempotente: si el
    usuario ya tenía la tarea, no hace nada y devuelve `None`.

    Defensivo a propósito: esta función NUNCA debe poder romper la operación
    de negocio real que la originó (crear un Aspirante, procesar una
    contratación/baja, revisar un hallazgo...). Cualquier error se registra
    en el log y se traga aquí — nunca se propaga al llamador. Esto es
    especialmente importante para los receptores de señal en
    `progreso/receptores.py`, que se conectan a señales de `subsanacion`
    despachadas con `Signal.send()` (no `send_robust()`): una excepción sin
    capturar ahí rompería el flujo real de Subsanación.

    Devuelve la `TareaGuia` si se acaba de completar (para mostrar el toast),
    o `None` si ya estaba completada, la tarea no existe/está inactiva, o
    algo falló.
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return None
    try:
        tarea = TareaGuia.objects.get(codigo=codigo_tarea, activo=True)
    except TareaGuia.DoesNotExist:
        return None
    try:
        _, creada = TareaGuiaUsuario.objects.get_or_create(usuario=usuario, tarea=tarea)
    except Exception:
        logger.exception("No se pudo registrar la tarea de guía '%s' para %s", codigo_tarea, usuario)
        return None
    return tarea if creada else None
