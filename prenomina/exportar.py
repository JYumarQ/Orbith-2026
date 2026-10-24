"""Exportación de un reporte de pago a Excel.

El fichero que sale de aquí tiene que cumplir dos cosas a la vez, y son
distintas:

1. **Que RRHH lo reconozca.** Reproduce la hoja real (`Reporte de pago`): mismas
   zonas de color, misma cabecera de dos niveles, mismas columnas de esqueleto y
   el mismo bloque de encabezado con «Horas del mes» y las tres firmas.
2. **Que se pueda volver a importar** después de editarlo por fuera. Para eso el
   fichero lleva su propia identidad, en tres capas que se complementan:

   * una **fila máquina oculta** (fila 9) con una clave por columna, que permite
     reconocer cada concepto aunque el usuario reordene las columnas;
   * una **columna oculta** con el carnet de identidad, que detecta las filas
     desplazadas (el desastre clásico: ordenar por nombre con solo parte del
     rango seleccionado);
   * una **hoja de metadatos** (`_orbith`, `veryHidden`) con la identidad del
     reporte y una firma HMAC.

Sobre la firma, dicho sin adornos: **no es una medida de seguridad**. El fichero
está en manos del usuario y las celdas de datos están hechas para editarse. Es
evidencia de manipulación de la *identidad y la forma*: convierte «importé el
archivo del mes equivocado» en un mensaje comprensible en vez de en corrupción
silenciosa. La frontera de seguridad real es la comprobación de permisos sobre
el reporte de destino, que es independiente y se hace siempre.

`openpyxl` ya estaba en `requirements.txt`: no se añade ninguna dependencia.
"""

import hashlib
import hmac
from io import BytesIO

from django.conf import settings
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter

from .constantes import (CLAVE_CATEGORIA, CLAVE_DOC_IDENTIDAD, CLAVE_EXPEDIENTE,
                         CLAVE_HORAS_TRABAJADAS, CLAVE_NOMBRE, CLAVE_SALARIO,
                         CLAVE_TOTAL_DESCUENTO, COLOR_AUSENCIA,
                         COLOR_PAGO_HORAS, COLOR_PAGO_IMPORTE,
                         COLOR_TRABAJADAS, COLOR_TRABAJADOR, FILA_COLUMNAS,
                         FILA_GRUPOS, FILA_MAQUINA, HOJA_ESCALA,
                         HOJA_METADATOS, HOJA_REPORTE, PREFIJO_AUSENCIA,
                         PREFIJO_HORAS, PREFIJO_IMPORTE, PRIMERA_FILA_DATOS,
                         VERSION_FORMATO)

TIPO_XLSX = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')

_BORDE = Border(bottom=Side(style='thin'), right=Side(style='thin'))
_CENTRADO = Alignment(horizontal='center', vertical='center', wrap_text=True)
_VERTICAL = Alignment(horizontal='center', vertical='bottom', textRotation=90,
                      wrap_text=True)


def _relleno(color):
    return PatternFill(start_color=color, end_color=color, fill_type='solid')


# --------------------------------------------------------------------------- #
# Firma
# --------------------------------------------------------------------------- #

def _mensaje_de_firma(reporte, columnas):
    """Lo que la firma protege: identidad del reporte y forma del fichero."""
    claves = '|'.join(c['clave'] for c in columnas)
    return '|'.join(str(parte) for parte in (
        VERSION_FORMATO, reporte.pk, reporte.unidad_id, reporte.anno,
        reporte.mes, reporte.trabajadores.count(), claves))


def firmar(reporte, columnas):
    return hmac.new(settings.SECRET_KEY.encode('utf-8'),
                    _mensaje_de_firma(reporte, columnas).encode('utf-8'),
                    hashlib.sha256).hexdigest()


def firma_valida(reporte, columnas, firma):
    """Comparación en tiempo constante, por costumbre más que por necesidad."""
    return hmac.compare_digest(firmar(reporte, columnas), firma or '')


# --------------------------------------------------------------------------- #
# Estructura de columnas
# --------------------------------------------------------------------------- #

def construir_columnas(reporte):
    """Descripción de cada columna del fichero, en orden.

    Es la **única** fuente de la estructura: la usan el exportador, la firma y el
    importador. Si el orden de las columnas viviera en dos sitios, un cambio en
    uno rompería el otro en silencio.

    Cada entrada trae `clave` (lo que va en la fila máquina), `titulo`, `grupo`
    (para el color y los merges) y `editable` (si la importación acepta su
    valor).
    """
    columnas = [
        {'clave': CLAVE_EXPEDIENTE, 'titulo': 'Expediente',
         'grupo': 'trabajador', 'ancho': 12, 'editable': False},
        {'clave': CLAVE_NOMBRE, 'titulo': 'Nombres y Apellidos',
         'grupo': 'trabajador', 'ancho': 30, 'editable': False},
        {'clave': CLAVE_CATEGORIA, 'titulo': 'Categoría Ocupacional',
         'grupo': 'trabajador', 'ancho': 8, 'editable': False},
        {'clave': CLAVE_SALARIO, 'titulo': 'Salario Escala',
         'grupo': 'trabajador', 'ancho': 12, 'editable': False},
    ]

    for concepto in reporte.conceptos_ausencia.all():
        columnas.append({
            'clave': f'{PREFIJO_AUSENCIA}:{concepto.codigo}',
            'titulo': concepto.etiqueta, 'grupo': 'ausencia',
            'ancho': 6, 'editable': True, 'concepto': concepto})

    if reporte.conceptos_ausencia.exists():
        columnas.append({
            'clave': CLAVE_TOTAL_DESCUENTO, 'titulo': 'Total a descontar',
            'grupo': 'ausencia', 'ancho': 8, 'editable': False})

    columnas.append({
        'clave': CLAVE_HORAS_TRABAJADAS, 'titulo': 'Horas trabajadas',
        'grupo': 'trabajadas', 'ancho': 9, 'editable': False})

    for concepto in reporte.conceptos_horas.all():
        columnas.append({
            'clave': f'{PREFIJO_HORAS}:{concepto.codigo}',
            'titulo': concepto.etiqueta, 'grupo': 'horas', 'ancho': 6,
            # Un concepto derivado NO es editable: su valor es la suma de las
            # ausencias que lo alimentan. Excel deja escribirlo igualmente, así
            # que el importador lo rechaza explícitamente.
            'editable': not concepto.es_derivado, 'concepto': concepto})

    for concepto in reporte.conceptos_importe.all():
        columnas.append({
            'clave': f'{PREFIJO_IMPORTE}:{concepto.codigo}',
            'titulo': concepto.etiqueta, 'grupo': 'importe', 'ancho': 9,
            # Todo el grupo rojo se recalcula al importar: es fijo o es fórmula.
            'editable': False, 'concepto': concepto})

    columnas.append({
        'clave': CLAVE_DOC_IDENTIDAD, 'titulo': 'Documento de identidad',
        'grupo': 'oculta', 'ancho': 14, 'editable': False})

    return columnas


_RELLENO_POR_GRUPO = {
    'trabajador': COLOR_TRABAJADOR,
    'ausencia': COLOR_AUSENCIA,
    'trabajadas': COLOR_TRABAJADAS,
    'horas': COLOR_PAGO_HORAS,
    'importe': COLOR_PAGO_IMPORTE,
    'oculta': COLOR_TRABAJADOR,
}

_TITULO_DE_GRUPO = {
    'ausencia': 'Descuentos en horas (ausencias)',
    'horas': 'Pagos asociados por horas',
    'importe': 'Pagos asociados por Importe',
}


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #

def filas_de(reporte):
    """Valores de cada trabajador, indexados por clave de columna.

    Tres consultas y un pivote en Python, igual que la rejilla: la alternativa
    —recorrer las relaciones por fila— dispararía una consulta por celda.
    """
    trabajadores = reporte.trabajadores.prefetch_related(
        'valores_ausencia__concepto', 'valores_horas__concepto',
        'valores_importe__concepto')

    for trabajador in trabajadores:
        valores = {
            CLAVE_EXPEDIENTE: trabajador.no_expediente,
            CLAVE_NOMBRE: trabajador.nombre_completo,
            CLAVE_CATEGORIA: trabajador.cat_ocupacional,
            CLAVE_SALARIO: trabajador.salario_escala,
            CLAVE_TOTAL_DESCUENTO: trabajador.total_horas_descontadas,
            CLAVE_HORAS_TRABAJADAS: trabajador.horas_trabajadas,
            CLAVE_DOC_IDENTIDAD: trabajador.doc_identidad,
        }
        for valor in trabajador.valores_ausencia.all():
            valores[f'{PREFIJO_AUSENCIA}:{valor.concepto.codigo}'] = valor.horas
        for valor in trabajador.valores_horas.all():
            valores[f'{PREFIJO_HORAS}:{valor.concepto.codigo}'] = valor.horas
        for valor in trabajador.valores_importe.all():
            valores[f'{PREFIJO_IMPORTE}:{valor.concepto.codigo}'] = valor.importe
        yield valores


# --------------------------------------------------------------------------- #
# Construcción del libro
# --------------------------------------------------------------------------- #

def _escribir_encabezado(hoja, reporte, ultima):
    """Filas 1 a 5: título, unidad, horas del mes, período y firmas."""
    letra = get_column_letter(ultima)

    hoja['A1'] = 'REPORTE DE PAGO'
    hoja['A1'].font = Font(bold=True, size=14)
    hoja.merge_cells(f'A1:{letra}1')
    hoja['A1'].alignment = Alignment(horizontal='center')

    hoja['A2'] = 'Unidad Organizativa:'
    hoja['A2'].font = Font(bold=True)
    hoja['C2'] = reporte.unidad_descripcion
    hoja['G2'] = 'Horas del mes:'
    hoja['G2'].font = Font(bold=True)
    hoja['I2'] = reporte.fondo_tiempo

    hoja['A4'] = 'Período de Pago:'
    hoja['A4'].font = Font(bold=True)
    hoja['C4'] = 'Desde'
    hoja['D4'] = reporte.fecha_desde
    hoja['D4'].number_format = 'DD/MM/YYYY'
    hoja['F4'] = 'Hasta'
    hoja['G4'] = reporte.fecha_hasta
    hoja['G4'].number_format = 'DD/MM/YYYY'

    hoja['A5'] = 'Hecho por:'
    hoja['A5'].font = Font(bold=True)
    hoja['C5'] = reporte.hecho_por
    hoja['F5'] = 'Revisado por:'
    hoja['F5'].font = Font(bold=True)
    hoja['H5'] = reporte.revisado_por
    hoja['K5'] = 'Aprobado por:'
    hoja['K5'].font = Font(bold=True)
    hoja['M5'] = reporte.aprobado_por


def _escribir_cabecera_de_tabla(hoja, columnas):
    """Filas 7 y 8: grupos con sus merges de color, y el título de cada columna."""
    inicio_grupo = None
    grupo_actual = None

    for indice, columna in enumerate(columnas, start=1):
        relleno = _relleno(_RELLENO_POR_GRUPO[columna['grupo']])
        letra = get_column_letter(indice)
        hoja.column_dimensions[letra].width = columna['ancho']

        celda = hoja.cell(row=FILA_COLUMNAS, column=indice, value=columna['titulo'])
        celda.fill = relleno
        celda.font = Font(bold=True, color='FFFFFF')
        celda.alignment = _VERTICAL if columna['grupo'] in _TITULO_DE_GRUPO else _CENTRADO
        celda.border = _BORDE

        # Las columnas sin grupo (identidad, horas trabajadas) se combinan en
        # vertical con la fila 7, como en el original.
        if columna['grupo'] not in _TITULO_DE_GRUPO:
            superior = hoja.cell(row=FILA_GRUPOS, column=indice)
            superior.fill = relleno
            superior.border = _BORDE
            hoja.merge_cells(start_row=FILA_GRUPOS, start_column=indice,
                             end_row=FILA_COLUMNAS, end_column=indice)
            superior.value = columna['titulo']
            superior.font = Font(bold=True, color='FFFFFF')
            superior.alignment = _CENTRADO
            celda.value = None

        # Cierre del grupo anterior cuando cambia.
        if grupo_actual != columna['grupo']:
            _cerrar_grupo(hoja, grupo_actual, inicio_grupo, indice - 1)
            grupo_actual, inicio_grupo = columna['grupo'], indice

    _cerrar_grupo(hoja, grupo_actual, inicio_grupo, len(columnas))


def _cerrar_grupo(hoja, grupo, inicio, fin):
    """Escribe la cabecera de grupo de la fila 7 y la combina."""
    if grupo not in _TITULO_DE_GRUPO or inicio is None or fin < inicio:
        return
    celda = hoja.cell(row=FILA_GRUPOS, column=inicio, value=_TITULO_DE_GRUPO[grupo])
    celda.fill = _relleno(_RELLENO_POR_GRUPO[grupo])
    celda.font = Font(bold=True, color='FFFFFF')
    celda.alignment = _CENTRADO
    if fin > inicio:
        hoja.merge_cells(start_row=FILA_GRUPOS, start_column=inicio,
                         end_row=FILA_GRUPOS, end_column=fin)


def _escribir_fila_maquina(hoja, columnas):
    """Fila 9, oculta: una clave por columna.

    Se empareja por **código** y no por el texto visible: las descripciones las
    edita el Administrador y llevan tildes, así que emparejar por texto rompería
    la importación el día que alguien corrija una errata.
    """
    for indice, columna in enumerate(columnas, start=1):
        celda = hoja.cell(row=FILA_MAQUINA, column=indice, value=columna['clave'])
        celda.font = Font(color='FFFFFF', size=1)
    hoja.row_dimensions[FILA_MAQUINA].hidden = True


def _escribir_datos(hoja, columnas, filas):
    """Filas de datos, con el mismo pintado por zonas que el original."""
    total = 0
    for numero, valores in enumerate(filas, start=PRIMERA_FILA_DATOS):
        total += 1
        for indice, columna in enumerate(columnas, start=1):
            celda = hoja.cell(row=numero, column=indice,
                              value=valores.get(columna['clave']))
            celda.fill = _relleno(_RELLENO_POR_GRUPO[columna['grupo']])
            celda.border = _BORDE
            if columna['grupo'] in ('ausencia', 'horas', 'trabajadas'):
                celda.number_format = '0.00'
            elif columna['grupo'] == 'importe' or columna['clave'] == CLAVE_SALARIO:
                celda.number_format = '#,##0.00'
            # Solo se desbloquean las celdas que la importación acepta. Es una
            # ayuda de usabilidad —Excel avisa al escribir en una calculada—, no
            # un control: quitar la protección de hoja es trivial.
            celda.protection = Protection(locked=not columna['editable'])
    return total


def _escribir_hoja_escala(libro, reporte):
    """Copia de la escala de años de servicio congelada, como referencia.

    Es de solo lectura: la importación la ignora. Se incluye porque el Excel
    original la traía y porque explica de dónde sale la columna «Años de
    servicio» sin obligar a abrir el sistema.
    """
    concepto = reporte.conceptos_importe.exclude(escala_congelada={}).first()
    if concepto is None:
        return

    hoja = libro.create_sheet(HOJA_ESCALA)
    hoja['A1'] = 'Años'
    hoja['B1'] = 'Cuantía'
    hoja['A1'].font = hoja['B1'].font = Font(bold=True)
    for fila, annos in enumerate(sorted(concepto.escala_congelada, key=int), start=2):
        hoja.cell(row=fila, column=1, value=int(annos))
        hoja.cell(row=fila, column=2, value=float(concepto.escala_congelada[annos]))


def _escribir_metadatos(libro, reporte, columnas, total_filas):
    """Hoja `veryHidden` con la identidad del reporte y la firma."""
    hoja = libro.create_sheet(HOJA_METADATOS)
    datos = [
        ('version_formato', VERSION_FORMATO),
        ('reporte_id', reporte.pk),
        ('unidad_codigo', reporte.unidad_id),
        ('unidad_descripcion', reporte.unidad_descripcion),
        ('anno', reporte.anno),
        ('mes', reporte.mes),
        ('estado', reporte.estado),
        ('fondo_tiempo', str(reporte.fondo_tiempo)),
        ('n_trabajadores', total_filas),
        ('firma', firmar(reporte, columnas)),
    ]
    for fila, (clave, valor) in enumerate(datos, start=1):
        hoja.cell(row=fila, column=1, value=clave)
        hoja.cell(row=fila, column=2, value=valor)
    hoja.sheet_state = 'veryHidden'


def construir_libro(reporte):
    """Libro completo, listo para guardar. Separado de la vista para poder probarlo."""
    columnas = construir_columnas(reporte)

    libro = Workbook()
    hoja = libro.active
    hoja.title = HOJA_REPORTE

    _escribir_encabezado(hoja, reporte, len(columnas))
    _escribir_cabecera_de_tabla(hoja, columnas)
    _escribir_fila_maquina(hoja, columnas)
    total = _escribir_datos(hoja, columnas, filas_de(reporte))

    # La columna del carnet va oculta: sirve para detectar filas desplazadas al
    # importar, no para que nadie la lea.
    hoja.column_dimensions[get_column_letter(len(columnas))].hidden = True

    # Paneles inmovilizados en la primera fila de datos y tras las columnas de
    # identidad, que es exactamente lo que hace la rejilla en pantalla.
    hoja.freeze_panes = hoja.cell(row=PRIMERA_FILA_DATOS, column=5)
    # Sin contrasena a proposito: es un aviso, no un control. Quien quiera
    # editar una columna calculada solo tiene que quitar la protección, y eso
    # está bien: la validación de verdad la hace el importador.
    hoja.protection.sheet = True

    _escribir_hoja_escala(libro, reporte)
    _escribir_metadatos(libro, reporte, columnas, total)
    return libro


def nombre_de_archivo(reporte):
    """Nombre del fichero descargado.

    Lleva la quincena SOLO cuando la hay: con pago Mensual el nombre es el de
    siempre. Sin ese sufijo, descargar las dos quincenas del mismo mes dejaría
    dos ficheros con idéntico nombre en la carpeta de descargas y el segundo
    taparía al primero.

    La firma del libro (`_mensaje_de_firma`) NO se toca: ya identifica al
    reporte por su `pk`, y cambiarla invalidaría los ficheros exportados antes
    de existir las quincenas.
    """
    from core.nombres_descarga import NOMBRES_DE_MES, nombre_de_informe
    partes = ['Prenomina', reporte.unidad_descripcion or 'Unidad',
              NOMBRES_DE_MES[reporte.mes - 1] if 1 <= reporte.mes <= 12 else reporte.mes,
              reporte.anno]
    if reporte.quincena:
        partes.append('Quincena_%s' % reporte.quincena)
    return nombre_de_informe(*partes, extension='xlsx', fecha=False)


def exportar(reporte):
    """Respuesta HTTP con el fichero.

    El `Content-Type` y el `Content-Disposition` son además lo que hace que
    `progreso.DeteccionExportacionMiddleware` detecte la descarga sin que haya
    que cablear nada.
    """
    memoria = BytesIO()
    construir_libro(reporte).save(memoria)
    memoria.seek(0)

    respuesta = HttpResponse(memoria.read(), content_type=TIPO_XLSX)
    respuesta['Content-Disposition'] = (
        f'attachment; filename="{nombre_de_archivo(reporte)}"')
    return respuesta
