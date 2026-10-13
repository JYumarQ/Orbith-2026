"""Correcciones de movimientos de nómina que un Administrador lanza desde Subsanación.

Subsanación nació sin escribir nunca datos de negocio: detecta y explica, y la
corrección la hace el usuario en el formulario. Los movimientos de nómina no tienen
formulario de edición (son el registro de lo que ocurrió), así que dos casos que solo
se podían arreglar desde la consola tienen aquí su arreglo, con un botón «Corregir»
en el hallazgo, solo para Administradores (decisión de RRHH, 12-10-2026):

* MOV-002 — el movimiento perdió el enlace con su contrato vivo → se vuelve a enlazar.
* MOV-008 — el movimiento está enlazado a un contrato con otro número de expediente
  (el expediente se corrigió después) → toma el expediente de su contrato.

El código vive en Contratos y no en Subsanación a propósito: es Contratos quien sabe
qué es un movimiento correcto. Subsanación solo llama a estas funciones.

Cada función comprueba de nuevo el problema antes de tocar nada (desde el análisis
puede haber cambiado) y guarda con `save()`, para que Auditoría registre el antes y
el después con el usuario que pulsó el botón. Devuelven el texto que se anota en el
historial del hallazgo, o lanzan ValueError con el motivo si ya no se puede aplicar.
"""

from .models import TIPO_MOVIMIENTO_BAJA, CAlta, TMovimiento


def _movimiento(movimiento_id):
    movimiento = TMovimiento.objects.select_related('contrato').filter(pk=movimiento_id).first()
    if movimiento is None:
        raise ValueError('El movimiento ya no existe.')
    return movimiento


def reenganchar_movimiento(movimiento_id):
    """MOV-002: enlaza el movimiento al contrato vivo del mismo trabajador con el
    mismo número de expediente, el criterio de `CAlta.movimientos_huerfanos_reenganchables()`."""
    movimiento = _movimiento(movimiento_id)
    if movimiento.contrato_id:
        raise ValueError('El movimiento ya está enlazado a su contrato.')
    if (movimiento.tipo_movimiento or '').strip().lower() == TIPO_MOVIMIENTO_BAJA.lower():
        raise ValueError('Los movimientos de baja van sin contrato a propósito.')
    if not movimiento.aspirante_id or not movimiento.no_expediente:
        raise ValueError(
            'El movimiento no tiene trabajador o expediente: no se puede saber a qué '
            'contrato pertenece.')

    contrato = CAlta.objects.filter(
        aspirante_id=movimiento.aspirante_id, no_expediente=movimiento.no_expediente).first()
    if contrato is None:
        raise ValueError(
            f'El trabajador ya no tiene un contrato vivo con el expediente '
            f'{movimiento.no_expediente}.')

    movimiento.contrato = contrato
    movimiento.save(update_fields=['contrato'])
    return f'Movimiento enlazado al contrato del expediente {contrato.no_expediente}.'


def alinear_expediente_movimiento(movimiento_id):
    """MOV-008: pone al movimiento el número de expediente de su contrato."""
    movimiento = _movimiento(movimiento_id)
    if movimiento.contrato is None:
        raise ValueError('El movimiento no está enlazado a ningún contrato.')

    anterior = movimiento.no_expediente
    nuevo = movimiento.contrato.no_expediente
    if anterior == nuevo:
        raise ValueError('El movimiento ya tiene el expediente de su contrato.')

    movimiento.no_expediente = nuevo
    movimiento.save(update_fields=['no_expediente'])
    return f'Expediente del movimiento corregido: {anterior or "—"} → {nuevo}.'
