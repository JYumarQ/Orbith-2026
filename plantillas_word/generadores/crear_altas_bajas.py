# -*- coding: utf-8 -*-
"""Genera la plantilla .docx de «Altas y Bajas del Mes» (modelo de la UNE).

    .venv/Scripts/python.exe plantillas_word/generadores/crear_altas_bajas.py

Escribe `plantillas_word/informes_economia/altas_bajas_template.docx`, que es lo
que rellena `informes.views.ExportarAltasBajasWordView`.

QUE LLEVA Y EN QUE ORDEN
------------------------
Lo mismo que la pantalla y que el libro de Excel: las cifras del mes, el resumen
de altas, el detalle de altas, el resumen de bajas y el detalle de bajas.

Los resúmenes se parten en DOS tablas —los totales por un lado, el desglose por
cargos por el otro— y no en una con celdas combinadas verticalmente como en el
Excel. En Word esa combinación tendría que abarcar un número de filas que solo
se sabe al generar el documento, y no hay forma de decírselo a docxtpl. Dos
tablas dicen lo mismo y se pueden retocar a mano sin romper nada.

EL .docx SE PUEDE EDITAR A MANO
-------------------------------
Cada tabla de datos lleva UNA sola pareja de etiquetas `{%tr for %}` /
`{%tr endfor %}`. Se abre en Word y se retoca —letras, colores, anchos— sin
riesgo. Lo único que no se toca son esas filas, que parecen vacías.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Cm, RGBColor  # noqa: E402

from comun import (AZUL, BLANCO, GRIS, NARANJA, PIZARRA, VERDE,  # noqa: E402
                   cabecera_de_tabla, documento_apaisado, escribir,
                   fila_de_control, lista_de_unidades, sombrear, tarjetas,
                   titulo)

# El sexo lleva su color global —el mismo de la pantalla, el PDF y el Excel—.
# La plantilla no puede elegir color en tiempo de ejecucion, asi que la celda se
# escribe con DOS trozos condicionales: uno rosa que solo sale si es F y otro
# cian que solo sale si es M. Es la unica forma de que un valor variable lleve
# color variable en un .docx generado por plantilla.
ROSA = RGBColor(0xDB, 0x27, 0x77)
CIAN = RGBColor(0x03, 0xC3, 0xEC)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, 'informes_economia', 'altas_bajas_template.docx')


def seccion(documento, texto):
    escribir(documento.add_paragraph(), texto, 13, negrita=True, color=AZUL,
             mayusculas=True)


def tabla_de_totales(documento, resumen, rotulo):
    """Municipio y los tres totales del mes. Sin bucles.

    La Provincia no esta: la cabecera que se repite en cada pagina ya la
    declara, y en la tabla seria la misma celda repetida sin aportar nada.
    """
    columnas = [('Municipio', True), (rotulo, False),
                ('Total Puestos Clave', False),
                ('Total Puestos NO Clave', False)]
    tabla = documento.add_table(rows=2, cols=4)
    tabla.style = 'Table Grid'
    # No ocupa toda la pagina a proposito: son tres cifras y un nombre, y
    # estirarlas a 25 cm dejaba numeros de dos digitos flotando en celdas
    # enormes. Una caja compacta se lee mejor que una tabla vacia.
    cabecera_de_tabla(tabla, columnas,
                      [Cm(6.0), Cm(3.5), Cm(4.5), Cm(5.0)])

    fila = tabla.rows[1]
    escribir(fila.cells[0].paragraphs[0], '{{ municipio_resumen }}', 12,
             negrita=True, color=PIZARRA)
    for indice, (valor, color) in enumerate((
            ('{{ %s.total }}' % resumen, VERDE),
            ('{{ %s.total_claves }}' % resumen, NARANJA),
            ('{{ %s.total_no_claves }}' % resumen, AZUL)), start=1):
        parrafo = fila.cells[indice].paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        escribir(parrafo, valor, 16, negrita=True, color=color)

    documento.add_paragraph()
    return tabla


def tabla_de_desglose(documento, resumen):
    """Los cargos con movimiento: los CLAVE a la izquierda, los NO CLAVE a la derecha.

    Se recorre `desglose_par`, que trae las dos listas ya emparejadas fila a
    fila desde `altas_bajas.resumen()`. Un bucle de docxtpl solo sabe iterar UNA
    coleccion, asi que dos listas de distinta longitud una al lado de otra solo
    se pueden pintar si vienen ya cuadradas de Python.

    `{%p if %}` y no `{%tr if %}`: el aviso de «sin movimiento» es un parrafo
    suelto, no una fila de tabla.
    """
    columnas = [('Cargo Clave', True), ('Cantidad', False),
                ('Cargo NO Clave', True), ('Cantidad', False)]
    #   0  cabecera    1  for    2  datos    3  endfor
    tabla = documento.add_table(rows=4, cols=4)
    tabla.style = 'Table Grid'
    # El ancho se lo lleva el nombre del cargo, que es lo largo; la cantidad es
    # un numero de una o dos cifras y con 2,5 cm le sobra.
    cabecera_de_tabla(tabla, columnas,
                      [Cm(10.0), Cm(2.5), Cm(10.0), Cm(2.5)])

    fila_de_control(tabla, 1, '{%%tr for par in %s.desglose_par %%}' % resumen)
    fila = tabla.rows[2]
    escribir(fila.cells[0].paragraphs[0], '{{ par.cargo_clave }}', 11,
             color=PIZARRA)
    escribir(fila.cells[2].paragraphs[0], '{{ par.cargo_no_clave }}', 11,
             color=PIZARRA)
    for indice, (valor, color) in ((1, ('{{ par.cantidad_clave }}', NARANJA)),
                                   (3, ('{{ par.cantidad_no_clave }}', AZUL))):
        parrafo = fila.cells[indice].paragraphs[0]
        parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        escribir(parrafo, valor, 11, negrita=True, color=color)
    fila_de_control(tabla, 3, '{%tr endfor %}')

    escribir(documento.add_paragraph(),
             '{%%p if not %s.desglose_par %%}' % resumen, 10)
    escribir(documento.add_paragraph(),
             'Sin movimiento este mes.', 10, color=GRIS)
    escribir(documento.add_paragraph(), '{%p endif %}', 10)
    documento.add_paragraph()
    return tabla


def tabla_de_detalle(documento, coleccion, columnas, anchos, celdas):
    """Una tabla de personas. `celdas` son ternas (expresion, izquierda, color)."""
    #   0  cabecera    1  for    2  datos    3  endfor
    tabla = documento.add_table(rows=4, cols=len(columnas))
    tabla.style = 'Table Grid'
    tabla.autofit = False
    cabecera_de_tabla(tabla, columnas, anchos)

    fila_de_control(tabla, 1, '{%%tr for fila in %s %%}' % coleccion)
    fila = tabla.rows[2]
    for indice, (expresion, a_la_izquierda, color) in enumerate(celdas):
        parrafo = fila.cells[indice].paragraphs[0]
        parrafo.alignment = (WD_ALIGN_PARAGRAPH.LEFT if a_la_izquierda
                             else WD_ALIGN_PARAGRAPH.CENTER)
        # Una celda puede llevar VARIOS trozos con colores distintos: es lo que
        # permite que el sexo salga rosa o cian segun su valor. Una plantilla de
        # Word no puede elegir color al rellenarse, asi que se escriben los dos
        # y cada uno se condiciona a su valor; solo uno produce texto.
        if isinstance(expresion, (list, tuple)):
            for trozo, color_trozo in expresion:
                escribir(parrafo, trozo, 9, negrita=True, color=color_trozo)
        else:
            escribir(parrafo, expresion, 9, negrita=not a_la_izquierda,
                     color=color)
    fila_de_control(tabla, 3, '{%tr endfor %}')

    documento.add_paragraph()
    return tabla


documento = documento_apaisado()
titulo(documento, 'Altas y Bajas del Mes')
lista_de_unidades(documento)

escribir(documento.add_paragraph(), 'Período: {{ periodo_texto }}', 12,
         negrita=True, color=GRIS)

tarjetas(documento, [
    ('Altas', '{{ resumen_altas.total }}', VERDE),
    ('Bajas', '{{ resumen_bajas.total }}', NARANJA),
    ('Saldo del mes', '{{ saldo_texto }}', AZUL),
])

# --- Altas -----------------------------------------------------------------
seccion(documento, 'Resumen de Altas')
tabla_de_totales(documento, 'resumen_altas', 'Total Altas')
tabla_de_desglose(documento, 'resumen_altas')

seccion(documento, 'Altas del mes')
# Los anchos suman 24,0 cm y el ancho util de una Carta apaisada con margenes de
# 1,4 cm son 25,1: si la suma se pasa, Word desborda la tabla fuera de la hoja y
# las ultimas columnas se salen del papel. Cualquier cambio aqui tiene que
# respetar ese techo.
tabla_de_detalle(
    documento, 'altas',
    [('No', False), ('Nombre y Apellidos', True), ('Cargo', True),
     ('Área', True), ('Clave', False), ('Sexo', False), ('Edad', False),
     ('Cat. Ocup.', False), ('Nivel', False), ('Graduado en', True),
     ('Fecha', False), ('Dirección / Área o UEB', True),
     ('Municipio', True)],
    [Cm(0.9), Cm(4.2), Cm(3.8), Cm(2.7), Cm(1.0), Cm(0.8), Cm(0.8),
     Cm(1.0), Cm(1.0), Cm(3.1), Cm(1.4), Cm(2.7), Cm(1.6)],
    [('{{ loop.index }}', False, GRIS),
     ('{{ fila.nombre }}', True, PIZARRA),
     ('{{ fila.cargo }}', True, PIZARRA),
     ('{{ fila.area }}', True, GRIS),
     ('{% if fila.puesto_clave %}Sí{% else %}No{% endif %}', False, NARANJA),
     ((("{% if fila.sexo == 'F' %}F{% endif %}", ROSA),
       ("{% if fila.sexo == 'M' %}M{% endif %}", CIAN)), False, PIZARRA),
     ('{{ fila.edad }}', False, PIZARRA),
     ('{{ fila.categoria }}', False, AZUL),
     ('{{ fila.nivel_escolar }}', False, PIZARRA),
     ('{{ fila.graduado_en }}', True, GRIS),
     ('{{ fila.fecha.strftime("%d/%m/%y") }}', False, PIZARRA),
     ('{{ fila.unidad }}', True, GRIS),
     ('{{ fila.municipio }}', True, GRIS)])

# --- Bajas -----------------------------------------------------------------
seccion(documento, 'Resumen de Bajas')
tabla_de_totales(documento, 'resumen_bajas', 'Total Bajas')
tabla_de_desglose(documento, 'resumen_bajas')

seccion(documento, 'Bajas del mes')
# Dieciseis columnas en 25,0 cm justos, que es el ancho util de una Carta apaisada
# con margenes de 1,4 cm. Si la suma se pasa, Word desborda la tabla fuera de la
# hoja y las ultimas columnas se salen del papel.
#
# «Actividad que realizaba» no esta: en la practica repite el texto del cargo, y
# era la columna ancha que mas espacio robaba a las que si aportan. Sigue en la
# pantalla y en el Excel, que no tienen limite de ancho.
#
# Clave, Sexo, Edad y Cat. Ocup. van estrechas a proposito: su contenido es «Si»,
# «No», una cifra de dos digitos o una sola letra. El rotulo, mas largo que el
# dato, se parte en dos lineas y no manda sobre el ancho.
tabla_de_detalle(
    documento, 'bajas',
    [('No', False), ('Nombre y Apellidos', True), ('Cargo', True),
     ('Clave', False), ('Área', True), ('Sexo', False),
     ('Edad', False), ('Cat. Ocup.', False), ('Nivel', False),
     ('Fecha', False),
     ('Causa de la Baja', True), ('Comp.\nCargo', False),
     ('Años en la Org.', True), ('Dirección / Área o UEB', True),
     ('Municipio', True), ('SPxR', False)],
    [Cm(0.9), Cm(3.2), Cm(3.0), Cm(1.0), Cm(2.1), Cm(0.8),
     Cm(0.8), Cm(1.0), Cm(1.0), Cm(1.4), Cm(2.1), Cm(1.3),
     Cm(1.7), Cm(2.0), Cm(1.6), Cm(1.1)],
    [('{{ loop.index }}', False, GRIS),
     ('{{ fila.nombre }}', True, PIZARRA),
     ('{{ fila.cargo }}', True, PIZARRA),
     ('{% if fila.puesto_clave %}Sí{% else %}No{% endif %}', False, NARANJA),
     ('{{ fila.area }}', True, GRIS),
     ((("{% if fila.sexo == 'F' %}F{% endif %}", ROSA),
       ("{% if fila.sexo == 'M' %}M{% endif %}", CIAN)), False, PIZARRA),
     ('{{ fila.edad }}', False, PIZARRA),
     ('{{ fila.categoria }}', False, AZUL),
     ('{{ fila.nivel_escolar }}', False, PIZARRA),
     ('{{ fila.fecha.strftime("%d/%m/%y") }}', False, PIZARRA),
     ('{{ fila.causa }}', True, PIZARRA),
     ('{% if fila.completar_cargo %}Sí{% else %}No{% endif %}', False, NARANJA),
     ('{{ fila.antiguedad }}', True, GRIS),
     ('{{ fila.unidad }}', True, GRIS),
     ('{{ fila.municipio }}', True, GRIS),
     ('{% if fila.cobro_sistema_pago %}Sí{% else %}No{% endif %}', False,
      NARANJA)])

os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
documento.save(DESTINO)
print('plantilla escrita en', DESTINO)
print('tablas:', len(documento.tables))
