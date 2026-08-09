"""Aritmética de períodos y ventanas. Sin base de datos, a propósito.

Todas las reglas de calendario del módulo viven aquí y no dependen de ningún
modelo, así que se pueden probar con fechas inventadas sin tocar PostgreSQL.
`servicios.py` es quien las combina con los datos reales.

Un **período** es un mes concreto: (año, mes). El cierre del mes M se declara
durante la ventana del propio mes M (días 20 a 25). Si se deja pasar, ese
período queda pendiente y se regulariza más tarde — pero sigue llamándose M.
"""

from dataclasses import dataclass
from datetime import date

from .constantes import (COLOR_AZUL, COLOR_NARANJA, COLOR_ROJO, COLOR_VERDE,
                         DIA_FIN_VENTANA, DIA_INICIO_VENTANA, MESES)


@dataclass(frozen=True, order=True)
class Periodo:
    """Un mes concreto. `order=True` permite compararlos y ordenarlos."""

    anno: int
    mes: int

    def __post_init__(self):
        if not 1 <= self.mes <= 12:
            raise ValueError(f'Mes fuera de rango: {self.mes}')

    @property
    def etiqueta(self):
        return f'{MESES[self.mes - 1]} {self.anno}'

    @property
    def clave(self):
        """Identificador estable para URLs y `clave_extra` de notificaciones."""
        return f'{self.anno}-{self.mes:02d}'

    def siguiente(self):
        if self.mes == 12:
            return Periodo(self.anno + 1, 1)
        return Periodo(self.anno, self.mes + 1)

    def anterior(self):
        if self.mes == 1:
            return Periodo(self.anno - 1, 12)
        return Periodo(self.anno, self.mes - 1)

    def __str__(self):
        return self.etiqueta


def periodo_de(fecha):
    """El período al que pertenece una fecha."""
    return Periodo(fecha.year, fecha.month)


def desde_clave(clave):
    """Inverso de `Periodo.clave`. Devuelve None si el texto no es válido.

    No lanza: lo alimentan parámetros de URL, que pueden traer cualquier cosa.
    """
    try:
        anno, mes = str(clave).split('-')
        return Periodo(int(anno), int(mes))
    except (ValueError, AttributeError, TypeError):
        return None


def en_ventana(fecha):
    """¿Esa fecha cae dentro de la ventana ordinaria de declaración (20–25)?"""
    return DIA_INICIO_VENTANA <= fecha.day <= DIA_FIN_VENTANA


def ventana_vencida(fecha):
    """¿Ya pasó la ventana de ese mes? El día 25 todavía es válido."""
    return fecha.day > DIA_FIN_VENTANA


def periodo_objetivo(ultimo_cerrado, hoy=None):
    """El período que a esta unidad le toca cerrar, haya llegado o no su momento.

    `ultimo_cerrado` es el último Periodo que la unidad tiene cerrado, o None si
    nunca declaró. Sin primera declaración no hay historial que regularizar
    (regla 4 del requisito), así que el objetivo es simplemente el mes en curso.
    """
    hoy = hoy or date.today()
    if ultimo_cerrado is None:
        return periodo_de(hoy)
    return ultimo_cerrado.siguiente()


def periodo_declarable(ultimo_cerrado, hoy=None):
    """El período que se cerraría si la unidad declarase AHORA, o None si no puede.

    Tres situaciones:

    * El objetivo está en el futuro → ya cerró el mes en curso, no hay nada que
      declarar hasta que empiece el siguiente ciclo.
    * El objetivo es el mes en curso → solo a partir del día 20. Antes la ventana
      no ha abierto; del 20 al 25 es declaración ordinaria; a partir del 26 la
      unidad ya está desactualizada y regulariza su propio mes.
    * El objetivo es un mes pasado → regularización, permitida cualquier día. Se
      devuelve el **más antiguo** pendiente: la cola es FIFO y no se puede saltar
      un mes declarando el actual (regla 8).
    """
    hoy = hoy or date.today()
    actual = periodo_de(hoy)
    objetivo = periodo_objetivo(ultimo_cerrado, hoy)

    if objetivo > actual:
        return None
    if objetivo < actual:
        return objetivo
    return actual if hoy.day >= DIA_INICIO_VENTANA else None


def fue_en_plazo(periodo, fecha):
    """Solo cuenta como «en plazo» declarar el mes en curso dentro de su ventana.

    Una regularización de agosto hecha en septiembre es válida, pero nunca está
    en plazo: Auditoría necesita poder distinguirlas (regla 7).
    """
    return periodo == periodo_de(fecha) and en_ventana(fecha)


def puede_reabrirse(periodo_cerrado, hoy=None):
    """¿Se puede volver a Pendiente un cierre ya declarado?

    Solo el del mes en curso y solo mientras la ventana siga abierta. Pasado el
    día 25 el cierre es definitivo: cualquier cambio posterior pertenece ya al
    mes siguiente (regla 10), así que reabrir agosto el 27 de agosto falsearía
    la fotografía.
    """
    hoy = hoy or date.today()
    return periodo_cerrado == periodo_de(hoy) and en_ventana(hoy)


def periodos_pendientes(ultimo_cerrado, hoy=None):
    """Todos los períodos que la unidad debe cerrar, del más antiguo al más nuevo.

    Vacía si nunca declaró (no hay obligación) o si está al día. Sirve para
    avisar «arrastra 3 meses» sin que la vista tenga que calcularlo.
    """
    hoy = hoy or date.today()
    if ultimo_cerrado is None:
        return []

    actual = periodo_de(hoy)
    pendientes = []
    periodo = ultimo_cerrado.siguiente()
    while periodo < actual:
        pendientes.append(periodo)
        periodo = periodo.siguiente()

    # El mes en curso solo se considera pendiente una vez abierta su ventana.
    if periodo == actual and hoy.day >= DIA_INICIO_VENTANA:
        pendientes.append(actual)
    return pendientes


def color_por_calendario(ultimo_cerrado, hoy=None):
    """El color del indicador visual, derivado de fechas — nada de base de datos.

    Cuatro colores porque el requisito separa dos situaciones que el estado
    P/A/D no distingue: «ya declaró este mes concreto» (verde) de «está al
    día, pero el mes en curso aún no le toca» (azul). Ambas son, para
    `calcular_estado()`, la misma `ACTUALIZADA` — aquí sí importa la diferencia.

    * Nunca declaró → rojo, sin excepciones ni miradas al calendario.
    * Cerró el mes en curso → verde.
    * Cerró exactamente el mes anterior (nada pendiente todavía, un solo paso
      de distancia) → azul antes del día 20, naranja del 20 al 25, rojo pasado
      el 25 (regla del enunciado: «si llega el día 26 sin hacerlo, pasa a rojo»).
    * Cualquier otra distancia (dos o más meses de atraso) → rojo siempre,
      sea cual sea el día: es la misma unidad que `calcular_estado()` ya
      clasifica como Desactualizada por acumular varios períodos, y esta
      función debe coincidir con ese cálculo, no contradecirlo.
    """
    hoy = hoy or date.today()
    if ultimo_cerrado is None:
        return COLOR_ROJO

    actual = periodo_de(hoy)
    if ultimo_cerrado >= actual:
        # `> actual` no debería ocurrir (nadie declara el futuro), pero ante
        # cualquier inconsistencia de datos es más seguro no pintar de rojo
        # una unidad que en realidad está al día.
        return COLOR_VERDE
    if ultimo_cerrado == actual.anterior():
        if hoy.day < DIA_INICIO_VENTANA:
            return COLOR_AZUL
        if hoy.day <= DIA_FIN_VENTANA:
            return COLOR_NARANJA
        return COLOR_ROJO
    return COLOR_ROJO
