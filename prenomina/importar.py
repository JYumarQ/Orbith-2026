"""Lectura y validación de un reporte de pago exportado a Excel.

**Este módulo no escribe nada.** Analiza el fichero, acumula todos los errores
que encuentre y devuelve un `ResultadoImportacion`. Quien escribe es
`servicios.importar_valores()`, y solo si no hay ni un error.

Esa separación es lo que hace fácil el «todo o nada» que pide el requisito:
analizar un libro de 500 filas es caro y no debe mantener bloqueada ninguna
fila; escribir es corto y va dentro de una transacción con la cabecera
bloqueada, reafirmando allí lo que se validó fuera.

Qué se importa, y qué no
------------------------
Solo **horas de ausencia** y **horas de conceptos no derivados**. Todo lo demás
—«Total a descontar», «Horas trabajadas» y el grupo rojo entero— se ignora y se
recalcula. Es una decisión, no una limitación: esas columnas son función pura de
las anteriores, así que aceptarlas permitiría meter en el documento números que
no se corresponden con sus propias entradas.

La importación **mueve valores, nunca membresía**: no añade ni quita
trabajadores. Añadir a alguien exige releer su `CAlta` viva para congelar
salario, categoría y antigüedad, y una fila de Excel no trae nada de eso.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from . import exportar
from .constantes import (CLAVE_DOC_IDENTIDAD, CLAVE_EXPEDIENTE, FILA_MAQUINA,
                         HOJA_METADATOS, HOJA_REPORTE, PREFIJO_AUSENCIA,
                         PREFIJO_HORAS, PRIMERA_FILA_DATOS,
                         TAMANO_MAXIMO_IMPORTACION, VERSION_FORMATO)


@dataclass
class FilaImportada:
    """Una fila del fichero, ya emparejada con su trabajador del reporte."""
    trabajador_pk: int
    no_expediente: str
    ausencias: dict = field(default_factory=dict)
    horas: dict = field(default_factory=dict)


@dataclass
class ResultadoImportacion:
    """Lo que devuelve el análisis. `valido` es lo único que mira la vista."""
    errores: list = field(default_factory=list)
    notas: list = field(default_factory=list)
    filas: list = field(default_factory=list)

    @property
    def valido(self):
        return not self.errores


def _error(resultado, mensaje):
    resultado.errores.append(mensaje)


# --------------------------------------------------------------------------- #
# 1. Apertura
# --------------------------------------------------------------------------- #

def _abrir(archivo, resultado):
    """Abre el libro dos veces, y esto no es un descuido.

    Con `data_only=True` openpyxl devuelve el **resultado cacheado** de las
    fórmulas de Excel. Si el usuario sustituyó un número por una fórmula y no
    llegó a abrir el fichero en Excel, esa caché no existe y la celda se lee
    `None`, que se trataría como 0 y pagaría de menos en silencio. La segunda
    lectura, con `data_only=False`, permite distinguir «celda vacía» de «fórmula
    sin calcular» y avisar.
    """
    if archivo.size > TAMANO_MAXIMO_IMPORTACION:
        _error(resultado, 'El archivo supera los 10 MB permitidos.')
        return None, None
    if not archivo.name.lower().endswith('.xlsx'):
        _error(resultado, 'El archivo debe ser un Excel con extensión .xlsx.')
        return None, None

    try:
        archivo.seek(0)
        valores = load_workbook(archivo, data_only=True)
        archivo.seek(0)
        crudo = load_workbook(archivo, data_only=False)
    except Exception:
        _error(resultado,
               'No se pudo leer el archivo. Compruebe que es un Excel válido y '
               'que no está dañado.')
        return None, None

    if HOJA_REPORTE not in valores.sheetnames:
        _error(resultado, f'El archivo no tiene la hoja «{HOJA_REPORTE}».')
        return None, None

    return valores, crudo


# --------------------------------------------------------------------------- #
# 2-3. Metadatos e identidad
# --------------------------------------------------------------------------- #

def _leer_metadatos(libro, resultado):
    if HOJA_METADATOS not in libro.sheetnames:
        _error(resultado,
               'El archivo no procede de Orbith: le falta la hoja de control. '
               'Exporte el reporte de nuevo y trabaje sobre ese archivo.')
        return {}

    hoja = libro[HOJA_METADATOS]
    return {fila[0].value: fila[1].value
            for fila in hoja.iter_rows(min_row=1, max_col=2) if fila[0].value}


def _verificar_identidad(metadatos, reporte, columnas, resultado):
    """El reporte de destino sale SIEMPRE de la URL, nunca del archivo.

    Este paso solo **rechaza**; jamás enruta. Un archivo con la unidad
    manipulada no puede llevar la importación a otra unidad.
    """
    if not metadatos:
        return

    if metadatos.get('version_formato') != VERSION_FORMATO:
        _error(resultado,
               f'El archivo usa un formato distinto del actual '
               f'(v{metadatos.get("version_formato")} frente a v{VERSION_FORMATO}). '
               f'Exporte el reporte de nuevo.')
        return

    if metadatos.get('reporte_id') != reporte.pk:
        _error(resultado,
               f'El archivo pertenece a otro reporte: '
               f'{metadatos.get("unidad_descripcion", "?")} '
               f'{metadatos.get("mes", "?")}/{metadatos.get("anno", "?")}. '
               f'Está intentando importarlo en '
               f'{reporte.unidad_descripcion} {reporte.mes}/{reporte.anno}.')
        return

    if not exportar.firma_valida(reporte, columnas, metadatos.get('firma')):
        _error(resultado,
               'La estructura del archivo no coincide con la del reporte. '
               'Probablemente cambiaron los conceptos seleccionados desde que se '
               'exportó: vuelva a exportarlo y repita los cambios.')


# --------------------------------------------------------------------------- #
# 4. Cabecera: la fila máquina
# --------------------------------------------------------------------------- #

def _leer_fila_maquina(hoja, columnas, resultado):
    """Mapa `clave -> índice de columna`.

    Que el usuario reordene las columnas se acepta sin más: es la edición
    externa más probable y no debe fallar. Lo que no se acepta es que falte una
    clave o que sobre una desconocida con datos.
    """
    encontradas = {}
    for celda in hoja[FILA_MAQUINA]:
        if celda.value:
            encontradas[str(celda.value).strip()] = celda.column

    if not encontradas:
        _error(resultado,
               'El archivo no tiene la fila de control (fila 9). No procede de '
               'una exportación de Orbith, o se eliminaron filas de la cabecera.')
        return {}

    esperadas = {c['clave'] for c in columnas}
    faltan = esperadas - set(encontradas)
    if faltan:
        _error(resultado,
               f'Faltan columnas en el archivo: {", ".join(sorted(faltan))}.')

    sobran = set(encontradas) - esperadas
    if sobran:
        resultado.notas.append(
            f'Se ignoraron columnas que no pertenecen al reporte: '
            f'{", ".join(sorted(sobran))}.')

    return encontradas


# --------------------------------------------------------------------------- #
# 5. Filas
# --------------------------------------------------------------------------- #

def _numero(celda_valor, celda_cruda, etiqueta, fila, resultado):
    """Convierte a `Decimal`, o registra el error y devuelve `None`."""
    if celda_valor is None:
        # Distinguir «vacía» de «fórmula sin resultado guardado».
        if celda_cruda is not None and isinstance(celda_cruda, str) \
                and celda_cruda.startswith('='):
            _error(resultado,
                   f'Fila {fila}, columna «{etiqueta}»: la celda contiene una '
                   f'fórmula sin resultado guardado. Ábrala en Excel, guarde el '
                   f'archivo y vuelva a intentarlo.')
            return None
        return Decimal('0')

    try:
        valor = Decimal(str(celda_valor).strip().replace(',', '.'))
    except (InvalidOperation, ValueError, AttributeError):
        _error(resultado,
               f'Fila {fila}, columna «{etiqueta}»: «{celda_valor}» no es un '
               f'número válido.')
        return None

    if valor < 0:
        _error(resultado,
               f'Fila {fila}, columna «{etiqueta}»: las horas no pueden ser '
               f'negativas ({valor}).')
        return None

    if valor != valor.quantize(Decimal('0.01')):
        resultado.notas.append(
            f'Fila {fila}, columna «{etiqueta}»: se redondeó {valor} a dos decimales.')

    return valor.quantize(Decimal('0.01'))


def _leer_filas(hoja, hoja_cruda, mapa, columnas, reporte, resultado):
    """Empareja por expediente y verifica el carnet."""
    trabajadores = {t.no_expediente: t for t in reporte.trabajadores.all()}
    editables = {c['clave']: c['titulo'] for c in columnas if c['editable']}

    col_expediente = mapa.get(CLAVE_EXPEDIENTE)
    col_carnet = mapa.get(CLAVE_DOC_IDENTIDAD)
    if not col_expediente:
        return []

    filas, vistos = [], {}
    for numero in range(PRIMERA_FILA_DATOS, hoja.max_row + 1):
        bruto = hoja.cell(row=numero, column=col_expediente).value
        if bruto is None or str(bruto).strip() == '':
            continue
        expediente = str(bruto).strip()

        if expediente in vistos:
            _error(resultado,
                   f'El expediente {expediente} aparece dos veces, en las filas '
                   f'{vistos[expediente]} y {numero}.')
            continue
        vistos[expediente] = numero

        trabajador = trabajadores.get(expediente)
        if trabajador is None:
            _error(resultado,
                   f'Fila {numero}: el expediente {expediente} no pertenece a '
                   f'este reporte. Si desea incluirlo, añádalo desde la pantalla '
                   f'del reporte.')
            continue

        # Aserción cruzada: atrapa el desastre clásico de ordenar la hoja con
        # solo parte del rango seleccionado, que desplaza los valores respecto
        # de los expedientes. Sin esto, ese error es indetectable.
        if col_carnet and trabajador.doc_identidad:
            carnet = hoja.cell(row=numero, column=col_carnet).value
            carnet = str(carnet).strip() if carnet is not None else ''
            if carnet and carnet != trabajador.doc_identidad:
                _error(resultado,
                       f'Fila {numero}: el expediente {expediente} corresponde a '
                       f'{trabajador.nombre_completo} (CI '
                       f'{trabajador.doc_identidad}), pero el archivo trae el CI '
                       f'{carnet}. El archivo pertenece a otro reporte o sus '
                       f'filas fueron reordenadas.')
                continue

        fila = FilaImportada(trabajador_pk=trabajador.pk, no_expediente=expediente)
        for clave, titulo in editables.items():
            columna = mapa.get(clave)
            if not columna:
                continue
            valor = _numero(hoja.cell(row=numero, column=columna).value,
                            hoja_cruda.cell(row=numero, column=columna).value,
                            titulo, numero, resultado)
            if valor is None:
                continue
            codigo = int(clave.split(':')[1])
            if clave.startswith(PREFIJO_AUSENCIA):
                fila.ausencias[codigo] = valor
            elif clave.startswith(PREFIJO_HORAS):
                fila.horas[codigo] = valor

        filas.append(fila)

    # Perder un bloque de filas por accidente y que nadie se entere es peor que
    # un error explícito.
    ausentes = sorted(set(trabajadores) - set(vistos))
    if ausentes:
        _error(resultado,
               f'Faltan {len(ausentes)} trabajadores del reporte en el archivo '
               f'({", ".join(ausentes[:5])}'
               f'{"…" if len(ausentes) > 5 else ""}). Si desea quitarlos, hágalo '
               f'desde la pantalla del reporte.')

    return filas


# --------------------------------------------------------------------------- #
# 6. Reglas de negocio
# --------------------------------------------------------------------------- #

def _validar_reglas(filas, reporte, resultado):
    """Las mismas reglas que impone el modal, aplicadas fila a fila.

    El tope de ausencias es el de **cada trabajador**, no uno único del reporte:
    desde que las horas del mes salen del calendario de su jornada, dos
    trabajadores de la misma unidad pueden tener topes distintos.
    """
    from . import calculos

    conceptos = list(reporte.conceptos_ausencia.all())
    horas_por_expediente = dict(
        reporte.trabajadores.values_list('no_expediente', 'horas_mes'))

    for fila in filas:
        descontadas = calculos.horas_descontadas(fila.ausencias, conceptos)
        tope = horas_por_expediente.get(fila.no_expediente)
        if tope is not None and descontadas > tope:
            _error(resultado,
                   f'Expediente {fila.no_expediente}: las horas de ausencia '
                   f'({descontadas}) superan las horas del mes de este '
                   f'trabajador ({tope}). Las horas trabajadas no pueden ser '
                   f'negativas.')


def _verificar_columnas_derivadas(hoja, mapa, reporte, resultado):
    """Una columna derivada editada a mano es error duro.

    En pantalla el campo va bloqueado, pero Excel deja escribirlo igualmente, y
    aquí el error es la única defensa. Se rechaza en vez de ignorarse porque el
    usuario creyó estar cambiando algo: aceptar el archivo en silencio le haría
    pensar que su cambio se aplicó.
    """
    from . import calculos

    derivados = {c.codigo: c for c in reporte.conceptos_horas.all() if c.es_derivado}
    if not derivados:
        return

    conceptos_ausencia = list(reporte.conceptos_ausencia.all())
    trabajadores = {t.no_expediente: t for t in reporte.trabajadores.all()}
    col_expediente = mapa.get(CLAVE_EXPEDIENTE)
    if not col_expediente:
        return

    for numero in range(PRIMERA_FILA_DATOS, hoja.max_row + 1):
        bruto = hoja.cell(row=numero, column=col_expediente).value
        if bruto is None:
            continue
        trabajador = trabajadores.get(str(bruto).strip())
        if trabajador is None:
            continue

        actuales = {v.concepto.codigo: v.horas
                    for v in trabajador.valores_ausencia.select_related('concepto')}
        esperadas = calculos.derivar_horas(actuales, conceptos_ausencia)

        for codigo, concepto in derivados.items():
            columna = mapa.get(f'{PREFIJO_HORAS}:{codigo}')
            if not columna:
                continue
            valor = hoja.cell(row=numero, column=columna).value
            if valor is None:
                continue
            try:
                leido = Decimal(str(valor))
            except (InvalidOperation, ValueError):
                continue
            if leido != esperadas.get(codigo, Decimal('0')):
                _error(resultado,
                       f'Fila {numero}, columna «{concepto.etiqueta}»: es una '
                       f'columna calculada a partir de las ausencias y no se '
                       f'puede modificar. Cambie las horas de ausencia.')


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

def analizar(archivo, reporte, usuario):
    """Analiza el fichero sin escribir nada. Devuelve un `ResultadoImportacion`."""
    from .models import EstadoReporte
    from .permisos import gestiona_unidad, puede_escribir

    resultado = ResultadoImportacion()

    if not puede_escribir(usuario) or not gestiona_unidad(usuario, reporte.unidad_id):
        _error(resultado, 'No tiene permiso para importar en este reporte.')
        return resultado
    if reporte.estado != EstadoReporte.BORRADOR:
        _error(resultado,
               f'El reporte está en estado «{reporte.get_estado_display()}» y no '
               f'admite cambios.')
        return resultado

    libro, crudo = _abrir(archivo, resultado)
    if libro is None:
        return resultado

    columnas = exportar.construir_columnas(reporte)
    _verificar_identidad(_leer_metadatos(libro, resultado), reporte, columnas,
                         resultado)
    if resultado.errores:
        return resultado

    hoja, hoja_cruda = libro[HOJA_REPORTE], crudo[HOJA_REPORTE]
    mapa = _leer_fila_maquina(hoja, columnas, resultado)
    if resultado.errores:
        return resultado

    resultado.filas = _leer_filas(hoja, hoja_cruda, mapa, columnas, reporte,
                                  resultado)
    _verificar_columnas_derivadas(hoja, mapa, reporte, resultado)
    _validar_reglas(resultado.filas, reporte, resultado)

    return resultado
