# -*- coding: utf-8 -*-
"""Genera la plantilla .docx del informe de Puestos Clave.

    .venv/Scripts/python.exe plantillas_word/generadores/crear_puestos_clave.py

No forma parte de la aplicacion y no lo importa nadie: es la herramienta con la
que se construye `plantillas_word/informes_economia/puestos_clave_template.docx`,
que es lo que la aplicacion rellena al exportar (ver
`informes.views.ExportarPuestosClaveWordView`).

POR QUE EXISTE ESTE FICHERO
---------------------------
La plantilla NO se puede tratar como un documento de Word normal. Su tabla tiene
diecinueve filas y diez de ellas estan vacias a la vista: son las que llevan las
marcas `{%tr for ... %}` y `{%tr endfor %}` que construyen la jerarquia familia
-> unidad -> subunidad -> cargos. Borrar o fusionar una de esas filas al retocar
el documento a mano deja el informe VACIO o con las filas repetidas, y sin
ningun mensaje de error que lo delate.

Con este generador, cambiar el diseno es editar una linea legible —un ancho, un
color, un tamano— y volver a ejecutarlo. Ademas el cambio se ve en un `git
diff`, cosa que con un .docx no ocurre: git solo dice que el binario cambio.

CUIDADO: LOS DOS FICHEROS VAN DE LA MANO
----------------------------------------
Si alguna vez se retoca el .docx directamente en Word, hay que traer el mismo
cambio aqui. En cuanto los dos se separan, este fichero pasa a describir una
plantilla que ya no existe, y el siguiente que lo ejecute deshara el retoque sin
enterarse.

QUE DECIDE ESTE FICHERO
-----------------------
* Apaisada y en Carta, como el PDF.
* Cabecera y pie de pagina de Word: se repiten SOLOS en cada hoja.
* «Hoja X de Y» con campos PAGE y NUMPAGES: los numera Word al abrir, asi que
  el numero es siempre el real aunque el documento se edite despues.
* Las DOS filas de cabecera de la tabla llevan `tblHeader`, la marca de Word
  para repetirlas al principio de cada pagina.
* Mismo contenido y mismos colores que la pantalla y el PDF: los tres grupos de
  columnas («Plantilla Autorizada» / «Contratos y Otros»), el verde de las
  plazas cubiertas, el naranja de las vacantes y el azul de las mujeres.
* La columna del cargo se lleva casi la mitad del ancho: los nombres reales son
  largos («Especialista A en Liniero Electrico Vigilante de Turno de Noche») y
  las otras siete solo guardan numeros de dos o tres cifras.

SOBRE LOS BUCLES DE docxtpl
---------------------------
`{%tr ... %}` no envuelve a su fila: la SUSTITUYE. La fila que lleva el `for`
desaparece y el cuerpo del bucle son las filas que van detras hasta el `endfor`,
asi que el control y el contenido nunca pueden compartir fila.
"""
import os

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

# Se resuelve desde este mismo fichero para que funcione en cualquier maquina y
# desde cualquier directorio de trabajo.
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, 'informes_economia', 'puestos_clave_template.docx')

# Paleta. Son los mismos tonos de la pantalla y del PDF, pero sin los grises
# claros: sobre papel blanco un #94A3B8 se lee lavado, y en la cabecera de Word
# —que ya se dibuja atenuada mientras editas el cuerpo— desaparece del todo.
AZUL = RGBColor(0x1E, 0x3A, 0x8A)
INDIGO = RGBColor(0x31, 0x2E, 0x81)
PIZARRA = RGBColor(0x1E, 0x29, 0x3B)
GRIS = RGBColor(0x47, 0x55, 0x69)
VERDE = RGBColor(0x05, 0x96, 0x69)
NARANJA = RGBColor(0xC2, 0x41, 0x0C)
BLANCO = RGBColor(0xFF, 0xFF, 0xFF)

# Ancho util en apaisada Carta con margenes de 1,4 cm.
ANCHO_CARGO = Cm(11.5)
ANCHO_NUMERO = Cm(1.94)


def sombrear(celda, color):
    """Fondo de una celda. python-docx no lo expone, hay que bajar al XML."""
    sombra = OxmlElement('w:shd')
    sombra.set(qn('w:val'), 'clear')
    sombra.set(qn('w:fill'), color)
    celda._tc.get_or_add_tcPr().append(sombra)


def repetir_como_cabecera(fila):
    """Marca la fila para que Word la repita al inicio de cada pagina."""
    marca = OxmlElement('w:tblHeader')
    marca.set(qn('w:val'), 'true')
    fila._tr.get_or_add_trPr().append(marca)


def campo(parrafo, instruccion):
    """Inserta un campo de Word (PAGE, NUMPAGES...) en un parrafo."""
    inicio = OxmlElement('w:fldChar')
    inicio.set(qn('w:fldCharType'), 'begin')
    texto = OxmlElement('w:instrText')
    texto.set(qn('xml:space'), 'preserve')
    texto.text = ' %s ' % instruccion
    fin = OxmlElement('w:fldChar')
    fin.set(qn('w:fldCharType'), 'end')

    run = parrafo.add_run()
    run._r.append(inicio)
    run._r.append(texto)
    run._r.append(fin)
    return run


def escribir(parrafo, texto, tamano=11, negrita=False, color=PIZARRA,
             mayusculas=False):
    run = parrafo.add_run(texto)
    run.bold = negrita
    run.font.size = Pt(tamano)
    run.font.color.rgb = color
    if mayusculas:
        run.font.all_caps = True
    return run


documento = Document()

# --- Pagina apaisada -------------------------------------------------------
seccion = documento.sections[0]
seccion.orientation = WD_ORIENT.LANDSCAPE
seccion.page_width, seccion.page_height = seccion.page_height, seccion.page_width
seccion.left_margin = seccion.right_margin = Cm(1.4)
seccion.top_margin = Cm(1.2)
seccion.bottom_margin = Cm(1.2)

# --- Cabecera de pagina (se repite sola en cada hoja) ----------------------
cabecera = seccion.header
cabecera.paragraphs[0].text = ''
tabla_cab = cabecera.add_table(rows=1, cols=3, width=seccion.page_width - Cm(2.8))
tabla_cab.autofit = True

celda_logo, celda_datos, celda_hoja = tabla_cab.rows[0].cells

# El logo lo inyecta la vista con InlineImage; sin logo, la etiqueta queda vacia.
p_logo = celda_logo.paragraphs[0]
p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(p_logo, '{{ logo }}', 10)

p1 = celda_datos.paragraphs[0]
escribir(p1, '{{ nombre_empresa }}', 16, negrita=True, color=AZUL, mayusculas=True)
p2 = celda_datos.add_paragraph()
escribir(p2, '{{ cab_provincia }}{% if cab_municipio %} · {{ cab_municipio }}{% endif %} · {{ cab_unidades_resumen }}',
         10, negrita=True, color=PIZARRA, mayusculas=True)
p3 = celda_datos.add_paragraph()
escribir(p3, 'Gestión de Capital Humano{% if cab_exportado_por %} · Exportado por {{ cab_exportado_por }}{% endif %}',
         10, negrita=True, color=GRIS, mayusculas=True)

p4 = celda_hoja.paragraphs[0]
p4.alignment = WD_ALIGN_PARAGRAPH.RIGHT
escribir(p4, 'Hoja # ', 10, negrita=True, color=GRIS)
campo(p4, 'PAGE')
escribir(p4, ' de ', 10, negrita=True, color=GRIS)
campo(p4, 'NUMPAGES')
p5 = celda_hoja.add_paragraph()
p5.alignment = WD_ALIGN_PARAGRAPH.RIGHT
escribir(p5, 'Período: {{ mes_actual }} / {{ anno_actual }}', 10, negrita=True,
         color=PIZARRA)

# --- Pie de pagina ---------------------------------------------------------
pie = seccion.footer
p_pie = pie.paragraphs[0]
escribir(p_pie, 'Generado: {{ fecha_generacion }}', 9, color=GRIS)
p_pie.add_run('\t\t')
escribir(p_pie, 'Orbith · Gestión de Recursos Humanos', 9, color=GRIS)

# --- Titulo ----------------------------------------------------------------
titulo = documento.add_paragraph()
titulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(titulo, 'Consolidado de Puestos Claves', 20, negrita=True, color=AZUL,
         mayusculas=True)

subtitulo = documento.add_paragraph()
subtitulo.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(subtitulo, '{% if cab_unidades %}Reporte de Unidad Empresarial{% else %}Reporte Estadístico Provincial{% endif %}',
         11, negrita=True, color=GRIS, mayusculas=True)

# La lista completa de unidades, solo cuando no cabe en la cabecera.
escribir(documento.add_paragraph(), '{%p if cab_lista_aparte %}', 10)
lista = documento.add_paragraph()
escribir(lista, 'Unidades incluidas: ', 10, negrita=True, color=AZUL)
escribir(lista, '{{ cab_unidades|join(" · ") }}', 10, color=PIZARRA)
escribir(documento.add_paragraph(), '{%p endif %}', 10)

# --- Tarjetas de resumen (una sola vez) ------------------------------------
kpis = [('Plantilla Aprobada', '{{ stats.aprobada }}', AZUL),
        ('Cubierta Activa', '{{ stats.cubierta }}', VERDE),
        ('Vacantes', '{{ stats.vacante }}', NARANJA),
        ('Eficiencia', '{{ stats.porcentaje }}%', INDIGO)]
tabla_kpi = documento.add_table(rows=2, cols=4)
tabla_kpi.alignment = WD_TABLE_ALIGNMENT.CENTER
for columna, (etiqueta, valor, color) in enumerate(kpis):
    arriba = tabla_kpi.cell(0, columna).paragraphs[0]
    arriba.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(arriba, etiqueta, 10, negrita=True, color=GRIS, mayusculas=True)
    abajo = tabla_kpi.cell(1, columna).paragraphs[0]
    abajo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(abajo, valor, 24, negrita=True, color=color)
    sombrear(tabla_kpi.cell(0, columna), 'F1F5F9')
    sombrear(tabla_kpi.cell(1, columna), 'F8FAFC')

documento.add_paragraph()

# --- Tabla de datos --------------------------------------------------------
# Cada columna con su clave, su titulo y el color de sus cifras. El mismo
# reparto de colores que la pantalla: cubiertas en verde, vacantes en naranja y
# mujeres en azul; el resto en gris pizarra.
COLUMNAS = [
    ('aprob', 'Aprob.', PIZARRA),
    ('cub', 'Cub.', VERDE),
    ('vac', 'Vac.', NARANJA),
    ('porc', '%', PIZARRA),
    ('det', 'Det.', PIZARRA),
    ('muj', 'Mujeres', AZUL),
    ('adiest', 'Adiest.', PIZARRA),
]

#   0-1  cabecera de columnas (dos filas, se repiten en cada pagina)
#   2    for familia          3   contenido de la familia
#   4    for unidad
#   5    if unidad.nombre     6   contenido de la unidad     7  endif
#   8    for cargo            9   contenido del cargo       10  endfor
#  11    for subunidad       12   contenido de la subunidad
#  13    for cargo           14   contenido del cargo       15  endfor
#  16    endfor (subunidades)
#  17    endfor (unidades)
#  18    endfor (familias)
#
# El `if unidad.nombre` es lo que hace que el modo consolidado no saque una fila
# de totales en blanco: ahi la «unidad» es un envoltorio sin nombre que agrupa
# todos los cargos sumados. Mismo criterio que los partials de pantalla y PDF.
tabla = documento.add_table(rows=19, cols=len(COLUMNAS) + 1)
tabla.style = 'Table Grid'
tabla.autofit = False

# Anchos: hay que ponerlos en TODAS las celdas de la columna, Word ignora el
# ancho declarado solo en la primera fila.
for fila in tabla.rows:
    fila.cells[0].width = ANCHO_CARGO
    for i in range(1, len(COLUMNAS) + 1):
        fila.cells[i].width = ANCHO_NUMERO

# Cabecera en dos alturas, como en la pantalla y el PDF.
repetir_como_cabecera(tabla.rows[0])
repetir_como_cabecera(tabla.rows[1])

celda_cargo = tabla.cell(0, 0).merge(tabla.cell(1, 0))
p = celda_cargo.paragraphs[0]
escribir(p, 'Cargo u Ocupación', 11, negrita=True, color=BLANCO, mayusculas=True)
sombrear(celda_cargo, '1E293B')

celda_plantilla = tabla.cell(0, 1).merge(tabla.cell(0, 4))
p = celda_plantilla.paragraphs[0]
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(p, 'Plantilla Autorizada', 11, negrita=True, color=BLANCO, mayusculas=True)
sombrear(celda_plantilla, '1E3A8A')

celda_contratos = tabla.cell(0, 5).merge(tabla.cell(0, 7))
p = celda_contratos.paragraphs[0]
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
escribir(p, 'Contratos y Otros', 11, negrita=True, color=BLANCO, mayusculas=True)
sombrear(celda_contratos, 'C2410C')

for i, (_clave, titulo_col, _color) in enumerate(COLUMNAS, start=1):
    celda = tabla.cell(1, i)
    p = celda.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(p, titulo_col, 10, negrita=True, color=PIZARRA)
    sombrear(celda, 'E2E8F0')


def fila_de_control(indice, etiqueta):
    """Una fila que solo lleva una etiqueta de docxtpl: desaparece al generar."""
    escribir(tabla.rows[indice].cells[0].paragraphs[0], etiqueta, 10)


def fila_de_datos(indice, nombre, expresion, tamano, color, fondo,
                  negrita=True, sangria=0, colores_de_columna=False):
    """Una fila del informe: el nombre a la izquierda y las siete cifras.

    `colores_de_columna` pinta cada cifra con el color de su columna —el verde
    de las cubiertas, el naranja de las vacantes—, que es lo que hace la
    pantalla. Las filas de total (familia, unidad) van de un solo color, para
    que se lean como un bloque.
    """
    fila = tabla.rows[indice]
    primera = fila.cells[0]
    parrafo = primera.paragraphs[0]
    if sangria:
        parrafo.paragraph_format.left_indent = Cm(sangria)
    escribir(parrafo, nombre, tamano, negrita=negrita, color=color)
    sombrear(primera, fondo)

    for i, (clave, _titulo, color_columna) in enumerate(COLUMNAS, start=1):
        celda = fila.cells[i]
        cp = celda.paragraphs[0]
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sufijo = '%' if clave == 'porc' else ''
        escribir(cp, '{{ %s.%s }}%s' % (expresion, clave, sufijo), tamano,
                 negrita=negrita,
                 color=color_columna if colores_de_columna else color)
        sombrear(celda, fondo)


fila_de_control(2, '{%tr for familia in datos_familias %}')
fila_de_datos(3, '{{ familia.nombre }}', 'familia.subtotales', 13, AZUL, 'DBEAFE')

fila_de_control(4, '{%tr for unidad in familia.unidades %}')
fila_de_control(5, '{%tr if unidad.nombre %}')
fila_de_datos(6, '{{ unidad.nombre }}', 'unidad.subtotales', 14, INDIGO, 'EEF2FF')
fila_de_control(7, '{%tr endif %}')

fila_de_control(8, '{%tr for p in unidad.puestos %}')
fila_de_datos(9, '{{ p.nombre }}', 'p', 11, PIZARRA, 'FFFFFF',
              negrita=False, sangria=0.5, colores_de_columna=True)
fila_de_control(10, '{%tr endfor %}')

fila_de_control(11, '{%tr for sub in unidad.subunidades %}')
fila_de_datos(12, '{{ sub.nombre }}', 'sub.subtotales', 12, GRIS, 'F1F5F9',
              sangria=0.5)

fila_de_control(13, '{%tr for p in sub.puestos %}')
fila_de_datos(14, '{{ p.nombre }}', 'p', 11, PIZARRA, 'FFFFFF',
              negrita=False, sangria=1.0, colores_de_columna=True)
fila_de_control(15, '{%tr endfor %}')

fila_de_control(16, '{%tr endfor %}')
fila_de_control(17, '{%tr endfor %}')
fila_de_control(18, '{%tr endfor %}')

os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
documento.save(DESTINO)
print('plantilla escrita en', DESTINO)
print('filas de la tabla:', len(tabla.rows))
