"""Cálculo de los valores derivados de un reporte de pago.

La primera mitad del módulo es **pura**: no importa Django ni toca la base de
datos, así que se prueba con `SimpleTestCase`. La segunda mitad son las tres
funciones que leen y escriben, y que solo llama `servicios.py`.

Todo lo derivado se **almacena**, nunca se calcula al leer. La razón decisiva es
el histórico: si los importes se calcularan en cada visita, el día que alguien
corrigiera un modo de redondeo en `formulas.py` **todos los reportes cerrados
cambiarían en silencio**. Almacenarlos convierte el reporte en un documento y a
la fórmula en procedencia, no en dependencia viva.

Las tres identidades que sostiene este módulo
---------------------------------------------
1. `total_horas_descontadas` = Σ horas de las ausencias con `resta_horas_mes`.
2. `horas_trabajadas` = `fondo_tiempo` − `total_horas_descontadas`, nunca negativo.
3. Un concepto por horas **derivado** vale la suma de las ausencias que lo
   alimentan; los demás los teclea el usuario.

Ojo con la 1 y la 3: son **independientes**. Que unas vacaciones se paguen a
través de un concepto por horas no impide que se descuenten del fondo del mes.
La lectura intuitiva («si se paga, no se descuenta») produce doble conteo.
"""

from decimal import ROUND_HALF_UP, Decimal

from . import formulas
from .constantes import CENTAVO
from .models import (NEscalaAnnosServicio, TipoValorImporte, ValorAusencia,
                     ValorHoras, ValorImporte)

CERO = Decimal('0')


# --------------------------------------------------------------------------- #
# Cálculo puro
# --------------------------------------------------------------------------- #

def redondear(valor):
    """Redondeo monetario, aplicado UNA sola vez sobre el importe final.

    `ROUND_HALF_UP` explícito: el modo por defecto de Python es
    `ROUND_HALF_EVEN` (bancario), que no es la convención esperada aquí.
    """
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def horas_descontadas(horas_por_ausencia, conceptos_ausencia):
    """Suma de las horas de las ausencias que restan del fondo del mes.

    `horas_por_ausencia` es `{codigo: Decimal}`; `conceptos_ausencia` la lista de
    `ReporteConceptoAusencia` congelados del reporte.
    """
    total = CERO
    for concepto in conceptos_ausencia:
        if concepto.resta_horas_mes:
            total += horas_por_ausencia.get(concepto.codigo, CERO)
    return total


def horas_trabajadas(fondo_tiempo, descontadas):
    """Fondo del mes menos lo descontado, con suelo en cero.

    El suelo es **defensivo**, no un truncamiento silencioso:
    `servicios.guardar_valores()` rechaza antes la entrada que lo provocaría, con
    un mensaje que dice cuántas horas sobran. Si el suelo llegara a actuar, es
    que algo entró por otro camino.
    """
    resultado = Decimal(fondo_tiempo) - Decimal(descontadas)
    return resultado if resultado > CERO else CERO


def derivar_horas(horas_por_ausencia, conceptos_ausencia):
    """Horas que cada concepto por horas derivado recibe de sus ausencias.

    Devuelve `{codigo_concepto_horas: Decimal}`. Es una **suma**, no un 1:1:
    varias claves de ausencia pueden alimentar el mismo concepto (por ejemplo,
    dos licencias distintas que se paguen ambas por salario promedio).
    """
    derivadas = {}
    for concepto in conceptos_ausencia:
        destino = concepto.relacionado_con_codigo
        if destino is None:
            continue
        derivadas[destino] = (derivadas.get(destino, CERO)
                              + horas_por_ausencia.get(concepto.codigo, CERO))
    return derivadas


def contexto_de(trabajador, horas):
    """Variables disponibles para una fórmula, todas congeladas en la fila.

    Que todas salgan de `ReporteTrabajador` y ninguna de un dato vivo es lo que
    hace que un reporte cerrado se pueda recalcular igual dentro de años.
    """
    return {
        'horas': Decimal(horas or CERO),
        'salario_escala': trabajador.salario_escala or CERO,
        'tarifa_horaria': trabajador.tarifa_horaria or CERO,
        'cnci': trabajador.cnci or CERO,
        'maestria': Decimal(trabajador.maestria or 0),
        'instructor': trabajador.instructor or CERO,
        'anos_servicio': Decimal(trabajador.anos_servicio or 0),
    }


def importe_de(concepto, trabajador, horas):
    """Importe de un concepto para un trabajador. Despacha por tipo de valor.

    Una fórmula que falle en tiempo de ejecución no debe tumbar el guardado de
    toda una fila: se registra como cero. `formulas.validar()` ya rechaza al
    guardar el concepto las fórmulas que fallarían, así que llegar aquí con un
    error significa que hay un fallo del sistema, no del usuario.
    """
    if concepto.tipo_valor == TipoValorImporte.IMPORTE:
        return redondear(concepto.importe_fijo or CERO)

    if concepto.tipo_valor == TipoValorImporte.ESCALA:
        return redondear(NEscalaAnnosServicio.cuantia_de(
            concepto.escala_congelada, trabajador.anos_servicio or 0))

    try:
        bruto = formulas.evaluar(concepto.formula, contexto_de(trabajador, horas))
    except formulas.ErrorDeFormula:
        return CERO
    return redondear(bruto)


# --------------------------------------------------------------------------- #
# Recálculo con ORM
# --------------------------------------------------------------------------- #

def recalcular_trabajador(trabajador, *, conceptos=None):
    """Recalcula toda la fila de un trabajador y la guarda.

    `conceptos` permite pasar los conceptos del reporte ya cargados, para que
    recalcular el reporte entero no los relea una vez por trabajador.

    Coste: dos consultas de lectura, dos `bulk_update` y un `save`. Con ~30
    conceptos por trabajador son milisegundos, que es lo que permite responder a
    cada guardado del modal con solo esa fila.
    """
    reporte = trabajador.reporte
    if conceptos is None:
        conceptos = cargar_conceptos(reporte)
    ausencias, horas, importes = conceptos

    valores_ausencia = list(trabajador.valores_ausencia.all())
    valores_horas = list(trabajador.valores_horas.all())
    valores_importe = list(trabajador.valores_importe.all())

    por_codigo_ausencia = {v.concepto.codigo: v.horas for v in valores_ausencia}

    # 1. Horas derivadas: se sobrescriben siempre, porque su definición ES la
    #    suma de las ausencias que las alimentan.
    derivadas = derivar_horas(por_codigo_ausencia, ausencias)
    a_actualizar = []
    for valor in valores_horas:
        if valor.concepto.es_derivado:
            nuevo = derivadas.get(valor.concepto.codigo, CERO)
            if valor.horas != nuevo:
                valor.horas = nuevo
                a_actualizar.append(valor)
    if a_actualizar:
        ValorHoras.objects.bulk_update(a_actualizar, ['horas'])

    por_codigo_horas = {v.concepto.codigo: v.horas for v in valores_horas}

    # 2. Horas del mes.
    descontadas = horas_descontadas(por_codigo_ausencia, ausencias)
    trabajador.total_horas_descontadas = descontadas
    # Las horas del mes son **de cada trabajador**, no del reporte: salen del
    # Calendario de Pago según la jornada que tuviera asignada al congelarse.
    trabajador.horas_trabajadas = horas_trabajadas(trabajador.horas_mes, descontadas)

    # 3. Importes.
    total_importe = CERO
    a_actualizar = []
    for valor in valores_importe:
        concepto = valor.concepto
        base = (por_codigo_horas.get(concepto.relacionado_con_codigo, CERO)
                if concepto.relacionado_con_codigo is not None else None)
        nuevo = importe_de(concepto, trabajador, base or CERO)
        total_importe += nuevo
        if valor.importe != nuevo or valor.horas_base != base:
            valor.importe = nuevo
            valor.horas_base = base
            a_actualizar.append(valor)
    if a_actualizar:
        ValorImporte.objects.bulk_update(a_actualizar, ['importe', 'horas_base'])

    trabajador.total_importe = redondear(total_importe)
    trabajador.save(update_fields=['total_horas_descontadas', 'horas_trabajadas',
                                   'total_importe'])
    return trabajador


def cargar_conceptos(reporte):
    """Los tres juegos de conceptos congelados del reporte, en una sola pasada."""
    return (list(reporte.conceptos_ausencia.all()),
            list(reporte.conceptos_horas.all()),
            list(reporte.conceptos_importe.all()))


def refrescar_totales(reporte):
    """Totales de la cabecera, con un solo `aggregate`.

    Se recalculan desde cero en vez de acumular con `+=`: dos moderadores
    guardando filas distintas a la vez no pueden perderse una actualización,
    porque ninguno lee-modifica-escribe el mismo número.
    """
    from django.db.models import Count, Sum

    resumen = reporte.trabajadores.aggregate(
        cuenta=Count('id'),
        horas=Sum('horas_trabajadas'),
        importes=Sum('total_importe'))

    reporte.total_trabajadores = resumen['cuenta'] or 0
    reporte.total_horas_trabajadas = resumen['horas'] or CERO
    reporte.total_importes = resumen['importes'] or CERO
    reporte.save(update_fields=['total_trabajadores', 'total_horas_trabajadas',
                                'total_importes'])
    return reporte


def recalcular_reporte(reporte):
    """Recalcula el reporte entero. Es idempotente.

    La llama `cerrar_reporte()` para que cualquier desfase entre lo almacenado y
    lo que toca aflore en el cierre, en vez de quedarse latente.
    """
    conceptos = cargar_conceptos(reporte)
    trabajadores = (reporte.trabajadores
                    .prefetch_related('valores_ausencia__concepto',
                                      'valores_horas__concepto',
                                      'valores_importe__concepto'))
    for trabajador in trabajadores:
        recalcular_trabajador(trabajador, conceptos=conceptos)
    return refrescar_totales(reporte)


def verificar_integridad(reporte):
    """Comprueba, sin escribir nada, que lo almacenado cuadra con las entradas.

    Devuelve una lista de mensajes en español; vacía si todo cuadra. La usan las
    pruebas, y queda disponible como futura regla de Subsanación.
    """
    problemas = []
    ausencias, _, _ = cargar_conceptos(reporte)

    for trabajador in reporte.trabajadores.prefetch_related(
            'valores_ausencia__concepto'):
        por_codigo = {v.concepto.codigo: v.horas
                      for v in trabajador.valores_ausencia.all()}
        esperado = horas_descontadas(por_codigo, ausencias)
        if trabajador.total_horas_descontadas != esperado:
            problemas.append(
                f'{trabajador.no_expediente}: el total descontado almacenado '
                f'({trabajador.total_horas_descontadas}) no coincide con la suma '
                f'de sus ausencias ({esperado}).')

        esperado = horas_trabajadas(reporte.fondo_tiempo,
                                    trabajador.total_horas_descontadas)
        if trabajador.horas_trabajadas != esperado:
            problemas.append(
                f'{trabajador.no_expediente}: las horas trabajadas almacenadas '
                f'({trabajador.horas_trabajadas}) no coinciden con el fondo menos '
                f'lo descontado ({esperado}).')

    return problemas
