# -*- coding: utf-8 -*-
"""Lo que comparten el PDF, el Word y el Excel de Informe Inteligente.

Los tres documentos tienen que verse como los de Informes RRHH: misma cabecera
con logo, mismas tarjetas de cifras, misma paleta. Pero el módulo NO reutiliza
el código de `informes/`, sino que replica aquí su imagen. Es una decisión
tomada a conciencia: mover la maquinaria común a un sitio compartido tocaría los
siete informes que ya funcionan, y el riesgo no compensa. La contrapartida es
que hay dos versiones de la misma imagen; si algún día cambia, cambian las dos.

LA DIFERENCIA DE FONDO CON RRHH
-------------------------------
Los informes de RRHH tienen columnas FIJAS. Aquí las elige el usuario, y eso
cambia dos cosas:

  * El Word no puede salir de una plantilla `.docx`. Las plantillas de docxtpl
    repiten FILAS, no columnas, así que un documento con un número variable de
    columnas hay que construirlo por código.

  * Los anchos no se pueden escribir a mano. Se miden sobre el contenido real
    que se va a imprimir (ver `repartir_anchos`), porque una columna «Cargo»
    puede traer cuarenta caracteres en un informe y ocho en el siguiente.
"""
from datetime import datetime

MESES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
            'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado',
           'Domingo']

# A partir de aquí se pregunta antes de exportar. La plantilla de la empresa
# ronda los 2.000 trabajadores: un listado completo son cientos de páginas.
LIMITE_DE_FILAS = 500

# Ancho útil de una Carta apaisada con los márgenes del documento, en
# caracteres aproximados a 8 pt. Es la unidad en la que se razona el reparto:
# medir en centímetros obligaría a saber la anchura de cada letra.
ANCHO_UTIL_EN_CARACTERES = 165

# Una celda de texto largo puede plegarse hasta en tres renglones antes de dar
# la columna por imposible. Más líneas hacen la fila tan alta que la tabla deja
# de leerse como una tabla.
LINEAS_MAXIMAS_POR_CELDA = 3

# Ningún rótulo de columna baja de esto, aunque su contenido sea de una letra:
# la cabecera también tiene que caber.
ANCHO_MINIMO = 4


def fecha_generacion_es():
    """«Jueves, 03 de Septiembre de 2026 | 04:28 PM», en español.

    `strftime('%A')` devolvería el día en el idioma del servidor, que aquí es
    inglés.
    """
    ahora = datetime.now()
    return '%s, %02d de %s de %d | %s' % (
        DIAS_ES[ahora.weekday()], ahora.day, MESES_ES[ahora.month - 1],
        ahora.year, ahora.strftime('%I:%M %p'))


# --------------------------------------------------------------------------
# Reparto de anchos
# --------------------------------------------------------------------------

def _ancho_natural(columna, filas, indice):
    """Los caracteres que pide una columna si nada se pliega.

    Es el mayor entre su rótulo y el más largo de sus valores. Se mide el
    contenido REAL y no el tipo del campo porque el tipo se equivoca a menudo:
    «No. Expediente» es de tipo texto y mide cinco caracteres, y «País» también
    es texto y mide ocho.
    """
    mayor = len(str(columna.get('label') or ''))
    for fila in filas:
        valor = fila[indice] if indice < len(fila) else ''
        largo = len(str(valor if valor is not None else ''))
        if largo > mayor:
            mayor = largo
    return max(mayor, ANCHO_MINIMO)


def repartir_anchos(columnas, filas, ancho_total=ANCHO_UTIL_EN_CARACTERES):
    """Cuántos caracteres de ancho recibe cada columna, y si el conjunto cabe.

    Devuelve `(pesos, cabe)`. Los pesos son proporciones que suman 1, listas
    para convertirse en porcentajes (PDF) o en centímetros (Word).

    El reparto se hace en dos tiempos, y el segundo es el que importa:

      1. Cada columna pide lo que mide su contenido más largo.
      2. Si entre todas se pasan del papel, se comprimen en proporción. Una
         columna comprimida no pierde texto: lo pliega en varias líneas. Por eso
         el informe se declara imposible solo cuando alguna necesitaría MÁS de
         tres renglones, no en cuanto la suma se pasa.

    Sin ese segundo paso, cinco columnas de texto largo se declararían
    imposibles y doce de fechas y cifras pasarían apuradas: justo al revés de lo
    que se ve en el papel.
    """
    if not columnas:
        return [], True

    naturales = [_ancho_natural(columna, filas, indice)
                 for indice, columna in enumerate(columnas)]
    total = sum(naturales)

    # Lo mínimo que necesita cada columna si se le permite plegar en tres
    # líneas. Es el umbral por debajo del cual ya no cabe de ninguna manera.
    minimos = [max(ANCHO_MINIMO, -(-natural // LINEAS_MAXIMAS_POR_CELDA))
               for natural in naturales]

    cabe = sum(minimos) <= ancho_total
    reparto = naturales if total <= ancho_total else [
        max(minimo, natural * ancho_total // max(total, 1))
        for natural, minimo in zip(naturales, minimos)
    ]

    suma = sum(reparto) or 1
    return [valor / suma for valor in reparto], cabe


def diagnostico(columnas, filas, total_registros):
    """Lo que hay que saber ANTES de exportar: si cabe y si es demasiado largo.

    Lo consulta el navegador para poder preguntar, en vez de descubrirlo cuando
    el fichero ya está descargado y es ilegible.
    """
    _, cabe = repartir_anchos(columnas, filas)
    return {
        'columnas': len(columnas),
        'filas': total_registros,
        'cabe_a_lo_ancho': cabe,
        'excede_filas': total_registros > LIMITE_DE_FILAS,
        'limite_filas': LIMITE_DE_FILAS,
    }


# --------------------------------------------------------------------------
# Los filtros aplicados, en castellano
# --------------------------------------------------------------------------

OPERADORES = {
    'igual': 'es', 'no_igual': 'no es',
    'contiene': 'contiene', 'no_contiene': 'no contiene',
    'empieza': 'empieza por', 'termina': 'termina en',
    'mayor': 'mayor que', 'mayor_igual': 'mayor o igual que',
    'menor': 'menor que', 'menor_igual': 'menor o igual que',
    'entre': 'entre', 'vacio': 'está vacío', 'no_vacio': 'tiene valor',
    'en': 'es alguno de', 'no_en': 'no es ninguno de',
}


def describir_filtros(definicion_modelo, configuracion):
    """Una línea por filtro: «Unidad Organizativa es Nuevitas».

    Un informe a medida sin sus filtros escritos es irrepetible: dos informes
    del mismo mes con condiciones distintas se ven exactamente igual en el
    papel. Por eso van bajo el título y no en una nota al pie.
    """
    lineas = []
    for filtro in (configuracion.get('filtros') or []):
        if not isinstance(filtro, dict):
            continue
        campo = definicion_modelo['campos'].get(filtro.get('campo'))
        if not campo:
            continue

        operador = OPERADORES.get(filtro.get('operador'), filtro.get('operador') or '')
        valor = filtro.get('valor')
        if isinstance(valor, (list, tuple)):
            valor = ', '.join(str(v) for v in valor if v not in (None, ''))
        valor = '' if valor is None else str(valor)

        lineas.append(' '.join(p for p in (campo['label'], operador, valor) if p))
    return lineas
