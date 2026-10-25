"""Revisión por registro: mantiene al día los hallazgos Críticos y Altos de los
contratos, sus fichas y sus cargos sin esperar al análisis completo (decisión de
RRHH del 23-10-2026, Fase 2).

Se llama al guardar un contrato, una ficha o un cargo, y tras cada cambio externo
(solo con los contratos afectados). Usa las MISMAS reglas del barrido, limitadas a
esos registros (`reglas.base.solo_registros`), y escribe en los mismos hallazgos de
Subsanación (`servicios.reconciliar_regla(..., ids=...)`): Subsanación, la campana y
los triángulos rojos y ámbar dicen siempre lo mismo, y lo silenciado como
«Ignorado» o «Falso positivo» se respeta.

Su coste depende de cuántos registros se revisan, no del tamaño de la empresa.

Las reglas que cruzan varios registros (trabajador de baja con contrato activo,
varios contratos de alta, sin jornada, aspirante que sigue en la bolsa) no se pueden
decidir mirando una fila: quedan para el análisis completo diario y la búsqueda al
iniciar sesión.
"""

import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_estado = threading.local()


@contextmanager
def sin_revision_por_registro():
    """Desactiva la revisión por registro dentro del bloque: cargas masivas
    (importaciones, migraciones de datos) y pruebas que preparan hallazgos a mano.
    Lo que no se revise aquí lo recoge el análisis diario."""
    anterior = getattr(_estado, 'desactivada', False)
    _estado.desactivada = True
    try:
        yield
    finally:
        _estado.desactivada = anterior

#: Reglas Críticas y Altas que se pueden decidir mirando solo el registro revisado.
REGLAS_POR_REGISTRO = (
    # Contrato
    'CTR-001', 'CTR-002', 'CTR-003', 'CTR-004', 'CTR-010', 'CTR-016', 'CTR-017',
    'CTR-018', 'CTR-020', 'CTR-022', 'CTR-024', 'SAL-001', 'SAL-002',
    # Ficha del trabajador (MOV-015 y MOV-016 miran su histórico: se cierran al guardar el editor)
    'ASP-001', 'ASP-007', 'VIS-001', 'MOV-015', 'MOV-016',
    # Cargo
    'EST-001', 'EST-002', 'EST-008', 'VIS-006',
)

_MODELO = {
    'contratos.calta': 'contratos',
    'bolsa.aspirante': 'aspirantes',
    'strorganizativa.cargoplantilla': 'cargos',
}


def revisar_registros(contratos=(), aspirantes=(), cargos=()):
    """Revisa esos registros con las reglas de `REGLAS_POR_REGISTRO`.

    Nunca lanza: es un aviso, no parte del guardado. Si fallara, el guardado se
    completa igual y el análisis diario lo recoge.
    """
    from .contexto import ContextoAnalisis
    from .reglas import obtener_regla
    from .servicios import reconciliar_regla

    if getattr(_estado, 'desactivada', False):
        return
    ids = {
        'contratos': sorted({str(i) for i in contratos if i}),
        'aspirantes': sorted({str(i) for i in aspirantes if i}),
        'cargos': sorted({str(i) for i in cargos if i}),
    }
    if not any(ids.values()):
        return
    contexto = ContextoAnalisis()
    for codigo in REGLAS_POR_REGISTRO:
        regla = obtener_regla(codigo)
        if regla is None:
            continue
        grupo = _MODELO.get(regla.modelo.lower())
        if not grupo or not ids[grupo]:
            continue
        try:
            reconciliar_regla(regla, None, contexto, ids=ids[grupo])
        except Exception:
            logger.exception('No se pudo revisar la regla %s sobre %s.', codigo, ids[grupo])


def revisar_contratos(contratos):
    """Revisa contratos (instancias) junto con su ficha y su cargo."""
    contratos = [c for c in contratos if c is not None and c.pk]
    revisar_registros(
        contratos=[c.pk for c in contratos],
        aspirantes=[c.aspirante_id for c in contratos],
        cargos=[c.cargo_id for c in contratos])
