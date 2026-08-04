"""Vocabulario del módulo de Subsanación.

Este archivo es la única fuente de verdad sobre categorías, criticidades y estados.
Ni las reglas, ni las vistas, ni las plantillas deben escribir estos literales a mano.
"""

# ---------------------------------------------------------------------------
# CATEGORÍAS (el usuario las ve como "módulos" en los filtros y el dashboard)
# ---------------------------------------------------------------------------
# El orden de esta lista es el orden en que se ejecuta el análisis: cada entrada
# es una petición HTTP independiente encadenada por HTMX. Añadir una categoría
# nueva aquí la incorpora automáticamente a la cadena y al dashboard.

MODULO_CONTRATOS = 'contratos'
MODULO_NOMINA = 'nomina'
MODULO_ASPIRANTES = 'aspirantes'
MODULO_USUARIOS = 'usuarios'
MODULO_ESTRUCTURA = 'estructura'
MODULO_OCULTOS = 'ocultos'
MODULO_CALIDAD = 'calidad'
MODULO_CONFIGURACION = 'configuracion'

MODULOS = [
    (MODULO_CONTRATOS, 'Contratos', 'bi-file-earmark-text-fill'),
    (MODULO_NOMINA, 'Nómina e Históricos', 'bi-arrow-left-right'),
    (MODULO_ASPIRANTES, 'Aspirantes', 'bi-person-badge-fill'),
    (MODULO_USUARIOS, 'Usuarios', 'bi-person-gear'),
    (MODULO_ESTRUCTURA, 'Plantilla y Estructura', 'bi-diagram-3-fill'),
    (MODULO_OCULTOS, 'Ocultos', 'bi-eye-slash-fill'),
    (MODULO_CALIDAD, 'Calidad de datos', 'bi-spellcheck'),
    (MODULO_CONFIGURACION, 'Configuración', 'bi-sliders'),
]

MODULOS_CHOICES = [(clave, etiqueta) for clave, etiqueta, _ in MODULOS]
CLAVES_MODULOS = [clave for clave, _, _ in MODULOS]
ETIQUETA_MODULO = {clave: etiqueta for clave, etiqueta, _ in MODULOS}
ICONO_MODULO = {clave: icono for clave, _, icono in MODULOS}


# ---------------------------------------------------------------------------
# CRITICIDAD
# ---------------------------------------------------------------------------
# Es un ENTERO y no un código de texto a propósito: `ORDER BY criticidad` tiene
# que devolver lo más grave primero. Con códigos de 3 letras el orden alfabético
# daría ALT, BAJ, CRI, INF, MED, que no significa nada.
# Los huecos de 10 permiten intercalar un nivel nuevo en el futuro sin migrar datos.

CRITICIDAD_CRITICA = 10
CRITICIDAD_ALTA = 20
CRITICIDAD_MEDIA = 30
CRITICIDAD_BAJA = 40
CRITICIDAD_INFORMATIVA = 50

CRITICIDADES = [
    (CRITICIDAD_CRITICA, 'Crítica'),
    (CRITICIDAD_ALTA, 'Alta'),
    (CRITICIDAD_MEDIA, 'Media'),
    (CRITICIDAD_BAJA, 'Baja'),
    (CRITICIDAD_INFORMATIVA, 'Informativa'),
]

ETIQUETA_CRITICIDAD = dict(CRITICIDADES)

# Nombre de la clase CSS `sub-color-*` que pinta cada criticidad.
COLOR_POR_CRITICIDAD = {
    CRITICIDAD_CRITICA: 'rojo',
    CRITICIDAD_ALTA: 'naranja',
    CRITICIDAD_MEDIA: 'ambar',
    CRITICIDAD_BAJA: 'azul',
    CRITICIDAD_INFORMATIVA: 'gris',
}

ICONO_POR_CRITICIDAD = {
    CRITICIDAD_CRITICA: 'bi-exclamation-octagon-fill',
    CRITICIDAD_ALTA: 'bi-exclamation-triangle-fill',
    CRITICIDAD_MEDIA: 'bi-exclamation-circle-fill',
    CRITICIDAD_BAJA: 'bi-info-circle-fill',
    CRITICIDAD_INFORMATIVA: 'bi-dash-circle',
}

# Versión de la fórmula del índice de salud. Se guarda en cada ejecución para que una
# gráfica histórica no compare valores calculados con fórmulas distintas.
#
#   1 -> penalización por gravedad dividida entre el número de registros. RETIRADA:
#        como un mismo registro puede generar varios hallazgos, la penalización llegaba
#        a superar el número de registros y el índice quedaba pegado a cero, con lo que
#        dejaba de servir para ver si la base mejoraba o empeoraba.
#   2 -> porcentaje de registros limpios. Ver `servicios.indice_desde_afectados()`.
VERSION_INDICE_SALUD = 2


# ---------------------------------------------------------------------------
# LÍMITES OPERATIVOS
# ---------------------------------------------------------------------------

# Si una regla supera este número de hallazgos se trunca, se anota el aviso y la
# ejecución queda PARCIAL. Protege contra una regla mal escrita que intentara
# insertar cientos de miles de filas. Y tiene sentido de producto: nadie corrige
# a mano 5.000 registros; con ese volumen el problema es de otra naturaleza.
LIMITE_HALLAZGOS_POR_REGLA = 5000

# Tamaño de los lotes de bulk_create / bulk_update y de los .iterator().
TAMANO_LOTE = 500

# Una ejecución que lleve más de este tiempo "En curso" se considera abandonada
# (el usuario cerró el navegador a mitad de la cadena HTMX).
MINUTOS_EJECUCION_ABANDONADA = 15

# A partir de estos días, el dashboard avisa de que los resultados son antiguos.
DIAS_RESULTADO_ANTIGUO = 7

# Mínimo de filas para que el porcentaje de salud de una categoría signifique algo.
#
# El índice es una proporción «penalización sobre número de registros», y con
# denominadores diminutos se vuelve absurdo: la tabla de Configuración tiene UNA fila,
# así que un solo hallazgo de gravedad media la dejaría al 0 %, como si estuviera
# destruida. En esas categorías se muestra el número de hallazgos en lugar de un
# porcentaje engañoso. El índice global no tiene este problema porque suma todas las
# tablas y su denominador siempre es grande.
MINIMO_REGISTROS_PARA_PORCENTAJE = 10


def color_de_indice(indice):
    """Color con el que se pinta un porcentaje de salud (clase `sub-color-*`)."""
    if indice is None:
        return 'gris'
    valor = float(indice)
    if valor >= 95:
        return 'verde'
    if valor >= 85:
        return 'ambar'
    if valor >= 70:
        return 'naranja'
    return 'rojo'
