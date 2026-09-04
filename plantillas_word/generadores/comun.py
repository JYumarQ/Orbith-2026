# -*- coding: utf-8 -*-
"""Piezas comunes de los generadores de plantillas Word de los informes.

No forma parte de la aplicacion: lo usan los generadores de esta carpeta.

Aqui vive todo lo que es igual en las plantillas de los informes de RRHH —la
pagina apaisada, la cabecera y el pie que Word repite en cada hoja, la paleta y
las tarjetas de cifras— para que las cuatro se parezcan de verdad y no «casi».

CADA PLANTILLA SE PUEDE EDITAR A MANO DESPUES
---------------------------------------------
Es un .docx normal: se abre en Word y se le cambian fuentes, colores y anchos
con las herramientas de siempre. Lo unico que hay que respetar son las filas que
llevan las etiquetas `{%tr ... %}`, que parecen vacias y son las que repiten los
datos. Si se retoca a mano, conviene traer el mismo cambio al generador; si no,
el siguiente que lo ejecute deshara el retoque.
"""
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, Cm, RGBColor

# Paleta. Los mismos tonos que la pantalla y el PDF, sin los grises claros: sobre
# papel un #94A3B8 se lee lavado, y en la cabecera de Word —que ya se dibuja
# atenuada mientras editas el cuerpo— desaparece del todo.
AZUL = RGBColor(0x1E, 0x3A, 0x8A)
INDIGO = RGBColor(0x31, 0x2E, 0x81)
PIZARRA = RGBColor(0x1E, 0x29, 0x3B)
GRIS = RGBColor(0x47, 0x55, 0x69)
VERDE = RGBColor(0x05, 0x96, 0x69)
NARANJA = RGBColor(0xC2, 0x41, 0x0C)
BLANCO = RGBColor(0xFF, 0xFF, 0xFF)

FONDO_CABECERA = '1E3A8A'
FONDO_CABECERA_OSCURA = '1E293B'
FONDO_SUBCABECERA = 'E2E8F0'
FONDO_GRUPO = 'EEF2FF'


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
    """Un fragmento de texto con formato. Un `\\n` parte la linea de verdad.

    python-docx NO interpreta el salto de linea: `add_run('a\\nb')` escribe la
    barra invertida y la ene tal cual. Hace falta un `<w:br/>` explicito, y es lo
    que permite partir en dos lineas un rotulo de columna estrecha —«Comp.» /
    «Cargo»— en vez de dejarlo a merced de donde decida cortar Word.
    """
    run = parrafo.add_run()
    for indice, linea in enumerate(str(texto).split('\n')):
        if indice:
            run.add_break()
        run.add_text(linea)
    run.bold = negrita
    run.font.size = Pt(tamano)
    run.font.color.rgb = color
    if mayusculas:
        run.font.all_caps = True
    return run


def documento_apaisado():
    """Un .docx en Carta apaisada con la cabecera y el pie del informe puestos.

    La cabecera y el pie de Word se repiten SOLOS en cada hoja: es la forma
    correcta de que la identificacion y la fecha salgan en todas, sin duplicar
    nada en el cuerpo.
    """
    documento = Document()

    seccion = documento.sections[0]
    seccion.orientation = WD_ORIENT.LANDSCAPE
    seccion.page_width, seccion.page_height = seccion.page_height, seccion.page_width
    seccion.left_margin = seccion.right_margin = Cm(1.4)
    seccion.top_margin = Cm(1.2)
    seccion.bottom_margin = Cm(1.2)

    # --- Cabecera ---------------------------------------------------------
    cabecera = seccion.header
    cabecera.paragraphs[0].text = ''
    tabla = cabecera.add_table(rows=1, cols=3, width=seccion.page_width - Cm(2.8))
    tabla.autofit = True
    celda_logo, celda_datos, celda_hoja = tabla.rows[0].cells

    # El logo lo inyecta la vista con InlineImage; sin logo, la etiqueta queda
    # vacia y la cabecera no se descuadra.
    parrafo = celda_logo.paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(parrafo, '{{ logo }}', 10)

    escribir(celda_datos.paragraphs[0], '{{ nombre_empresa }}', 16,
             negrita=True, color=AZUL, mayusculas=True)
    escribir(celda_datos.add_paragraph(),
             '{{ cab_provincia }}{% if cab_municipio %} · {{ cab_municipio }}'
             '{% endif %} · {{ cab_unidades_resumen }}',
             10, negrita=True, color=PIZARRA, mayusculas=True)
    escribir(celda_datos.add_paragraph(),
             'Gestión de Capital Humano{% if cab_exportado_por %} · Exportado por '
             '{{ cab_exportado_por }}{% endif %}',
             10, negrita=True, color=GRIS, mayusculas=True)

    parrafo = celda_hoja.paragraphs[0]
    parrafo.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    escribir(parrafo, 'Hoja # ', 10, negrita=True, color=GRIS)
    campo(parrafo, 'PAGE')
    escribir(parrafo, ' de ', 10, negrita=True, color=GRIS)
    campo(parrafo, 'NUMPAGES')
    parrafo = celda_hoja.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    escribir(parrafo, 'Período: {{ mes_actual }} / {{ anno_actual }}', 10,
             negrita=True, color=PIZARRA)

    # --- Pie --------------------------------------------------------------
    pie = seccion.footer
    parrafo = pie.paragraphs[0]
    escribir(parrafo, 'Generado: {{ fecha_generacion }}', 9, color=GRIS)
    parrafo.add_run('\t\t')
    escribir(parrafo, 'Orbith · Gestión de Recursos Humanos', 9, color=GRIS)

    return documento


def titulo(documento, texto):
    """Titulo y subtitulo del informe, centrados."""
    parrafo = documento.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(parrafo, texto, 20, negrita=True, color=AZUL, mayusculas=True)

    parrafo = documento.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    escribir(parrafo,
             '{% if cab_unidades %}Reporte de Unidad Empresarial'
             '{% else %}Reporte Estadístico Provincial{% endif %}',
             11, negrita=True, color=GRIS, mayusculas=True)


def lista_de_unidades(documento):
    """La lista completa de unidades, solo cuando no cabe en la cabecera."""
    escribir(documento.add_paragraph(), '{%p if cab_lista_aparte %}', 10)
    parrafo = documento.add_paragraph()
    escribir(parrafo, 'Unidades incluidas: ', 10, negrita=True, color=AZUL)
    escribir(parrafo, '{{ cab_unidades|join(" · ") }}', 10, color=PIZARRA)
    escribir(documento.add_paragraph(), '{%p endif %}', 10)


def tarjetas(documento, cifras):
    """Fila de tarjetas de cifra. `cifras` son ternas (rotulo, valor, color)."""
    tabla = documento.add_table(rows=2, cols=len(cifras))
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER
    for columna, (rotulo, valor, color) in enumerate(cifras):
        arriba = tabla.cell(0, columna).paragraphs[0]
        arriba.alignment = WD_ALIGN_PARAGRAPH.CENTER
        escribir(arriba, rotulo, 10, negrita=True, color=GRIS, mayusculas=True)
        abajo = tabla.cell(1, columna).paragraphs[0]
        abajo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        escribir(abajo, valor, 24, negrita=True, color=color)
        sombrear(tabla.cell(0, columna), 'F1F5F9')
        sombrear(tabla.cell(1, columna), 'F8FAFC')
    documento.add_paragraph()
    return tabla


def cabecera_de_tabla(tabla, columnas, anchos=None):
    """Primera fila de la tabla de datos, marcada para repetirse por pagina.

    `columnas` son pares (titulo, alineado_a_la_izquierda).
    """
    fila = tabla.rows[0]
    repetir_como_cabecera(fila)
    for i, (titulo_col, a_la_izquierda) in enumerate(columnas):
        celda = fila.cells[i]
        parrafo = celda.paragraphs[0]
        parrafo.alignment = (WD_ALIGN_PARAGRAPH.LEFT if a_la_izquierda
                             else WD_ALIGN_PARAGRAPH.CENTER)
        escribir(parrafo, titulo_col, 10, negrita=True, color=BLANCO,
                 mayusculas=True)
        sombrear(celda, FONDO_CABECERA)

    if anchos:
        for fila_tabla in tabla.rows:
            for i, ancho in enumerate(anchos):
                fila_tabla.cells[i].width = ancho


def fila_de_control(tabla, indice, etiqueta):
    """Una fila que solo lleva una etiqueta de docxtpl: desaparece al generar.

    `{%tr ... %}` NO envuelve a su fila: la SUSTITUYE. El cuerpo del bucle son
    las filas que van detras, asi que el control y el contenido nunca pueden
    compartir fila.
    """
    escribir(tabla.rows[indice].cells[0].paragraphs[0], etiqueta, 10)
