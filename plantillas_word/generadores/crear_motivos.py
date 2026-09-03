# -*- coding: utf-8 -*-
"""Genera la plantilla .docx de «Contratos Determinados (Motivos)».

    .venv/Scripts/python.exe plantillas_word/generadores/crear_motivos.py

Escribe `plantillas_word/informes_economia/motivos_template.docx`, que es lo que
rellena `informes.views.ExportarMotivosWordView`.

POR QUE LA TABLA ES PLANA
-------------------------
La pantalla agrupa en tres niveles —tipo de contrato, motivo y unidad— porque
ahi se pliegan y se despliegan. En papel eso serian tres cabeceras por cada
puñado de filas, y en la plantilla seis bucles encajados que nadie podria
retocar despues sin romperlos. Aqui el tipo, el motivo y la unidad son columnas,
y la tabla lleva UNA sola pareja `{%tr for %}` / `{%tr endfor %}`.

EL .docx SE PUEDE EDITAR A MANO
-------------------------------
Es un documento de Word normal. Lo unico intocable son las dos filas con
etiquetas `{%tr ... %}`: parecen vacias y son las que repiten los datos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

from comun import (AZUL, GRIS, INDIGO, NARANJA, PIZARRA, VERDE,  # noqa: E402
                   cabecera_de_tabla, documento_apaisado, escribir,
                   fila_de_control, lista_de_unidades, sombrear, tarjetas,
                   titulo)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, 'informes_economia', 'motivos_template.docx')

ANCHOS = [Cm(2.0), Cm(5.2), Cm(4.4), Cm(4.0), Cm(4.0), Cm(2.2), Cm(1.5), Cm(2.6)]
COLUMNAS = [('Exp.', False), ('Nombre y Apellidos', True), ('Cargo', True),
            ('Unidad', True), ('Motivo', True), ('F. Alta', False),
            ('Días', False), ('Estado', False)]

documento = documento_apaisado()
titulo(documento, 'Contratos Determinados por Motivo')
lista_de_unidades(documento)

tarjetas(documento, [
    ('Total Determinados', '{{ total_contratos }}', AZUL),
    ('Vigentes', '{{ vencen_vigente }}', VERDE),
    ('Advertencia', '{{ vencen_alerta }}', NARANJA),
    ('Críticos', '{{ vencen_critico }}', INDIGO),
])

# --- Resumen por motivo ----------------------------------------------------
# Tabla propia, con su bucle de una sola pareja de etiquetas.
parrafo = documento.add_paragraph()
escribir(parrafo, 'Totales por motivo', 12, negrita=True, color=AZUL,
         mayusculas=True)

resumen = documento.add_table(rows=4, cols=3)
resumen.style = 'Table Grid'
cabecera_de_tabla(resumen, [('Motivo', True), ('Contratos', False), ('%', False)],
                  [Cm(14.0), Cm(4.0), Cm(4.0)])
fila_de_control(resumen, 1, '{%tr for m in lista_motivos %}')
fila = resumen.rows[2]
escribir(fila.cells[0].paragraphs[0], '{{ m.nombre }}', 11, color=PIZARRA)
for i, valor in enumerate(('{{ m.count }}', '{{ m.porc }}%'), start=1):
    parrafo = fila.cells[i].paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(parrafo, valor, 11, negrita=True, color=PIZARRA)
fila_de_control(resumen, 3, '{%tr endfor %}')

documento.add_paragraph()

# --- Detalle ---------------------------------------------------------------
parrafo = documento.add_paragraph()
escribir(parrafo, 'Detalle de contratos', 12, negrita=True, color=AZUL,
         mayusculas=True)

#   0  cabecera de columnas (se repite en cada pagina)
#   1  for fila            2  datos de la fila          3  endfor
tabla = documento.add_table(rows=4, cols=len(COLUMNAS))
tabla.style = 'Table Grid'
tabla.autofit = False
cabecera_de_tabla(tabla, COLUMNAS, ANCHOS)

fila_de_control(tabla, 1, '{%tr for f in filas_documento %}')
fila_datos = tabla.rows[2]
valores = [('{{ f.expediente }}', False, PIZARRA),
           ('{{ f.nombre }}', True, PIZARRA),
           ('{{ f.cargo }}', True, GRIS),
           ('{{ f.unidad }}', True, GRIS),
           ('{{ f.motivo }}', True, GRIS),
           ('{{ f.fecha_alta_texto }}', False, GRIS),
           ('{{ f.dias_restantes }}', False, PIZARRA),
           ('{{ f.estado }}', False, PIZARRA)]
for i, (valor, a_la_izquierda, color) in enumerate(valores):
    parrafo = fila_datos.cells[i].paragraphs[0]
    parrafo.alignment = (WD_ALIGN_PARAGRAPH.LEFT if a_la_izquierda
                         else WD_ALIGN_PARAGRAPH.CENTER)
    run = escribir(parrafo, valor, 10, color=color)
    run.font.size = Pt(10)
fila_de_control(tabla, 3, '{%tr endfor %}')

# --- Total -----------------------------------------------------------------
total = documento.add_table(rows=1, cols=2)
total.style = 'Table Grid'
escribir(total.cell(0, 0).paragraphs[0], 'Total de contratos determinados', 12,
         negrita=True, color=PIZARRA)
parrafo = total.cell(0, 1).paragraphs[0]
parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(parrafo, '{{ total_contratos }}', 12, negrita=True, color=AZUL)
total.cell(0, 0).width = Cm(18.0)
total.cell(0, 1).width = Cm(4.0)
sombrear(total.cell(0, 0), 'F1F5F9')
sombrear(total.cell(0, 1), 'F1F5F9')

os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
documento.save(DESTINO)
print('plantilla escrita en', DESTINO)
print('filas del detalle:', len(tabla.rows))
