# -*- coding: utf-8 -*-
"""Exportación a Excel de los informes de RRHH.

COMO FUNCIONA, Y POR QUE ASI
----------------------------
Igual que con los Word: hay una PLANTILLA `.xlsx` guardada en
`plantillas_excel/informes_rrhh/`, y este módulo se limita a abrirla y escribir
los datos dentro. Todo lo que es aspecto —títulos, cabeceras, anchos de columna,
celdas combinadas, colores— vive en la plantilla, así que se abre en Excel y se
retoca a mano, sin tocar una línea de código.

Excel no tiene nada parecido a los bucles `{%tr for %}` de docxtpl: hay que
escribir fila a fila desde Python. Para que el formato de los datos también sea
editable a mano, cada hoja de la plantilla lleva una FILA MODELO justo debajo de
la cabecera. Este módulo copia su formato a cada fila que escribe. Si mañana
quieres los datos en otra letra, cambias esa fila en Excel y ya.

LAS PLANTILLAS NO SE ESCRIBEN A MANO DESDE CERO
-----------------------------------------------
Las fabrica `plantillas_excel/generadores/`, que importa las constantes de este
mismo módulo. Generador y exportación comparten la definición de dónde empieza
cada cosa: si estuvieran en dos sitios, bastaría con mover una fila en uno para
que el otro escribiera encima de la cabecera.
"""
import os
from copy import copy

from cierres.constantes import MESES
from django.conf import settings
from django.http import HttpResponse
from nomencladores.models import (COLOR_CAT_DESCONOCIDA, color_de_categoria,
                                  color_de_sexo)
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

CARPETA_PLANTILLAS = ('plantillas_excel', 'informes_rrhh')

TIPO_MIME = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')

# Excel rechaza los nombres de hoja de más de 31 caracteres. El más largo que
# genera este módulo es «Resumen Bajas Septiembre 2026», que son 29.
LARGO_MAXIMO_HOJA = 31


# --------------------------------------------------------------------------
# Paleta
# --------------------------------------------------------------------------
# Los mismos colores que los generadores de Word y que `informes-rrhh.css`, para
# que un informe se reconozca como el mismo en pantalla, en papel y en Excel.

AZUL = '1E3A8A'
PIZARRA = '1E293B'
GRIS = '475569'
NARANJA = 'EA580C'
VERDE = '059669'
SUBCABECERA = 'E2E8F0'
GRUPO = 'EEF2FF'
BORDE = 'CBD5E1'
FILA_ALTERNA = 'F8FAFC'

LINEA = Side(style='thin', color=BORDE)
REJILLA = Border(left=LINEA, right=LINEA, top=LINEA, bottom=LINEA)

FUENTE_TITULO = Font(name='Calibri', size=14, bold=True, color=AZUL)
FUENTE_PORTADA = Font(name='Calibri', size=22, bold=True, color=AZUL)
FUENTE_CABECERA = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
FUENTE_SUBCABECERA = Font(name='Calibri', size=9, bold=True, color=PIZARRA)
FUENTE_DATO = Font(name='Calibri', size=10, color=PIZARRA)
FUENTE_ROTULO = Font(name='Calibri', size=9, bold=True, color=GRIS)
FUENTE_VALOR = Font(name='Calibri', size=12, bold=True, color=PIZARRA)
FUENTE_PIE = Font(name='Calibri', size=8, italic=True, color=GRIS)

RELLENO_CABECERA = PatternFill('solid', fgColor=AZUL)
RELLENO_SUBCABECERA = PatternFill('solid', fgColor=SUBCABECERA)
RELLENO_GRUPO = PatternFill('solid', fgColor=GRUPO)

CENTRADO = Alignment(horizontal='center', vertical='center', wrap_text=True)
IZQUIERDA = Alignment(horizontal='left', vertical='center', wrap_text=True)


def fuente_de_sexo(codigo):
    """El color global del sexo, aplicado a la LETRA.

    Mismo criterio que la categoría ocupacional y por el mismo motivo: en el
    fondo, una celda de color macizo en medio de la fila parte la lectura.
    """
    color = color_de_sexo(codigo)
    return Font(name='Calibri', size=10, bold=True,
                color=color.lstrip('#').upper())


def fuente_de_categoria(codigo):
    """El color global de la categoría ocupacional, aplicado a la LETRA.

    Es el mismo que pinta las insignias de pantalla y las barras de los
    gráficos: sale de `nomencladores.COLORES_CAT_OCUPACIONAL`, que es la fuente
    única. `color_de_categoria` devuelve «#RRGGBB» y openpyxl quiere «RRGGBB».

    Va en la letra y no en el fondo de la celda: una fila con una celda de color
    macizo en medio parte la lectura horizontal, y en una hoja con bandas
    alternas se pelea con ellas. La letra en negrita y de color identifica igual
    la categoría sin romper la fila.
    """
    color = color_de_categoria(codigo) or COLOR_CAT_DESCONOCIDA
    return Font(name='Calibri', size=10, bold=True,
                color=color.lstrip('#').upper())


# --------------------------------------------------------------------------
# Donde empieza cada cosa en la plantilla de Altas y Bajas
# --------------------------------------------------------------------------
# Compartido con el generador. La fila modelo es SIEMPRE la primera de datos.
#
# `col_categoria` es la columna cuya LETRA toma el color de la categoría
# ocupacional; `None` en las hojas que no la tienen.
#
# `centradas` son las columnas cuyo contenido va centrado en horizontal y en
# vertical: cifras, marcas de Si/No, fechas y codigos cortos. Los textos largos
# —nombres, cargos, causas— se quedan a la izquierda, que es como se lee una
# lista de personas.
#
# La columna Provincia NO existe en ninguna hoja: es la misma en todas las filas
# y la portada ya la declara. Repetirla cuarenta veces no anadia nada.

HOJAS = {
    'portada': {'nombre': 'Portada', 'fila_datos': None, 'columnas': 4,
                'col_categoria': None, 'centradas': ()},
    'resumen_altas': {'nombre': 'Resumen Altas', 'fila_datos': 6, 'columnas': 8,
                      'col_categoria': None, 'centradas': (2, 3, 5, 6, 8)},
    'altas': {'nombre': 'Altas', 'fila_datos': 6, 'columnas': 13,
              'col_categoria': 8, 'col_sexo': 6,
              'centradas': (1, 5, 6, 7, 8, 9, 11)},
    'resumen_bajas': {'nombre': 'Resumen Bajas', 'fila_datos': 6, 'columnas': 8,
                      'col_categoria': None, 'centradas': (2, 3, 5, 6, 8)},
    'bajas': {'nombre': 'Bajas', 'fila_datos': 7, 'columnas': 18,
              'col_categoria': 9, 'col_sexo': 7,
              'centradas': (1, 4, 7, 8, 9, 10, 12, 14, 15, 18)},
}

# Fila donde va el título de cada hoja de datos, para escribirle el mes.
FILA_TITULO = 2


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def ruta_de_plantilla(nombre):
    return os.path.join(settings.BASE_DIR, *CARPETA_PLANTILLAS, nombre)


def _formatos_de_la_fila_modelo(hoja, fila, columnas):
    """El formato de la fila modelo, para clonarlo en cada fila de datos.

    Se copia con `copy()` y no se asigna directamente: en openpyxl el `_style`
    de una celda es un objeto compartido, y asignarlo tal cual haría que
    cambiar el formato de una fila cambiara el de todas.
    """
    return [copy(hoja.cell(row=fila, column=col)._style)
            for col in range(1, columnas + 1)]


def escribir_filas(hoja, clave, filas, categorias=None):
    """Vuelca las filas debajo de la cabecera, con el formato de la fila modelo.

    `filas` es una lista de listas: una por fila, con un valor por columna. Un
    `None` deja la celda vacía, que es justo lo que hace falta en las columnas
    Si/No del modelo (se marca una de las dos y la otra se queda en blanco).

    `categorias` es la lista de códigos de categoría ocupacional, uno por fila.
    Cuando se pasa, la celda de esa columna se pinta con el color global de su
    categoría. Devuelve el número de la última fila escrita.
    """
    config = HOJAS[clave]
    primera, columnas = config['fila_datos'], config['columnas']
    formatos = _formatos_de_la_fila_modelo(hoja, primera, columnas)

    for indice, valores in enumerate(filas):
        numero_fila = primera + indice
        for col in range(1, columnas + 1):
            celda = hoja.cell(row=numero_fila, column=col)
            celda._style = copy(formatos[col - 1])
            celda.value = valores[col - 1] if col <= len(valores) else None

        # Bandas alternas: sin ellas, una lista de cuarenta personas y veinte
        # columnas se lee saltando de renglón.
        if indice % 2:
            for col in range(1, columnas + 1):
                hoja.cell(row=numero_fila, column=col).fill = PatternFill(
                    'solid', fgColor=FILA_ALTERNA)

        columna_cat = config['col_categoria']
        if categorias and columna_cat:
            hoja.cell(row=numero_fila, column=columna_cat).font = (
                fuente_de_categoria(categorias[indice]))

        # El sexo, con su color global. Se lee de la propia celda porque el
        # valor que se acaba de escribir ES el código: «F» o «M».
        columna_sexo = config.get('col_sexo')
        if columna_sexo:
            celda_sexo = hoja.cell(row=numero_fila, column=columna_sexo)
            if celda_sexo.value in ('F', 'M'):
                celda_sexo.font = fuente_de_sexo(celda_sexo.value)

    return primera + max(len(filas), 1) - 1


def pie_de_hoja(hoja, clave, ultima_fila, texto):
    """Una línea discreta debajo de los datos que identifica el documento.

    Va escrita en la propia rejilla y no en el pie de impresión de Excel a
    propósito: el pie de impresión solo se ve al imprimir, y una hoja que se
    consulta en pantalla también tiene que poder decir de dónde sale.
    """
    fila = ultima_fila + 2
    columnas = HOJAS[clave]['columnas']
    hoja.merge_cells(start_row=fila, start_column=1,
                     end_row=fila, end_column=columnas)
    celda = hoja.cell(row=fila, column=1)
    celda.value = texto
    celda.font = FUENTE_PIE
    celda.alignment = IZQUIERDA


def respuesta(libro, nombre_fichero):
    """El libro, ya como descarga del navegador."""
    salida = HttpResponse(content_type=TIPO_MIME)
    salida['Content-Disposition'] = 'attachment; filename="%s"' % nombre_fichero
    libro.save(salida)
    return salida


# --------------------------------------------------------------------------
# Altas y Bajas del Mes
# --------------------------------------------------------------------------

def _si_no(condicion):
    """Una sola columna que dice «Sí» o «No».

    El modelo oficial trae DOS columnas por dato —una «Si» y otra «No»— y se
    marca con una X la que corresponde. Aquí van fundidas en una: ocupa la mitad
    y se lee de un vistazo, sin tener que mirar en cuál de las dos cayó la X.
    Es la única diferencia deliberada con la plantilla de la UNE, junto con el
    desglose de puestos no clave.
    """
    return 'Sí' if condicion else 'No'


def _fecha(valor):
    return valor.strftime('%d/%m/%Y') if valor else ''


def _filas_de_resumen(resumen, municipio):
    """La hoja de resumen: los totales a la izquierda y los DOS desgloses.

    Los totales se escriben SOLO en la primera fila y luego se combinan
    verticalmente, que es como está el modelo en papel. Sin ningún movimiento se
    escribe una única fila, para que el total del mes no desaparezca.

    Las parejas de cargo y cantidad vienen ya cuadradas de
    `altas_bajas.resumen()`: el desglose de puestos clave y el de no clave casi
    nunca miden lo mismo, y aquí se pintan uno al lado del otro.
    """
    cabeza = [municipio, resumen['total'], resumen['total_claves'],
              resumen['total_no_claves']]
    parejas = resumen['desglose_par']

    if not parejas:
        return [[municipio, resumen['total'], resumen['total_claves'], '',
                 resumen['total_no_claves'], '', '', '']]

    filas = []
    for indice, par in enumerate(parejas):
        filas.append([
            cabeza[0] if indice == 0 else None,
            cabeza[1] if indice == 0 else None,
            cabeza[2] if indice == 0 else None,
            par['cargo_clave'], par['cantidad_clave'],
            cabeza[3] if indice == 0 else None,
            par['cargo_no_clave'], par['cantidad_no_clave'],
        ])
    return filas


# Municipio, Total, Total Puestos Clave y Total Puestos NO Clave: las cuatro
# celdas que valen para todo el informe y se combinan a lo alto. Las de cargo y
# cantidad, no: cambian en cada fila.
COLUMNAS_COMBINADAS = ('A', 'B', 'C', 'F')


def _combinar_totales(hoja, primera, ultima):
    """Une verticalmente las columnas de totales del resumen.

    Solo tiene sentido con más de una fila de desglose; con una sola, combinar
    una celda consigo misma es un error en openpyxl.
    """
    if ultima <= primera:
        return
    for columna in COLUMNAS_COMBINADAS:
        hoja.merge_cells('%s%d:%s%d' % (columna, primera, columna, ultima))


def _filas_de_altas(altas):
    filas = []
    for numero, fila in enumerate(altas, start=1):
        filas.append([
            numero, fila.nombre, fila.cargo, fila.area,
            _si_no(fila.puesto_clave),
            fila.sexo, fila.edad, fila.categoria, fila.nivel_escolar,
            fila.graduado_en, _fecha(fila.fecha),
            fila.unidad, fila.municipio,
        ])
    return filas


def _filas_de_bajas(bajas):
    filas = []
    for numero, fila in enumerate(bajas, start=1):
        filas.append([
            numero, fila.nombre, fila.cargo,
            _si_no(fila.puesto_clave),
            fila.actividad, fila.area,
            fila.sexo, fila.edad, fila.categoria, fila.nivel_escolar,
            fila.graduado_en, _fecha(fila.fecha), fila.causa,
            _si_no(fila.completar_cargo),
            fila.antiguedad, fila.unidad, fila.municipio,
            _si_no(fila.cobro_sistema_pago),
        ])
    return filas


def _nombre_de_hoja(base, periodo):
    """«Resumen Altas Julio 2026», recortado si no cupiera en los 31 de Excel."""
    completo = ('%s %s' % (base, periodo)).strip()
    return completo[:LARGO_MAXIMO_HOJA]


# Alto del logo en la portada, en pixeles. Equivale a los 28 mm de ancho que le
# da el Word, para que los tres documentos se vean del mismo tamano.
ALTO_DEL_LOGO = 110


def _poner_logo(hoja, config, ancla='A1'):
    """El logo de la empresa en la portada, si lo hay y se puede leer.

    Se escala por ALTO conservando la proporcion original. Forzarlo a un cuadrado
    deformaria cualquier logo que no lo fuera, que son casi todos.

    Un fichero de imagen que falte o este corrupto NO puede tumbar la exportacion
    entera: el informe sin logo sigue sirviendo, y el fallo se ve como un hueco.
    """
    if not (config and getattr(config, 'logo', None)):
        return False
    try:
        from openpyxl.drawing.image import Image
        imagen = Image(config.logo.path)
        proporcion = (imagen.width / imagen.height) if imagen.height else 1
        imagen.height = ALTO_DEL_LOGO
        imagen.width = int(ALTO_DEL_LOGO * proporcion)
        hoja.add_image(imagen, ancla)
        return True
    except Exception:
        return False


def _escribir_portada(hoja, context, periodo, titulo='Altas y Bajas del Mes',
                     cifras=None):
    """Quién informa, de dónde, quién exportó y cuándo. Más las cifras del mes.

    Los mismos datos que la cabecera repetida del Word y del PDF, que arma
    `informes.views._cabecera_documento`. Aquí caben enteros —una hoja no tiene
    el límite de ancho de una cabecera impresa—, así que la lista de unidades se
    escribe completa en vez de recortada en «y N más».
    """
    if _poner_logo(hoja, context.get('config')):
        # La fila 1 tiene que medir lo que el logo (px → puntos), o el logo se
        # monta encima del nombre de la empresa y del título. Los Informes RRHH ya
        # la agrandaban en `LibroInforme.portada`; los Anexos no, y ahí se
        # solapaba (24-10-2026). Aquí vale para todos.
        alto = ALTO_DEL_LOGO * 0.75 + 6
        if (hoja.row_dimensions[1].height or 0) < alto:
            hoja.row_dimensions[1].height = alto

    hoja['B2'] = context.get('nombre_empresa') or ''
    hoja['B2'].font = FUENTE_PORTADA
    hoja['B3'] = '%s · %s' % (titulo, periodo)
    hoja['B3'].font = FUENTE_TITULO

    unidades = context.get('cab_unidades') or []
    if not unidades:
        alcance = 'Reporte Estadístico Provincial · todas las unidades'
    elif len(unidades) == 1:
        alcance = 'Reporte de Unidad Empresarial · %s' % unidades[0]
    else:
        alcance = 'Reporte de %d unidades · %s' % (
            len(unidades), ', '.join(unidades))

    datos = [
        ('Provincia', context.get('cab_provincia') or '—'),
        ('Municipio', context.get('municipio_resumen') or '—'),
        ('Alcance', alcance),
        ('Exportado por', context.get('cab_exportado_por') or '—'),
        ('Generado', context.get('fecha_generacion') or '—'),
    ]
    # Cada informe pasa las suyas; «Altas y Bajas» las tiene fijas por historia.
    if cifras is None:
        cifras = [
            ('Altas', context['resumen_altas']['total']),
            ('De ellas en puestos clave',
             context['resumen_altas']['total_claves']),
            ('Bajas', context['resumen_bajas']['total']),
            ('De ellas en puestos clave',
             context['resumen_bajas']['total_claves']),
            ('Saldo del mes', context.get('saldo_texto') or ''),
        ]
    # Las cifras pueden venir como ternas (rótulo, valor, pie) desde el resumen
    # del informe: aquí solo interesan las dos primeras.
    cifras = [(par[0], par[1]) for par in cifras]

    bloques = [(datos, 'Identificación')]
    if cifras:
        bloques.append((cifras, 'Cifras del período'))

    fila = 6
    for bloque, titulo_bloque in bloques:
        hoja.cell(row=fila, column=2).value = titulo_bloque.upper()
        hoja.cell(row=fila, column=2).font = FUENTE_TITULO
        fila += 1
        for rotulo, valor in bloque:
            hoja.cell(row=fila, column=2).value = rotulo
            hoja.cell(row=fila, column=2).font = FUENTE_ROTULO
            hoja.cell(row=fila, column=3).value = valor
            hoja.cell(row=fila, column=3).font = FUENTE_VALOR
            hoja.cell(row=fila, column=3).alignment = IZQUIERDA
            fila += 1
        fila += 1

    for columna, ancho in ((1, 12), (2, 30), (3, 70), (4, 12)):
        hoja.column_dimensions[get_column_letter(columna)].width = ancho


def _texto_del_pie(context):
    partes = [context.get('nombre_empresa'), context.get('cab_provincia'),
              context.get('cab_unidades_resumen')]
    linea = ' · '.join(p for p in partes if p)
    if context.get('cab_exportado_por'):
        linea += ' · Exportado por %s' % context['cab_exportado_por']
    if context.get('fecha_generacion'):
        linea += ' · %s' % context['fecha_generacion']
    return linea


def libro_de_altas_bajas(context):
    """El libro del modelo de la UNE, relleno: portada y las cuatro hojas."""
    libro = load_workbook(ruta_de_plantilla('altas_bajas_template.xlsx'))

    municipio = context.get('municipio_resumen') or ''
    periodo = context.get('periodo_texto') or ''
    empresa = context.get('nombre_empresa') or ''
    pie = _texto_del_pie(context)

    _escribir_portada(libro[HOJAS['portada']['nombre']], context, periodo)

    # --- Resumen de altas ---
    hoja = libro[HOJAS['resumen_altas']['nombre']]
    hoja.cell(row=FILA_TITULO, column=1).value = 'Altas Mes %s' % periodo
    ultima = escribir_filas(hoja, 'resumen_altas', _filas_de_resumen(
        context['resumen_altas'], municipio))
    _combinar_totales(hoja, HOJAS['resumen_altas']['fila_datos'], ultima)
    pie_de_hoja(hoja, 'resumen_altas', ultima, pie)
    hoja.title = _nombre_de_hoja('Resumen Altas', periodo)

    # --- Detalle de altas ---
    hoja = libro[HOJAS['altas']['nombre']]
    hoja.cell(row=FILA_TITULO, column=2).value = 'Altas Mes %s' % periodo
    hoja.cell(row=3, column=2).value = 'Empresa: %s' % empresa
    ultima = escribir_filas(
        hoja, 'altas', _filas_de_altas(context['altas']),
        [f.cat_codigo for f in context['altas']])
    pie_de_hoja(hoja, 'altas', ultima, pie)
    hoja.title = _nombre_de_hoja('Altas', periodo)

    # --- Resumen de bajas ---
    hoja = libro[HOJAS['resumen_bajas']['nombre']]
    hoja.cell(row=FILA_TITULO, column=1).value = 'Bajas Mes %s' % periodo
    ultima = escribir_filas(hoja, 'resumen_bajas', _filas_de_resumen(
        context['resumen_bajas'], municipio))
    _combinar_totales(hoja, HOJAS['resumen_bajas']['fila_datos'], ultima)
    pie_de_hoja(hoja, 'resumen_bajas', ultima, pie)
    hoja.title = _nombre_de_hoja('Resumen Bajas', periodo)

    # --- Detalle de bajas ---
    hoja = libro[HOJAS['bajas']['nombre']]
    hoja.cell(row=FILA_TITULO, column=2).value = 'Bajas Mes %s' % periodo
    hoja.cell(row=4, column=2).value = empresa.upper()
    ultima = escribir_filas(
        hoja, 'bajas', _filas_de_bajas(context['bajas']),
        [f.cat_codigo for f in context['bajas']])
    pie_de_hoja(hoja, 'bajas', ultima, pie)
    hoja.title = _nombre_de_hoja('Bajas', periodo)

    return libro


# ==========================================================================
# Libros generados sin plantilla, para los seis informes de RRHH
# ==========================================================================
# «Altas y Bajas del Mes» parte de una plantilla `.xlsx` porque imita un modelo
# oficial de la UNE que hay que poder retocar a mano. Los otros seis son
# informes propios de Orbith: no hay modelo externo al que ceñirse, así que se
# construyen aquí, con la misma paleta, y no hay seis ficheros de plantilla más
# que mantener sincronizados con el código.
#
# TRES CLASES DE HOJA
# -------------------
#   Portada    quién informa, de dónde, quién exportó y cuándo.
#   Resumen    las mismas tarjetas de cifras que encabezan el informe en
#              pantalla, una por fila.
#   Datos      el contenido. Los informes con niveles llevan DOS: una plana,
#              con el nivel repetido en columnas, autofiltro y paneles
#              inmovilizados —que es lo que Excel sabe hacer y el PDF no—, y
#              otra que imita los niveles de la pantalla.

# Estilos de las filas segun su papel en una hoja por niveles:
# (relleno, color de letra, negrita, tamano).
#
# La familia NO puede llevar el mismo azul que la cabecera de columnas: con los
# dos iguales, su fila se lee como una segunda cabecera y la hoja entera parece
# plana. Va en pizarra, mas oscura, y la unidad en un tinte claro; el dato, sin
# relleno. Tres pesos distintos que se distinguen de un vistazo.
ESTILOS_DE_NIVEL = {
    'familia': (PIZARRA, 'FFFFFF', True, 12),
    'unidad': (GRUPO, AZUL, True, 11),
    'dato': (None, PIZARRA, False, 10),
    'total': (PIZARRA, 'FFFFFF', True, 11),
}



class LibroDeInforme:
    """Un libro de Excel con portada, resumen y hojas de datos."""

    def __init__(self, context, titulo):
        self.libro = Workbook()
        self.libro.remove(self.libro.active)
        self.context = context
        self.titulo = titulo
        self.periodo = context.get('periodo_texto') or self._periodo(context)
        self.pie = _texto_del_pie(context)

    @staticmethod
    def _periodo(context):
        """«Septiembre 2026» a partir del mes y el año que trae cada informe.

        Solo «Altas y Bajas» pone `periodo_texto` en su contexto; los otros seis
        traen `mes_actual` y `anno_actual` sueltos desde antes de que existiera
        aquel. Los nombres de mes salen de `cierres.constantes`, que es de donde
        los toma también el selector de período.
        """
        try:
            mes = int(context.get('mes_actual'))
            anno = int(context.get('anno_actual'))
        except (TypeError, ValueError):
            return ''
        if not 1 <= mes <= 12:
            return ''
        return '%s %d' % (MESES[mes - 1], anno)

    # -- Portada ----------------------------------------------------------
    def portada(self, cifras=()):
        hoja = self.libro.create_sheet('Portada')
        hoja.sheet_view.showGridLines = False
        hoja.row_dimensions[1].height = 88
        _escribir_portada(hoja, self.context, self.periodo,
                          titulo=self.titulo, cifras=cifras)
        return hoja

    # -- Resumen ----------------------------------------------------------
    def resumen(self, cifras):
        """Las tarjetas de cifra del informe, una por fila.

        `cifras` son ternas (rótulo, valor, pie). El pie es la letra pequeña de
        la tarjeta en pantalla —«32 en puestos clave»—; se escribe porque a
        menudo es lo que explica de qué va el número.
        """
        hoja = self.libro.create_sheet('Resumen')
        hoja.sheet_view.showGridLines = False

        hoja['B2'] = self.titulo
        hoja['B2'].font = FUENTE_TITULO
        hoja['B3'] = self.periodo
        hoja['B3'].font = FUENTE_ROTULO

        fila = 5
        for rotulo, valor, pie in cifras:
            hoja.cell(row=fila, column=2).value = rotulo
            hoja.cell(row=fila, column=2).font = FUENTE_ROTULO
            celda = hoja.cell(row=fila, column=3)
            celda.value = valor
            celda.font = Font(name='Calibri', size=18, bold=True, color=AZUL)
            celda.alignment = IZQUIERDA
            if pie:
                hoja.cell(row=fila, column=4).value = pie
                hoja.cell(row=fila, column=4).font = FUENTE_PIE
            fila += 1

        for columna, ancho in ((1, 4), (2, 34), (3, 16), (4, 46)):
            hoja.column_dimensions[get_column_letter(columna)].width = ancho
        self._pie(hoja, fila + 1, 4)
        return hoja

    # -- Datos ------------------------------------------------------------
    def datos(self, nombre, cabeceras, filas, anchos=None, centradas=(),
              col_categoria=None, categorias=None, total=None, filtrable=True):
        """Una tabla plana, con autofiltro y cabecera inmovilizada."""
        hoja = self.libro.create_sheet(nombre[:LARGO_MAXIMO_HOJA])
        self._titulo(hoja, len(cabeceras))
        self._cabecera(hoja, 4, cabeceras, anchos)

        for indice, valores in enumerate(filas):
            self._fila(hoja, 5 + indice, valores, centradas,
                       alterna=bool(indice % 2),
                       categoria=(categorias[indice] if categorias else None),
                       col_categoria=col_categoria)

        ultima = 4 + max(len(filas), 1)
        if total:
            ultima += 1
            self._fila(hoja, ultima, total, centradas, estilo='total')

        if filtrable and filas:
            hoja.auto_filter.ref = 'A4:%s%d' % (
                get_column_letter(len(cabeceras)), 4 + len(filas))
        hoja.freeze_panes = hoja.cell(row=5, column=1)
        self._pie(hoja, ultima + 2, len(cabeceras))
        self._apaisada(hoja)
        return hoja

    def por_niveles(self, nombre, cabeceras, filas, anchos=None, centradas=()):
        """La misma tabla, pero con los niveles del informe en pantalla.

        `filas` son ternas (papel, profundidad, valores). El papel decide el
        ASPECTO —'familia', 'unidad', 'dato' o 'total'— y la profundidad decide
        el NIVEL. Van separados porque no siempre coinciden: una subunidad se
        pinta igual que su unidad padre pero cuelga un nivel por debajo, y en
        modo consolidado los datos suben un nivel porque no hay unidades.

        Los niveles no son solo un color: cada fila lleva su PROFUNDIDAD en el
        esquema de Excel, así que la hoja sale con los controles «+» y «−» al
        margen y se pliega y despliega como el informe en pantalla. Es lo que
        convierte una lista de filas de colores en una jerarquía de verdad.

        `summaryBelow = False` porque nuestras filas de cabecera van ARRIBA de lo
        que resumen; con el ajuste por defecto, Excel busca el resumen debajo y
        los grupos salen corridos una fila.

        Sin autofiltro a propósito: filtrar una tabla con filas de cabecera
        intercaladas la deja sin sentido, y para eso está la hoja plana.
        """
        hoja = self.libro.create_sheet(nombre[:LARGO_MAXIMO_HOJA])
        self._titulo(hoja, len(cabeceras))
        self._cabecera(hoja, 4, cabeceras, anchos)
        hoja.sheet_properties.outlinePr.summaryBelow = False

        for indice, (papel, profundidad, valores) in enumerate(filas):
            numero = 5 + indice
            self._fila(hoja, numero, valores, centradas, estilo=papel,
                       sangria=profundidad)
            hoja.row_dimensions[numero].outlineLevel = profundidad

        ultima = 4 + max(len(filas), 1)
        hoja.freeze_panes = hoja.cell(row=5, column=1)
        self._pie(hoja, ultima + 2, len(cabeceras))
        self._apaisada(hoja)
        return hoja

    # -- Piezas comunes ---------------------------------------------------
    def _titulo(self, hoja, columnas):
        hoja.cell(row=2, column=1).value = '%s · %s' % (self.titulo, self.periodo)
        hoja.cell(row=2, column=1).font = FUENTE_TITULO
        if columnas > 1:
            hoja.merge_cells(start_row=2, start_column=1,
                             end_row=2, end_column=columnas)

    def _cabecera(self, hoja, fila, cabeceras, anchos):
        for columna, texto in enumerate(cabeceras, start=1):
            celda = hoja.cell(row=fila, column=columna)
            celda.value = texto
            celda.font = FUENTE_CABECERA
            celda.fill = RELLENO_CABECERA
            celda.alignment = CENTRADO
            celda.border = REJILLA
        hoja.row_dimensions[fila].height = 32
        for columna, ancho in enumerate(anchos or (), start=1):
            hoja.column_dimensions[get_column_letter(columna)].width = ancho

    def _fila(self, hoja, numero, valores, centradas, estilo='dato',
              alterna=False, categoria=None, col_categoria=None, sangria=0):
        relleno, color, negrita, tamano = ESTILOS_DE_NIVEL[estilo]
        for columna, valor in enumerate(valores, start=1):
            celda = hoja.cell(row=numero, column=columna)
            celda.value = valor
            celda.font = Font(name='Calibri', size=tamano, bold=negrita,
                              color=color)
            celda.border = REJILLA
            if columna in centradas:
                celda.alignment = CENTRADO
            elif columna == 1 and sangria:
                # La sangria de Excel, no espacios en blanco delante del texto:
                # los espacios se pierden al ordenar, al copiar y al exportar, y
                # esta se mantiene y se ve como lo que es.
                celda.alignment = Alignment(horizontal='left',
                                            vertical='center',
                                            wrap_text=True, indent=sangria)
            else:
                celda.alignment = IZQUIERDA
            if relleno:
                celda.fill = PatternFill('solid', fgColor=relleno)
            elif alterna:
                celda.fill = PatternFill('solid', fgColor=FILA_ALTERNA)
        if categoria and col_categoria:
            hoja.cell(row=numero, column=col_categoria).font = (
                fuente_de_categoria(categoria))

    def _pie(self, hoja, fila, columnas):
        hoja.merge_cells(start_row=fila, start_column=1,
                         end_row=fila, end_column=max(columnas, 1))
        celda = hoja.cell(row=fila, column=1)
        celda.value = self.pie
        celda.font = FUENTE_PIE
        celda.alignment = IZQUIERDA

    def _apaisada(self, hoja):
        hoja.page_setup.orientation = 'landscape'
        hoja.page_setup.fitToWidth = 1
        hoja.sheet_properties.pageSetUpPr.fitToPage = True
