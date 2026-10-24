# -*- coding: utf-8 -*-
"""Genera la plantilla .xlsx del Anexo 17.2.

    .venv/Scripts/python.exe plantillas_excel/generadores/crear_anexo_17_2.py

Escribe `plantillas_excel/informes_rrhh/anexo_17_2_template.xlsx`, que rellena
`informes_anexo.excel.libro17_2`.

DOS HOJAS MOLDE
---------------
  * `Portada`    — la rellena `informes.excel._escribir_portada()`, la misma de
                   los siete informes de RRHH. Aquí solo se reserva la hoja.
  * `Modelo 17.2` — el registro. Se copia una vez por departamento y al final el
                   molde se retira del libro.

LA CABECERA VA A DOS ALTURAS
----------------------------
Es la forma del modelo oficial: «Salario» abarca siete columnas en la fila de
arriba y sus subtítulos van debajo. Encima, una fila con la numeración del 1 al 17
que el organismo usa para referirse a cada columna en sus instrucciones — por eso
se escribe aunque parezca redundante.

LAS DOS FILAS MODELO
--------------------
Debajo de la cabecera hay dos filas que parecen vacías y no lo están: la primera
lleva el formato de la plaza y la segunda el de su tarifa horaria, que va justo
debajo y en gris. La exportación copia esos formatos en cada fila que vuelca. Se
pueden cambiar desde Excel; si se BORRAN, los datos saldrán sin formato.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django  # noqa: E402
django.setup()

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from informes.excel import (CENTRADO, FILA_ALTERNA, FUENTE_CABECERA,  # noqa: E402
                            FUENTE_DATO, FUENTE_ROTULO, FUENTE_TITULO,
                            GRIS, IZQUIERDA, REJILLA, RELLENO_CABECERA,
                            RELLENO_SUBCABECERA)

from informes_anexo.excel.libro import HOJA_PORTADA  # noqa: E402
from informes_anexo.excel.libro17_2 import (ALTO_CABECERA_ALTA,  # noqa: E402
                                           ALTO_CABECERA_BAJA, ANCHOS,
                                           COLUMNAS, ROTULOS_HORIZONTALES,
                                           TAMANO_LETRA,
                                           FILA_CABECERA_ALTA,
                                           FILA_CABECERA_BAJA, FILA_DATOS,
                                           FILA_ENTIDAD, FILA_FECHA,
                                           FILA_MODELO_TARIFA, FILA_NUMEROS,
                                           FILA_TITULO, MOLDE,
                                           NOMBRE_PLANTILLA, PRIMERA_SALARIO,
                                           ROTULOS_COLA, ROTULOS_FIJOS,
                                           ROTULOS_SALARIO, TITULO,
                                           ULTIMA_SALARIO)

DESTINO = os.path.join(RAIZ, 'plantillas_excel', 'informes_rrhh',
                       NOMBRE_PLANTILLA)

#: Columnas cuyo contenido va centrado: cifras, siglas y marcas cortas. Los
#: textos largos —cargo, nombre, formación— se quedan a la izquierda, que es
#: como se lee una lista de personas.
CENTRADAS = {1, 3, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17}


def _a_tamano(fuente):
    """La misma fuente común de los informes, al tamaño de letra del modelo."""
    return Font(name=fuente.name, size=TAMANO_LETRA, bold=fuente.b, italic=fuente.i,
                color=fuente.color)


LETRA_CABECERA = _a_tamano(FUENTE_CABECERA)
LETRA_DATO = _a_tamano(FUENTE_DATO)
LETRA_ROTULO = _a_tamano(FUENTE_ROTULO)
LETRA_TITULO = _a_tamano(FUENTE_TITULO)
#: Cabecera girada 90°, como en el modelo de RRHH (24-10-2026).
GIRADO = Alignment(horizontal='center', vertical='center', wrap_text=True, text_rotation=90)


def rotulo(hoja, fila, columna, texto, combinar_hasta_fila=None,
           combinar_hasta_col=None):
    """Una celda de cabecera, opcionalmente combinada con sus vecinas."""
    celda = hoja.cell(row=fila, column=columna)
    celda.value = texto
    celda.font = LETRA_CABECERA
    celda.fill = RELLENO_CABECERA
    celda.alignment = CENTRADO if texto in ROTULOS_HORIZONTALES else GIRADO
    celda.border = REJILLA

    if combinar_hasta_fila or combinar_hasta_col:
        hoja.merge_cells(start_row=fila, start_column=columna,
                         end_row=combinar_hasta_fila or fila,
                         end_column=combinar_hasta_col or columna)
        # En un rango combinado openpyxl solo pinta la celda superior izquierda:
        # el resto hay que bordearlas a mano o la rejilla se corta.
        for filas in hoja[hoja.cell(row=fila, column=columna).coordinate + ':'
                          + hoja.cell(row=combinar_hasta_fila or fila,
                                      column=combinar_hasta_col or columna).coordinate]:
            for c in filas:
                c.border = REJILLA
                c.fill = RELLENO_CABECERA


libro = Workbook()

portada = libro.active
portada.title = HOJA_PORTADA
portada.sheet_view.showGridLines = False

hoja = libro.create_sheet(title=MOLDE)

# --- Título y líneas de identificación (las rellena la exportación) ---
hoja.merge_cells(start_row=FILA_TITULO, start_column=1,
                 end_row=FILA_TITULO, end_column=COLUMNAS)
celda = hoja.cell(row=FILA_TITULO, column=1)
celda.value = TITULO
celda.font = LETRA_TITULO
celda.alignment = CENTRADO

for fila, desde, hasta in ((FILA_ENTIDAD, 1, 3), (FILA_ENTIDAD, 4, COLUMNAS),
                           (FILA_FECHA, 4, COLUMNAS)):
    hoja.merge_cells(start_row=fila, start_column=desde,
                     end_row=fila, end_column=hasta)
    c = hoja.cell(row=fila, column=desde)
    c.font = LETRA_DATO
    c.alignment = IZQUIERDA

# --- Cabecera a dos alturas ---
for indice, texto in enumerate(ROTULOS_FIJOS, start=1):
    rotulo(hoja, FILA_CABECERA_ALTA, indice, texto,
           combinar_hasta_fila=FILA_CABECERA_BAJA)

rotulo(hoja, FILA_CABECERA_ALTA, PRIMERA_SALARIO, 'Salario',
       combinar_hasta_col=ULTIMA_SALARIO)
for desplazamiento, texto in enumerate(ROTULOS_SALARIO):
    rotulo(hoja, FILA_CABECERA_BAJA, PRIMERA_SALARIO + desplazamiento, texto)

for desplazamiento, texto in enumerate(ROTULOS_COLA):
    rotulo(hoja, FILA_CABECERA_ALTA, ULTIMA_SALARIO + 1 + desplazamiento, texto,
           combinar_hasta_fila=FILA_CABECERA_BAJA)

hoja.row_dimensions[FILA_CABECERA_ALTA].height = ALTO_CABECERA_ALTA
hoja.row_dimensions[FILA_CABECERA_BAJA].height = ALTO_CABECERA_BAJA

# --- La numeración del 1 al 17 que usa el organismo en sus instrucciones ---
for columna in range(1, COLUMNAS + 1):
    celda = hoja.cell(row=FILA_NUMEROS, column=columna)
    celda.value = columna
    celda.font = LETRA_ROTULO
    celda.fill = RELLENO_SUBCABECERA
    celda.alignment = CENTRADO
    celda.border = REJILLA

# --- Las dos filas modelo ---
for columna in range(1, COLUMNAS + 1):
    celda = hoja.cell(row=FILA_DATOS, column=columna)
    celda.font = LETRA_DATO
    celda.fill = PatternFill('solid', fgColor=FILA_ALTERNA)
    celda.border = REJILLA
    celda.alignment = CENTRADO if columna in CENTRADAS else Alignment(
        horizontal='left', vertical='center', wrap_text=True)

    # La tarifa horaria: misma rejilla, en cursiva y gris. Es una continuación
    # de la fila de arriba, no una plaza nueva, y tiene que leerse como tal sin
    # necesidad de explicarlo. Mismo tamaño que el resto, como en el modelo.
    celda = hoja.cell(row=FILA_MODELO_TARIFA, column=columna)
    celda.font = Font(name='Calibri', size=TAMANO_LETRA, italic=True, color=GRIS)
    celda.border = REJILLA
    celda.alignment = CENTRADO
    # Cinco decimales: con cuatro, dos salarios distintos pueden dar la
    # misma tarifa redondeada y el documento parecería mal calculado.
    celda.number_format = '0.00000'

hoja.page_setup.orientation = 'landscape'
hoja.page_setup.fitToWidth = 1
hoja.page_setup.fitToHeight = 0
hoja.sheet_properties.pageSetUpPr.fitToPage = True
hoja.print_title_rows = '%d:%d' % (FILA_CABECERA_ALTA, FILA_NUMEROS)
hoja.freeze_panes = hoja.cell(row=FILA_DATOS, column=1)

for indice, ancho in enumerate(ANCHOS, start=1):
    hoja.column_dimensions[get_column_letter(indice)].width = ancho

libro.save(DESTINO)
print('Plantilla escrita en %s' % DESTINO)
