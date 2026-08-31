"""Constantes del módulo Pre-Nómina.

Aquí solo hay constantes *estructurales* (colores del Excel, claves de columna,
límites numéricos). Ningún concepto de negocio: las claves de ausencia y los
pagos son datos de los nomencladores, nunca texto en el código.
"""

from decimal import Decimal

MODULO = 'prenomina'
ETIQUETA_MODULO = 'Pre-Nómina'

# --- Precisión monetaria -----------------------------------------------------
# El redondeo se aplica UNA sola vez, sobre el importe final. Redondear los
# resultados intermedios acumularía error a lo largo de 30 columnas.
CENTAVO = Decimal('0.01')
HORA = Decimal('0.01')

# --- Colores exactos del Excel de RRHH ---------------------------------------
# Tomados con openpyxl del fichero original. La semántica de cada zona está en
# el nombre; no se inventan tonos nuevos.
COLOR_TRABAJADOR = 'FFFF00'   # amarillo  — datos fijos del trabajador
COLOR_AUSENCIA = '92D050'     # verde     — descuentos en horas
COLOR_TRABAJADAS = '0070C0'   # azul      — horas realmente trabajadas
COLOR_PAGO_HORAS = '7030A0'   # púrpura   — pagos asociados por horas
COLOR_PAGO_IMPORTE = 'FF0000' # rojo      — pagos asociados por importe

# --- Claves de la fila máquina del Excel (fila 9, oculta) --------------------
# Identifican cada columna al reimportar. Se emparejan por CÓDIGO y no por
# descripción: las descripciones las edita el Administrador y llevan tildes, así
# que emparejar por texto rompería el import el día que alguien corrija una
# errata.
CLAVE_EXPEDIENTE = 'EXP'
CLAVE_NOMBRE = 'NOM'
CLAVE_CATEGORIA = 'CAT'
CLAVE_SALARIO = 'SAL'
CLAVE_TOTAL_DESCUENTO = 'TOTDESC'
CLAVE_HORAS_TRABAJADAS = 'HTRAB'
CLAVE_DOC_IDENTIDAD = 'CI'

PREFIJO_AUSENCIA = 'AUS'
PREFIJO_HORAS = 'HOR'
PREFIJO_IMPORTE = 'IMP'

# Columnas que siempre existen y no son conceptos configurables.
CLAVES_ESQUELETO = frozenset({
    CLAVE_EXPEDIENTE, CLAVE_NOMBRE, CLAVE_CATEGORIA, CLAVE_SALARIO,
    CLAVE_TOTAL_DESCUENTO, CLAVE_HORAS_TRABAJADAS, CLAVE_DOC_IDENTIDAD,
})

# --- Estructura del libro exportado ------------------------------------------
HOJA_REPORTE = 'Reporte de pago'
HOJA_ESCALA = 'Rangos'
HOJA_METADATOS = '_orbith'
VERSION_FORMATO = 1

FILA_GRUPOS = 7        # cabecera de grupo (merges de color)
FILA_COLUMNAS = 8      # cabecera de columna
FILA_MAQUINA = 9       # claves de columna, oculta
PRIMERA_FILA_DATOS = 10

# --- Límites defensivos ------------------------------------------------------
# Techo de horas por celda, expresado como múltiplo del fondo de tiempo del
# reporte. Atrapa el "184" tecleado en la casilla equivocada sin estorbar a
# nadie: ningún concepto real triplica el fondo del mes.
FACTOR_TECHO_HORAS = 3
TAMANO_MAXIMO_IMPORTACION = 10 * 1024 * 1024  # 10 MB
