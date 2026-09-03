# -*- coding: utf-8 -*-
"""Genera las DOS plantillas .docx de «Contratos Determinados (Motivos)».

    .venv/Scripts/python.exe plantillas_word/generadores/crear_motivos.py

Escribe en `plantillas_word/informes_economia/`:

    motivos_template.docx              desglosado: tipo -> motivo -> unidad
    motivos_consolidado_template.docx  consolidado: tipo -> motivo

La vista (`informes.views.ExportarMotivosWordView`) elige una u otra segun el
conmutador de la pantalla.

POR QUE DOS FICHEROS Y NO UNO CON UN `if`
-----------------------------------------
Se podria envolver cada tabla en un `{%p if %}`, pero entonces el .docx tendria
las dos tablas dentro y quien lo abriera para retocar el diseno tendria que
adivinar cual esta viendo. Con dos ficheros, cada uno es lo que parece.

EL .docx DEL MODO DESGLOSADO ES LA SEGUNDA EXCEPCION
----------------------------------------------------
Los tres niveles —tipo de contrato, motivo y unidad— necesitan tres bucles
encajados, y eso son ocho filas de etiquetas `{%tr ... %}` que PARECEN VACIAS.
Se puede abrir en Word y cambiar fuentes, colores y anchos con normalidad; lo
que no se puede es borrar ni fusionar esas filas: el informe saldria vacio o con
las filas repetidas, y sin ningun mensaje de error. El mapa de filas esta junto
al codigo que las escribe.

La del modo consolidado tiene un nivel menos —la unidad pasa a ser una
columna—, asi que son seis filas de etiquetas en vez de ocho.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Cm  # noqa: E402

from comun import (AZUL, GRIS, INDIGO, NARANJA, PIZARRA, VERDE,  # noqa: E402
                   cabecera_de_tabla, documento_apaisado, escribir,
                   fila_de_control, lista_de_unidades, sombrear, tarjetas,
                   titulo)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO_DESGLOSADO = os.path.join(RAIZ, 'informes_economia',
                                  'motivos_template.docx')
DESTINO_CONSOLIDADO = os.path.join(RAIZ, 'informes_economia',
                                   'motivos_consolidado_template.docx')

TARJETAS = [
    ('Total Determinados', '{{ total_contratos }}', AZUL),
    ('Vigentes', '{{ vencen_vigente }}', VERDE),
    ('Advertencia', '{{ vencen_alerta }}', NARANJA),
    ('Críticos', '{{ vencen_critico }}', INDIGO),
]


def resumen_por_motivo(documento):
    """Tabla de totales por motivo. Va en los dos modos, como en la pantalla."""
    escribir(documento.add_paragraph(), 'Totales por motivo', 12, negrita=True,
             color=AZUL, mayusculas=True)

    tabla = documento.add_table(rows=4, cols=3)
    tabla.style = 'Table Grid'
    cabecera_de_tabla(tabla,
                      [('Motivo', True), ('Contratos', False), ('%', False)],
                      [Cm(14.0), Cm(4.0), Cm(4.0)])
    fila_de_control(tabla, 1, '{%tr for m in lista_motivos %}')
    fila = tabla.rows[2]
    escribir(fila.cells[0].paragraphs[0], '{{ m.nombre }}', 11, color=PIZARRA)
    for i, valor in enumerate(('{{ m.count }}', '{{ m.porc }}%'), start=1):
        parrafo = fila.cells[i].paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        escribir(parrafo, valor, 11, negrita=True, color=PIZARRA)
    fila_de_control(tabla, 3, '{%tr endfor %}')

    documento.add_paragraph()


def escribir_fila(fila, valores, tamano=10):
    """Rellena una fila de datos. `valores` son ternas (texto, izquierda, color)."""
    for i, (valor, a_la_izquierda, color) in enumerate(valores):
        parrafo = fila.cells[i].paragraphs[0]
        parrafo.alignment = (WD_ALIGN_PARAGRAPH.LEFT if a_la_izquierda
                             else WD_ALIGN_PARAGRAPH.CENTER)
        escribir(parrafo, valor, tamano, color=color)


def fila_de_nivel(tabla, indice, texto, tamano, color, fondo, sangria):
    """Cabecera de un nivel: ocupa toda la anchura, como en pantalla y en PDF."""
    fila = tabla.rows[indice]
    celda = fila.cells[0].merge(fila.cells[len(fila.cells) - 1])
    parrafo = celda.paragraphs[0]
    parrafo.paragraph_format.left_indent = Cm(sangria)
    escribir(parrafo, texto, tamano, negrita=True, color=color)
    sombrear(celda, fondo)


def total_final(documento):
    tabla = documento.add_table(rows=1, cols=2)
    tabla.style = 'Table Grid'
    escribir(tabla.cell(0, 0).paragraphs[0], 'Total de contratos determinados',
             12, negrita=True, color=PIZARRA)
    parrafo = tabla.cell(0, 1).paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(parrafo, '{{ total_contratos }}', 12, negrita=True, color=AZUL)
    tabla.cell(0, 0).width = Cm(18.0)
    tabla.cell(0, 1).width = Cm(4.0)
    sombrear(tabla.cell(0, 0), 'F1F5F9')
    sombrear(tabla.cell(0, 1), 'F1F5F9')


# ===========================================================================
# MODO DESGLOSADO: tipo -> motivo -> unidad -> contratos
# ===========================================================================
documento = documento_apaisado()
titulo(documento, 'Contratos Determinados por Motivo')
lista_de_unidades(documento)
tarjetas(documento, TARJETAS)
resumen_por_motivo(documento)

escribir(documento.add_paragraph(), 'Detalle por tipo, motivo y unidad', 12,
         negrita=True, color=AZUL, mayusculas=True)

COLUMNAS_NIVELES = [('Exp.', False), ('Nombre y Apellidos', True),
                    ('Cargo u Ocupación', True), ('Sexo', False),
                    ('Cat.', False), ('G. Escala', False),
                    ('F. Alta', False), ('T. Restante', False)]
ANCHOS_NIVELES = [Cm(2.2), Cm(6.2), Cm(5.8), Cm(1.6), Cm(1.6), Cm(2.2),
                  Cm(2.6), Cm(2.7)]

#   0  cabecera de columnas (se repite en cada pagina)
#   1  for tipo             2  cabecera del tipo
#   3  for motivo           4  cabecera del motivo
#   5  for unidad           6  cabecera de la unidad
#   7  for contrato         8  datos del contrato
#   9  endfor (contratos)
#  10  endfor (unidades)
#  11  endfor (motivos)
#  12  endfor (tipos)
tabla = documento.add_table(rows=13, cols=len(COLUMNAS_NIVELES))
tabla.style = 'Table Grid'
tabla.autofit = False
cabecera_de_tabla(tabla, COLUMNAS_NIVELES, ANCHOS_NIVELES)

fila_de_control(tabla, 1, '{%tr for tipo_nombre, tipo_data in datos_agrupados.items() %}')
fila_de_nivel(tabla, 2, '{{ tipo_nombre }} — total {{ tipo_data.total }}',
              13, PIZARRA, 'E2E8F0', 0)

fila_de_control(tabla, 3, '{%tr for motivo_nombre, motivo_data in tipo_data.motivos.items() %}')
fila_de_nivel(tabla, 4, 'Motivo: {{ motivo_nombre }} — total {{ motivo_data.total }}',
              11, AZUL, 'E0E7FF', 0.4)

fila_de_control(tabla, 5, '{%tr for ueb_nombre, ueb_data in motivo_data.uebs.items() %}')
fila_de_nivel(tabla, 6, '{{ ueb_nombre }} — {{ ueb_data.contratos|length }}',
              10, GRIS, 'F8FAFC', 0.9)

fila_de_control(tabla, 7, '{%tr for c in ueb_data.contratos %}')
escribir_fila(tabla.rows[8], [
    ('{{ c.no_expediente }}', False, PIZARRA),
    ('{{ c.aspirante_nombre }}', True, PIZARRA),
    ('{{ c.ncargo_descripcion }}', True, GRIS),
    ('{{ c.sexo }}', False, GRIS),
    ('{{ c.cat_ocupacional[:1] }}', False, PIZARRA),
    ('{{ c.grupo_escala_nivel }}', False, GRIS),
    # Formateada en la propia plantilla: aqui la fila es el objeto crudo de
    # la fuente, y sin esto la fecha salia en ISO mientras el PDF y la
    # pantalla la mostraban a la cubana.
    ("{{ c.fecha_alta.strftime('%d/%m/%Y') if c.fecha_alta else '-' }}", False, GRIS),
    ('{{ c.dias_restantes }}', False, PIZARRA),
])

for indice in (9, 10, 11, 12):
    fila_de_control(tabla, indice, '{%tr endfor %}')

total_final(documento)
os.makedirs(os.path.dirname(DESTINO_DESGLOSADO), exist_ok=True)
documento.save(DESTINO_DESGLOSADO)
print('desglosado ->', DESTINO_DESGLOSADO, '| filas:', len(tabla.rows))


# ===========================================================================
# MODO CONSOLIDADO: una tabla corrida
# ===========================================================================
documento = documento_apaisado()
titulo(documento, 'Contratos Determinados por Motivo')
lista_de_unidades(documento)
tarjetas(documento, TARJETAS)
resumen_por_motivo(documento)

escribir(documento.add_paragraph(), 'Detalle por tipo y motivo', 12,
         negrita=True, color=AZUL, mayusculas=True)

COLUMNAS_CORRIDO = [('Exp.', False), ('Nombre y Apellidos', True),
                    ('Unidad', True), ('Cargo u Ocupación', True),
                    ('Sexo', False), ('Cat.', False), ('G. Escala', False),
                    ('F. Alta', False), ('T. Restante', False)]
ANCHOS_CORRIDO = [Cm(2.0), Cm(5.0), Cm(3.6), Cm(4.6), Cm(1.5), Cm(1.5),
                  Cm(2.0), Cm(2.4), Cm(2.5)]

#   0  cabecera de columnas (se repite en cada pagina)
#   1  for tipo             2  cabecera del tipo
#   3  for motivo           4  cabecera del motivo
#   5  for contrato         6  datos del contrato
#   7  endfor (contratos)
#   8  endfor (motivos)
#   9  endfor (tipos)
#
# Seis filas de etiquetas en vez de las ocho del modo desglosado: aqui falta el
# nivel de la unidad, que pasa a ser una columna.
tabla = documento.add_table(rows=10, cols=len(COLUMNAS_CORRIDO))
tabla.style = 'Table Grid'
tabla.autofit = False
cabecera_de_tabla(tabla, COLUMNAS_CORRIDO, ANCHOS_CORRIDO)

fila_de_control(tabla, 1, '{%tr for tipo_nombre, tipo_data in datos_agrupados.items() %}')
fila_de_nivel(tabla, 2, '{{ tipo_nombre }} — total {{ tipo_data.total }}',
              13, PIZARRA, 'E2E8F0', 0)

fila_de_control(tabla, 3, '{%tr for motivo_nombre, motivo_data in tipo_data.motivos.items() %}')
fila_de_nivel(tabla, 4, 'Motivo: {{ motivo_nombre }} — total {{ motivo_data.total }}',
              11, AZUL, 'E0E7FF', 0.4)

fila_de_control(tabla, 5, '{%tr for f in motivo_data.contratos %}')
escribir_fila(tabla.rows[6], [
    ('{{ f.contrato.no_expediente }}', False, PIZARRA),
    ('{{ f.contrato.aspirante_nombre }}', True, PIZARRA),
    ('{{ f.unidad }}', True, AZUL),
    ('{{ f.contrato.ncargo_descripcion }}', True, GRIS),
    ('{{ f.contrato.sexo }}', False, GRIS),
    ('{{ f.contrato.cat_ocupacional[:1] }}', False, PIZARRA),
    ('{{ f.contrato.grupo_escala_nivel }}', False, GRIS),
    ("{{ f.contrato.fecha_alta.strftime('%d/%m/%Y') if f.contrato.fecha_alta else '-' }}", False, GRIS),
    ('{{ f.contrato.dias_restantes }}', False, PIZARRA),
])

for indice in (7, 8, 9):
    fila_de_control(tabla, indice, '{%tr endfor %}')

total_final(documento)
documento.save(DESTINO_CONSOLIDADO)
print('consolidado ->', DESTINO_CONSOLIDADO, '| filas:', len(tabla.rows))
