"""Congelado de la unidad y de los trabajadores en un reporte de pago.

Equivalente de `cierres/captura.py`, y con los dos mismos criterios de fondo:

* **Se releen los datos de la base**, nunca se usan instancias que venga del
  llamador: una instancia en memoria puede traer valores a medio validar.
* **No se guardan ForeignKey a datos vivos**, solo copias planas. Aquí el motivo
  es más agudo que en Cierres: cuando un trabajador causa baja, su `CAlta` **se
  borra físicamente**, así que una FK dejaría inconsultable el reporte del mes
  anterior.

A diferencia de Cierres, aquí **sí se filtra**: un reporte de pago es la nómina
de quien estaba trabajando, no un censo de la plantilla. Se cargan los contratos
cuyo aspirante está `ACTIVO`, que es el mismo criterio que usa la tarjeta de
Antigüedad del Dashboard.

El alcance del reporte **incluye las subunidades**: el reporte de una Dirección
Principal recoge también a los trabajadores de las unidades que cuelgan de ella.
La expansión no se reimplementa aquí, se delega en
`informes.fuentes.expandir_unidades()`, que ya era el único sitio donde vivía esa
cascada. Como contrapartida, `servicios.crear_reporte()` impide que un mismo
trabajador acabe en dos reportes del mismo período (el de su subunidad y el de su
padre), que es la forma en que este alcance podría pagar dos veces.
"""

from datetime import date
from decimal import Decimal

from contratos.models import CAlta

from .models import ReporteTrabajador

# Los mismos `select_related` que `cierres/captura.py`: sin ellos, congelar una
# unidad de 200 trabajadores lanza cientos de consultas sueltas.
_RELACIONES = (
    'aspirante', 'cargo', 'cargo__departamento',
    'cargo__departamento__unidad_organizativa', 'cargo__ncargo',
    'cargo__ncargo__grupo_escala', 'cargo__rol', 'tridente',
    'cnci_nomenclador', 'instructor_nomenclador',
    # La jornada asignada y su calendario: sin esto, congelar 200 trabajadores
    # lanzaría 400 consultas sueltas para averiguar las horas de cada uno.
    'asignacion_calendario', 'asignacion_calendario__calendario',
)


def _nombre_completo(aspirante):
    partes = [aspirante.nombre, aspirante.papellido, aspirante.sapellido]
    return ' '.join(p for p in partes if p).strip()[:150]


def annos_de_servicio(fecha_alta_entidad, referencia=None):
    """Años completos de servicio a una fecha dada.

    Misma semántica de «años completos» que `Aspirante.get_edad` y que el
    `EdadExacta` del Dashboard, pero calculada en Python y **contra la fecha de
    referencia del reporte**, no contra hoy.

    Esa es la diferencia importante: `EdadExacta` usa `AGE()` de PostgreSQL, que
    siempre mide contra la fecha actual. Si el reporte de julio se cerrara en
    septiembre, ese cálculo daría los años que el trabajador tiene en septiembre.
    Un documento de pago tiene que reflejar la antigüedad al cierre de SU
    período.
    """
    if not fecha_alta_entidad:
        return 0
    referencia = referencia or date.today()
    annos = referencia.year - fecha_alta_entidad.year - (
        (referencia.month, referencia.day)
        < (fecha_alta_entidad.month, fecha_alta_entidad.day)
    )
    return max(annos, 0)


def unidades_del_reporte(unidad):
    """La unidad y, si es principal, sus subunidades.

    Se delega en `informes.fuentes.expandir_unidades()` en vez de recorrer
    `direcciones_hijas` aquí: esa cascada ya estaba copiada en cuatro vistas y se
    unificó allí. Duplicarla sería reabrir el problema que ese módulo cerró.
    """
    from informes.fuentes import expandir_unidades
    return expandir_unidades(unidad.pk) or [unidad.pk]


def contratos_de(unidad):
    """Contratos activos del alcance del reporte, listos para congelar.

    El camino trabajador → unidad es el mismo de todo el proyecto
    (`cierres/captura.py`, `contratos/filtros.py`):
    `CAlta.cargo → CargoPlantilla.departamento → Departamento.unidad_organizativa`.

    El orden importa más de lo habitual: la rejilla del detalle agrupa la
    lista congelada por Sub Unidad y luego por Departamento apoyándose en que
    ya viene contigua (`views._rejilla`, vía `itertools.groupby`), sin volver a
    ordenarla. Por eso se ordena primero por la subunidad
    (`unidad_organizativa__orden_informe`) y solo después por su departamento.
    """
    return (CAlta.objects
            .filter(cargo__departamento__unidad_organizativa__in=unidades_del_reporte(unidad),
                    aspirante__estado='ACTIVO')
            .select_related(*_RELACIONES)
            .order_by('cargo__departamento__unidad_organizativa__orden_informe',
                      'cargo__departamento__orden_informe',
                      'aspirante__papellido', 'aspirante__nombre', 'id'))


def datos_de_unidad(unidad):
    """Campos de la unidad que quedan congelados en la cabecera del reporte."""
    return {
        'unidad_codigo_original': unidad.pk,
        'unidad_descripcion': unidad.descripcion or '',
        'unidad_grupo_nomina': unidad.grupo_nomina,
        'unidad_orden_informe': unidad.orden_informe,
    }


def _tarifa_horaria(salario, fondo_tarifa):
    """Salario de escala dividido entre el fondo de tarifa, con 4 decimales.

    Es la misma operación que `contratos/views.py` repite en cada pantalla de
    contrato (`round(monto / fondo, 5)`). Aquí se conserva a 4 decimales porque
    es un valor **intermedio** de las fórmulas: el redondeo a 2 se aplica una
    sola vez, sobre el importe final.

    No se llama a `contratos.salarios.calcular_salario()` porque no hace falta:
    `CAlta.salario_actual` ya es su resultado, recalculado en cada guardado del
    contrato. Recalcularlo aquí sería duplicar la fuente de verdad.
    """
    if not salario or not fondo_tarifa:
        return Decimal('0')
    return (Decimal(salario) / Decimal(fondo_tarifa)).quantize(Decimal('0.0001'))


def horas_del_periodo(usuario, anno, mes):
    """`{calendario_id: (codigo, descripcion, horas_mes)}` del período del usuario.

    Es el puente entre el Calendario de Pago y el reporte: se consulta una sola
    vez por reporte y después cada trabajador busca en el diccionario las horas
    de su jornada, en vez de ir a la base de datos fila a fila.

    Se leen el código y la descripción **históricos** de la línea, no los del
    calendario maestro: es lo que el usuario vio y aprobó al montar el período.
    """
    from .models import CalendarioPago

    periodo = CalendarioPago.objects.filter(
        usuario=usuario, anno=anno, mes=mes).first()
    if periodo is None:
        return {}
    return {
        detalle.calendario_id: (detalle.codigo_historico,
                                detalle.descripcion_historica,
                                detalle.horas_mes)
        for detalle in periodo.detalles.all()
    }


def calendario_de(contrato, horas_por_calendario):
    """Código, descripción y horas del mes que le tocan a un trabajador.

    Devuelve `None` si no se le puede asignar un fondo de tiempo, que ocurre en
    dos casos distintos y ambos son un problema real que hay que resolver antes
    de crear el reporte:

    * el trabajador no tiene calendario asignado (Pre-Nómina → Asignar Calendario);
    * lo tiene, pero ese calendario no está incluido en el Calendario de Pago
      del período, así que no hay horas definidas para él ese mes.

    No se inventa un valor por defecto a propósito: unas horas equivocadas en un
    documento de pago no se notan hasta que alguien cobra de menos.
    """
    asignacion = getattr(contrato, 'asignacion_calendario', None)
    if asignacion is None:
        return None
    return horas_por_calendario.get(asignacion.calendario_id)


def datos_de_trabajador(contrato, *, fondo_tarifa, referencia,
                        horas_por_calendario=None):
    """Todo lo que se congela de un trabajador, como diccionario.

    Se devuelve un diccionario y no una instancia para que sirva igual al crear
    la fila y al re-congelarla («Actualizar datos del trabajador»), sin duplicar
    la lista de campos.

    `horas_por_calendario` viene de `horas_del_periodo()`. Si no se pasa, el
    trabajador se congela sin horas (0): quien llama es responsable de haber
    comprobado antes que todos tienen calendario — lo hace
    `servicios._exigir_calendarios()`.
    """
    aspirante = contrato.aspirante
    cargo = contrato.cargo
    ncargo = cargo.ncargo if cargo else None
    unidad_sub = (cargo.departamento.unidad_organizativa
                  if cargo and cargo.departamento else None)
    calendario = calendario_de(contrato, horas_por_calendario or {})
    codigo_cal, descripcion_cal, horas_mes = calendario or (None, '', Decimal('0'))

    # `cat_ocupacional` son `choices`, no una tabla: se congelan clave Y
    # etiqueta. El Excel imprime la etiqueta, y las etiquetas de un `choices`
    # pueden reescribirse en cualquier despliegue.
    categoria = ncargo.cat_ocupacional if ncargo else ''
    categoria_desc = ncargo.get_cat_ocupacional_display() if ncargo and categoria else ''

    # `salario_actual` es, pese al nombre, el salario DE ESCALA: lo calcula
    # `contratos/salarios.py` y no incluye maestría, CNCI ni instructor, que en
    # este reporte son columnas aparte del grupo rojo.
    salario = contrato.salario_actual or Decimal('0')

    return {
        'contrato_id_original': contrato.pk,
        'aspirante_id_original': contrato.aspirante_id,
        'no_expediente': contrato.no_expediente or '',
        'doc_identidad': aspirante.doc_identidad or '' if aspirante else '',
        'nombre_completo': _nombre_completo(aspirante) if aspirante else '',
        'cat_ocupacional': categoria,
        'cat_ocupacional_desc': categoria_desc,
        'ncargo_descripcion': ncargo.descripcion if ncargo else '',
        'departamento_descripcion': (
            cargo.departamento.descripcion if cargo and cargo.departamento else ''),
        'unidad_sub_id_original': unidad_sub.pk if unidad_sub else None,
        'unidad_sub_descripcion': unidad_sub.descripcion if unidad_sub else '',
        'calendario_codigo': codigo_cal,
        'calendario_descripcion': descripcion_cal,
        'horas_mes': horas_mes,
        'salario_escala': salario,
        'tarifa_horaria': _tarifa_horaria(salario, fondo_tarifa),
        'cnci': contrato.importe_cnci,
        'maestria': contrato.importe_maestria,
        'doctorado': contrato.importe_doctorado,
        'instructor': contrato.importe_instructor,
        'anos_servicio': annos_de_servicio(contrato.fecha_alta_entidad, referencia),
        'fecha_alta_entidad': contrato.fecha_alta_entidad,
    }


def construir_trabajadores(reporte, usuario):
    """Filas de trabajador de la unidad del reporte, sin guardarlas todavía.

    Devuelve instancias sin `pk`; el llamador decide cuándo hacer `bulk_create`,
    para que todo el alta del reporte quepa en una sola transacción.

    `usuario` hace falta para localizar SU Calendario de Pago del período: los
    calendarios son personales, así que las horas del mes son las que definió
    quien crea el reporte.
    """
    horas = horas_del_periodo(usuario, reporte.anno, reporte.mes)
    filas = []
    for orden, contrato in enumerate(contratos_de(reporte.unidad)):
        datos = datos_de_trabajador(contrato,
                                    fondo_tarifa=reporte.fondo_tarifa,
                                    referencia=reporte.fecha_hasta,
                                    horas_por_calendario=horas)
        filas.append(ReporteTrabajador(
            reporte=reporte,
            orden=orden,
            # Un reporte recién creado no tiene ausencias, así que las horas
            # trabajadas son todas las del mes. Sin esto la rejilla enseñaría
            # 0.00 hasta que alguien configurara los conceptos, que es un cero
            # que no significa «no trabajó» sino «aún no se ha calculado».
            horas_trabajadas=datos['horas_mes'],
            **datos))
    return filas
