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

Desde la 3.9.0 se revisan TODAS las reglas Críticas y Altas de los contratos, fichas,
cargos, movimientos y bajas de las personas afectadas. Las de otros modelos
(configuración, unidades, usuarios) quedan para el análisis completo diario.
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

#: De qué modelo es cada grupo de ids. Desde la 3.9.0 (09-11-2026, decisión de RRHH)
#: se revisan TODAS las reglas Críticas y Altas de estos modelos, no una lista fija:
#: antes, al corregir un contrato podía quedar el triángulo por una regla que no se
#: revisaba al guardar (CTR-008, las del histórico y las bajas…).
_MODELO = {
    'contratos.calta': 'contratos',
    'bolsa.aspirante': 'aspirantes',
    'strorganizativa.cargoplantilla': 'cargos',
    'contratos.tmovimiento': 'movimientos',
    'contratos.cbaja': 'bajas',
}


#: Medias que también se revisan al guardar: miran el histórico de la persona y
#: tienen que cerrarse en cuanto se corrige con el editor del histórico.
REGLAS_EXTRA = ('MOV-015', 'MOV-016')


def reglas_por_registro():
    """Reglas Críticas y Altas (más `REGLAS_EXTRA`), activas, cuyo modelo es uno de `_MODELO`."""
    from .constantes import CRITICIDAD_ALTA
    from .reglas import codigos_desactivados, obtener_reglas

    desactivadas = codigos_desactivados()
    return [r for r in obtener_reglas()
            if (r.criticidad <= CRITICIDAD_ALTA or r.codigo in REGLAS_EXTRA) and r.codigo not in desactivadas
            and r.modelo.lower() in _MODELO]


def revisar_registros(contratos=(), aspirantes=(), cargos=()):
    """Revisa esos registros —y los movimientos y bajas de esas personas— con todas
    las reglas Críticas y Altas activas.

    Nunca lanza: es un aviso, no parte del guardado. Si fallara, el guardado se
    completa igual y el análisis diario lo recoge.
    """
    from .contexto import ContextoAnalisis
    from .servicios import reconciliar_regla

    if getattr(_estado, 'desactivada', False):
        return
    ids = {
        'contratos': sorted({str(i) for i in contratos if i}),
        'aspirantes': sorted({str(i) for i in aspirantes if i}),
        'cargos': sorted({str(i) for i in cargos if i}),
        'movimientos': [],
        'bajas': [],
    }
    if not any(ids.values()):
        return
    if ids['aspirantes']:
        from contratos.models import CBaja, TMovimiento
        ids['movimientos'] = [str(i) for i in TMovimiento.objects.filter(
            aspirante_id__in=ids['aspirantes']).values_list('pk', flat=True)]
        ids['bajas'] = [str(i) for i in CBaja.objects.filter(
            aspirante_id__in=ids['aspirantes']).values_list('pk', flat=True)]

    contexto = ContextoAnalisis()
    for regla in reglas_por_registro():
        grupo = _MODELO[regla.modelo.lower()]
        if not ids[grupo]:
            continue
        try:
            reconciliar_regla(regla, None, contexto, ids=ids[grupo])
        except Exception:
            logger.exception('No se pudo revisar la regla %s sobre %s.', regla.codigo, ids[grupo])


def revisar_contratos(contratos):
    """Revisa contratos (instancias) junto con su ficha y su cargo."""
    contratos = [c for c in contratos if c is not None and c.pk]
    revisar_registros(
        contratos=[c.pk for c in contratos],
        aspirantes=[c.aspirante_id for c in contratos],
        cargos=[c.cargo_id for c in contratos])
