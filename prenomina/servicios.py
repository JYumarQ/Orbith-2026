"""Transiciones del reporte de pago.

Doctrina literal de `cierres/servicios.py`, que este módulo replica:
**las vistas no escriben estado, solo llaman aquí. Toda transición es
`@transaction.atomic` y bloquea la fila con `select_for_update()`.**

Los errores son `ErrorDePreNomina`, cuyo mensaje en español va directo a la
interfaz; las vistas no componen textos de error por su cuenta.

Ciclo de vida
-------------
    Borrador ──cerrar──> Cerrado ──reabrir──> Borrador
                            │
                            └── al crear el reporte del mes siguiente
                                de esa unidad, pasa a Histórico y ya
                                nadie lo reabre.

La regla la sostienen dos mecanismos que se refuerzan:

* En la base de datos, `UniqueConstraint(['unidad'], condition=Q(estado='B'))`:
  una unidad no puede tener dos borradores a la vez, pase lo que pase.
* Aquí, `crear_reporte()` marca como Histórico el reporte anterior de la unidad
  dentro de la misma transacción.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_auditoria

from . import calculos
from .captura import construir_trabajadores, datos_de_trabajador, datos_de_unidad
from .constantes import FACTOR_TECHO_HORAS, MODULO
from .models import (EstadoReporte, NClaveAusencia, NEscalaAnnosServicio,
                     NPagoHoras, NPagoImporte, Quincena,
                     ReporteConceptoAusencia, ReporteConceptoHoras,
                     ReporteConceptoImporte, ReportePago, ReporteTrabajador,
                     TipoValorImporte, ValorAusencia, ValorHoras, ValorImporte)
from .permisos import gestiona_unidad, puede_escribir

logger = logging.getLogger(__name__)


class ErrorDePreNomina(Exception):
    """Transición o dato no permitido. El mensaje va directo al usuario."""


# --------------------------------------------------------------------------- #
# Período de pago de la entidad
# --------------------------------------------------------------------------- #

def es_pago_quincenal():
    """¿La entidad paga por quincenas? Lo dice Configuración → Parámetros Generales.

    `Configuracion.periodo` guarda los DÍAS del período (15 Quincenal, 30
    Mensual). Se lee aquí y no se copia en el reporte porque es una regla de la
    entidad, no un dato del documento: lo que el reporte congela es la quincena
    que le tocó, que ya no depende de que mañana se cambie el parámetro.

    Sin configuración creada se asume Mensual, que es el comportamiento que
    tenía Pre-Nómina antes de existir este campo.
    """
    from configuracion.models import Configuracion
    configuracion = Configuracion.objects.first()
    if configuracion is None:
        return False
    return configuracion.periodo == Configuracion.PERIODO_QUINCENAL


def limites_del_periodo(anno, mes, quincena):
    """Fechas «desde» y «hasta» que le corresponden a un período de pago.

    Mes completo: del 1 al último día. 1ra quincena: del 1 al 15. 2da quincena:
    del 16 al último día — y no «del 16 al 30», porque febrero existe.

    Es solo la propuesta con la que se rellena el formulario: el usuario puede
    ajustarla antes de crear el reporte.
    """
    import calendar as _calendario
    from datetime import date

    ultimo = _calendario.monthrange(anno, mes)[1]
    if quincena == Quincena.PRIMERA:
        return date(anno, mes, 1), date(anno, mes, 15)
    if quincena == Quincena.SEGUNDA:
        return date(anno, mes, 16), date(anno, mes, ultimo)
    return date(anno, mes, 1), date(anno, mes, ultimo)


def siguiente_quincena(unidad_pk, anno, mes):
    """Qué reporte toca crear para esa unidad y mes, o `None` si ya no falta ninguno.

    La quincena **no la elige el usuario**: se deduce de lo que ya existe. Con
    pago Mensual solo cabe MES_COMPLETO; con pago Quincenal se devuelve la
    primera de las dos que falte, así que el orden natural sale solo y rehacer
    una quincena borrada la vuelve a ofrecer.
    """
    existentes = set(
        ReportePago.objects
        .filter(unidad_id=unidad_pk, anno=anno, mes=mes)
        .values_list('quincena', flat=True))

    if not es_pago_quincenal():
        candidatas = [Quincena.MES_COMPLETO]
    else:
        candidatas = [Quincena.PRIMERA, Quincena.SEGUNDA]

    for candidata in candidatas:
        if candidata not in existentes:
            return candidata
    return None


def _fondo_de_tarifa():
    """Divisor con el que se obtiene la tarifa horaria a partir del salario.

    Sale siempre de Configuración → Parámetros Generales. Dejó de preguntarse en
    el formulario de alta: era un número que el usuario no decidía —siempre
    aceptaba el que se le proponía— y que ya vivía en un solo sitio.

    Se sigue COPIANDO en el reporte (`ReportePago.fondo_tarifa`) en vez de leerlo
    al vuelo: un reporte cerrado tiene que poder recalcularse igual dentro de dos
    años, aunque el parámetro haya cambiado desde entonces.
    """
    from configuracion.models import Configuracion
    configuracion = Configuracion.objects.first()
    if configuracion and configuracion.fondo_tiempo_calc_tarif:
        return configuracion.fondo_tiempo_calc_tarif
    return Decimal('190.60')


# --------------------------------------------------------------------------- #
# Comprobaciones compartidas
# --------------------------------------------------------------------------- #

def _exigir_permiso(usuario, unidad_pk):
    if not puede_escribir(usuario):
        raise ErrorDePreNomina('Su rol solo permite consultar los reportes de pago.')
    if not gestiona_unidad(usuario, unidad_pk):
        raise ErrorDePreNomina(
            'Solo puede gestionar reportes de las Unidades Organizativas que '
            'tenga asignadas.')


def _exigir_borrador(reporte):
    """Primera instrucción de toda función mutadora, ya dentro del bloqueo.

    `permisos.puede_editar()` comprueba lo mismo para decidir qué botones se
    pintan; esta es la que de verdad protege, porque corre con la fila bloqueada
    y no puede quedar obsoleta entre la comprobación y la escritura.
    """
    if reporte.estado != EstadoReporte.BORRADOR:
        raise ErrorDePreNomina(
            f'El reporte está en estado «{reporte.get_estado_display()}» y no '
            f'admite cambios.')


def _auditar(usuario, accion, reporte, descripcion):
    """Auditoría en `try/except`: nunca debe tumbar la transición real.

    Mismo criterio que `auditoria/admin_mixins.py` y `notificaciones/avisos.py`.
    """
    try:
        registrar_auditoria(
            usuario=usuario, accion=accion, instancia=reporte,
            descriptor=descripcion[:200], modulo=MODULO)
    except Exception:
        logger.exception('No se pudo auditar la acción %s sobre el reporte %s.',
                         accion, reporte.pk)


def _nombre_de(usuario):
    completo = (usuario.get_full_name() or '').strip()
    return (completo or usuario.get_username())[:150]


# --------------------------------------------------------------------------- #
# Alta del reporte
# --------------------------------------------------------------------------- #

@transaction.atomic
def crear_reporte(unidad, periodo, usuario, *,
                  fecha_desde, fecha_hasta, hecho_por='', revisado_por='',
                  aprobado_por='', fondo_tiempo=None, plantilla=None,
                  fondo_tarifa=None):
    """Crea el reporte de una unidad para un período y congela sus trabajadores.

    El objeto que se bloquea es la **unidad** y no el reporte, porque el reporte
    todavía no existe. Es el mismo recurso que bloquea
    `cierres.servicios.declarar_actualizada`.

    La QUINCENA se decide aquí dentro, con la unidad ya bloqueada, y no en el
    formulario: es la única forma de que dos usuarios creando a la vez el reporte
    del mismo mes no se peleen por la misma quincena.

    `fondo_tarifa` es opcional y solo lo pasan el panel de administración y los
    tests: el alta normal lo toma de Configuración (`_fondo_de_tarifa()`).
    """
    _exigir_permiso(usuario, unidad.pk)

    # Relectura con bloqueo: dos moderadores pulsando «Crear» a la vez quedan
    # serializados aquí, así que el segundo ve el reporte del primero.
    unidad = (type(unidad).objects.select_for_update()
              .select_related('tipo').get(pk=unidad.pk))

    quincena = siguiente_quincena(unidad.pk, periodo.anno, periodo.mes)
    if quincena is None:
        # Con pago Mensual solo cabía un reporte; con pago Quincenal, dos. En
        # ambos casos significa lo mismo: ese mes ya está cubierto entero.
        if es_pago_quincenal():
            raise ErrorDePreNomina(
                f'{unidad.descripcion} ya tiene las dos quincenas de '
                f'{periodo.etiqueta}.')
        raise ErrorDePreNomina(
            f'Ya existe un reporte de {unidad.descripcion} para '
            f'{periodo.etiqueta}.')

    # Un solo borrador por unidad. Se comprueba aquí para poder decir CUÁL está
    # abierto; la `UniqueConstraint` parcial lo garantiza pase lo que pase.
    abierto = ReportePago.objects.filter(
        unidad=unidad, estado=EstadoReporte.BORRADOR).first()
    if abierto:
        raise ErrorDePreNomina(
            f'{unidad.descripcion} ya tiene el reporte de '
            f'{abierto.etiqueta_periodo} en Borrador. Ciérrelo antes de '
            f'empezar otro.')

    if fecha_hasta < fecha_desde:
        raise ErrorDePreNomina(
            'La fecha final del período no puede ser anterior a la inicial.')

    reporte = ReportePago.objects.create(
        unidad=unidad, anno=periodo.anno, mes=periodo.mes, quincena=quincena,
        estado=EstadoReporte.BORRADOR,
        # Valor de arranque: `_fondo_de_referencia()` lo sustituye unas líneas
        # más abajo, ya con los trabajadores congelados y sus jornadas conocidas.
        fondo_tiempo=fondo_tiempo or Decimal('0.01'),
        fondo_tarifa=fondo_tarifa if fondo_tarifa is not None else _fondo_de_tarifa(),
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        hecho_por=hecho_por or _nombre_de(usuario),
        revisado_por=revisado_por, aprobado_por=aprobado_por,
        **datos_de_unidad(unidad))

    filas = construir_trabajadores(reporte, usuario)
    _exigir_calendarios(filas, periodo)
    _exigir_sin_solape(reporte, [f.no_expediente for f in filas])
    if filas:
        ReporteTrabajador.objects.bulk_create(filas)
    reporte.total_trabajadores = len(filas)
    # «Horas del mes» de la cabecera: la jornada que más se repite en el reporte.
    # Es solo el número de referencia del encabezado del documento; el cálculo de
    # cada trabajador usa SUS propias horas (`ReporteTrabajador.horas_mes`).
    reporte.fondo_tiempo = _fondo_de_referencia(filas) or reporte.fondo_tiempo
    reporte.save(update_fields=['total_trabajadores', 'fondo_tiempo'])

    # Los conceptos salen de la plantilla y se CONGELAN aquí mismo. A partir de
    # este momento el reporte es independiente de ella: editarla después no lo
    # toca. La FK que queda es trazabilidad, no dependencia.
    if plantilla is not None:
        from . import servicios_plantilla
        servicios_plantilla.aplicar_a_reporte(reporte, plantilla, usuario)

    # Los reportes cerrados anteriores de esta unidad pasan a Histórico: ya hay
    # uno posterior, así que dejan de ser reabribles.
    _archivar_anteriores(reporte)

    _auditar(usuario, AccionAuditoria.CREAR, reporte,
             f'Reporte de pago de {reporte.unidad_descripcion} — '
             f'{reporte.etiqueta_periodo} ({len(filas)} trabajadores'
             f'{f", plantilla «{plantilla.descripcion}»" if plantilla else ""})')
    return reporte


def _exigir_calendarios(filas, periodo):
    """Ningún trabajador puede entrar al reporte sin horas del mes definidas.

    Es la puerta que hace real «todo se rige por el calendario». Falla en vez de
    poner un cero porque un cero no se nota: el reporte se crearía, se cerraría y
    alguien cobraría de menos. Con este mensaje, en cambio, el usuario sabe
    exactamente a quién le falta la asignación y dónde arreglarla.

    Cubre los dos motivos por los que un trabajador puede quedarse sin horas —no
    tener jornada asignada, o tenerla pero fuera del Calendario de Pago del
    período— porque desde aquí ambos se ven igual y la solución del usuario es la
    misma: pasar por «Asignar Calendario» o añadir esa jornada al período.
    """
    sin_horas = [fila for fila in filas if not fila.calendario_codigo]
    if not sin_horas:
        return

    nombres = ', '.join(f'{f.nombre_completo} ({f.no_expediente})'
                        for f in sin_horas[:5])
    if len(sin_horas) > 5:
        nombres += f' y {len(sin_horas) - 5} más'
    raise ErrorDePreNomina(
        f'{len(sin_horas)} trabajador{"es" if len(sin_horas) != 1 else ""} no '
        f'tiene{"n" if len(sin_horas) != 1 else ""} horas del mes para '
        f'{periodo.etiqueta}: {nombres}. Asígneles una jornada en Pre-Nómina → '
        f'Asignar Calendario y compruebe que esa jornada está incluida en el '
        f'Calendario de Pago de {periodo.etiqueta}.')


def _fondo_de_referencia(filas):
    """Las «Horas del mes» que se imprimen en la cabecera del documento.

    Con jornadas distintas dentro del mismo reporte ya no existe UN fondo de
    tiempo: cada trabajador tiene el suyo. Para el encabezado del Excel, que es
    una sola casilla, se toma la jornada **más repetida** del reporte, con
    empates resueltos por el código más bajo para que el número no baile entre
    dos ejecuciones iguales.

    Es un dato de presentación: ningún cálculo lo usa.
    """
    from collections import Counter

    conteo = Counter((f.calendario_codigo, f.horas_mes)
                     for f in filas if f.calendario_codigo)
    if not conteo:
        return None
    # `-cuantos` ordena de más a menos repetida; `codigo` desempata al más bajo.
    (_, horas), _ = min(conteo.items(),
                        key=lambda par: (-par[1], par[0][0]))
    return horas


def _exigir_sin_solape(reporte, expedientes):
    """Impide que un trabajador acabe en dos reportes del mismo período.

    Es la contrapartida de que el alcance incluya las subunidades: sin esto,
    crear el reporte de una Dirección Principal cuando ya existe el de una de
    sus hijas pondría a los mismos trabajadores en dos nóminas del mismo mes.
    Se comprueba por expediente y no por unidad porque es el trabajador, no la
    unidad, lo que no puede pagarse dos veces.

    La comparación incluye la QUINCENA. Sin ella esta comprobación bloquearía
    justamente lo que las quincenas vienen a permitir: con pago Quincenal el
    mismo trabajador tiene que aparecer en la 1ra y en la 2da del mismo mes, y
    eso no es un doble pago sino los dos medios pagos de ese mes.
    """
    if not expedientes:
        return

    solapados = (ReporteTrabajador.objects
                 .filter(reporte__anno=reporte.anno, reporte__mes=reporte.mes,
                         reporte__quincena=reporte.quincena,
                         no_expediente__in=expedientes)
                 .exclude(reporte_id=reporte.pk)
                 .select_related('reporte')[:5])
    if not solapados:
        return

    otros = sorted({t.reporte.unidad_descripcion for t in solapados})
    ejemplos = ', '.join(t.no_expediente for t in solapados)
    raise ErrorDePreNomina(
        f'Algunos trabajadores ya están en otro reporte de '
        f'{reporte.etiqueta_periodo}: {ejemplos}. Ese reporte es de '
        f'{", ".join(otros)}. Un trabajador no puede aparecer en dos nóminas '
        f'del mismo período.')


def _archivar_anteriores(reporte):
    """Marca como Histórico los reportes cerrados previos de la misma unidad.

    Se hace por consulta y no recorriendo `es_ultimo` fila a fila: al crear el
    reporte de agosto, todos los cerrados de esa unidad son anteriores por
    definición.

    La quincena desempata dentro del mes, igual que en `es_ultimo`: al crear la
    2da quincena, la 1ra ya cerrada de ese mismo mes pasa a Histórico.
    """
    from django.db.models import Q
    return (ReportePago.objects
            .filter(unidad_id=reporte.unidad_id, estado=EstadoReporte.CERRADO)
            .filter(Q(anno__lt=reporte.anno)
                    | Q(anno=reporte.anno, mes__lt=reporte.mes)
                    | Q(anno=reporte.anno, mes=reporte.mes,
                        quincena__lt=reporte.quincena))
            .update(estado=EstadoReporte.HISTORICO))


# --------------------------------------------------------------------------- #
# Trabajadores
# --------------------------------------------------------------------------- #

@transaction.atomic
def agregar_trabajador(reporte, no_expediente, usuario):
    """Añade (o vuelve a congelar) un trabajador del reporte.

    Los datos se releen SIEMPRE de la `CAlta` viva. Un trabajador no puede
    entrar en un reporte con un salario que alguien haya tecleado: si no hay
    contrato vivo del que copiarlo, la operación se rechaza.
    """
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    from .captura import contratos_de
    contrato = contratos_de(reporte.unidad).filter(
        no_expediente=no_expediente).first()
    if contrato is None:
        raise ErrorDePreNomina(
            f'El expediente {no_expediente} no corresponde a ningún trabajador '
            f'activo de {reporte.unidad_descripcion}.')

    from .captura import horas_del_periodo
    horas_calendario = horas_del_periodo(usuario, reporte.anno, reporte.mes)
    datos = datos_de_trabajador(contrato, fondo_tarifa=reporte.fondo_tarifa,
                                referencia=reporte.fecha_hasta,
                                horas_por_calendario=horas_calendario)
    if not datos['calendario_codigo']:
        raise ErrorDePreNomina(
            f'{datos["nombre_completo"]} no tiene horas del mes para '
            f'{reporte.periodo.etiqueta}. Asígnele una jornada en Pre-Nómina → '
            f'Asignar Calendario y compruebe que esa jornada está incluida en el '
            f'Calendario de Pago de {reporte.periodo.etiqueta}.')

    fila = reporte.trabajadores.filter(no_expediente=no_expediente).first()
    if fila is None:
        _exigir_sin_solape(reporte, [no_expediente])
        siguiente = reporte.trabajadores.count()
        fila = ReporteTrabajador.objects.create(
            reporte=reporte, orden=siguiente, **datos)
        accion, verbo = AccionAuditoria.CREAR, 'añadido a'
    else:
        # Re-congelado: se refresca la fotografía y se conservan los valores ya
        # introducidos. Es el botón «Actualizar datos del trabajador».
        for campo, valor in datos.items():
            setattr(fila, campo, valor)
        fila.save(update_fields=list(datos))
        accion, verbo = AccionAuditoria.MODIFICAR, 'actualizado en'

    # Las filas de valor de los conceptos ya configurados. Sin esto, un
    # trabajador añadido después de configurar el reporte saldría sin celdas y
    # la importación no tendría dónde escribir sus horas.
    ausencias, horas, importes = calculos.cargar_conceptos(reporte)
    _crear_filas_de_valor(reporte, ausencias=ausencias, horas=horas,
                          importes=importes, trabajadores=[fila])
    calculos.recalcular_trabajador(fila, conceptos=(ausencias, horas, importes))

    calculos.refrescar_totales(reporte)

    _auditar(usuario, accion, reporte,
             f'{fila.nombre_completo} ({no_expediente}) {verbo} el reporte '
             f'{reporte.etiqueta_periodo}')
    return fila


@transaction.atomic
def quitar_trabajador(reporte, trabajador_pk, usuario):
    """Saca a un trabajador del reporte, con todos sus valores."""
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    fila = reporte.trabajadores.filter(pk=trabajador_pk).first()
    if fila is None:
        raise ErrorDePreNomina('Ese trabajador no pertenece a este reporte.')

    etiqueta = f'{fila.nombre_completo} ({fila.no_expediente})'
    fila.delete()

    calculos.refrescar_totales(reporte)

    _auditar(usuario, AccionAuditoria.ELIMINAR, reporte,
             f'{etiqueta} retirado del reporte {reporte.etiqueta_periodo}')


# --------------------------------------------------------------------------- #
# Estados
# --------------------------------------------------------------------------- #

@transaction.atomic
def cerrar_reporte(reporte, usuario, *, revisado_por='', aprobado_por=''):
    """Cierra el reporte.

    **No vuelve a capturar nada.** Recalcula los derivados a partir de las
    entradas ya guardadas, escribe los totales y marca el estado. Volver a
    capturar aquí cambiaría en silencio números que el Moderador ya revisó, que
    es el peor fallo posible en un documento de nómina.
    """
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    if not reporte.trabajadores.exists():
        raise ErrorDePreNomina('No se puede cerrar un reporte sin trabajadores.')

    # No se vuelve a capturar NADA de los datos vivos: solo se recalculan los
    # derivados a partir de las entradas ya guardadas. Recapturar aquí cambiaría
    # en silencio números que el Moderador ya revisó.
    calculos.recalcular_reporte(reporte)
    reporte.refresh_from_db()

    reporte.estado = EstadoReporte.CERRADO
    reporte.cerrado_por = usuario
    reporte.cerrado_por_nombre = _nombre_de(usuario)
    reporte.fecha_cierre = timezone.now()
    if revisado_por:
        reporte.revisado_por = revisado_por
    if aprobado_por:
        reporte.aprobado_por = aprobado_por
    reporte.save(update_fields=['estado', 'cerrado_por', 'cerrado_por_nombre',
                                'fecha_cierre', 'revisado_por', 'aprobado_por'])

    sincronizar_calendario(usuario, reporte.anno, reporte.mes)

    _auditar(usuario, AccionAuditoria.MODIFICAR, reporte,
             f'Cerrado el reporte de {reporte.unidad_descripcion} — '
             f'{reporte.etiqueta_periodo}')
    return reporte


def sincronizar_calendario(usuario, anno, mes):
    """Pone el Calendario de Pago del período en el estado que le corresponde.

    La regla es **el mes completo, no la unidad suelta**: el calendario se cierra
    cuando ya no queda ningún reporte en Borrador de ese año+mes dentro del
    alcance del usuario, y se reabre en cuanto vuelve a haber alguno.

    Por eso no basta con cerrar el calendario al cerrar un reporte: un moderador
    con tres unidades cerraría el calendario al cerrar la primera y se quedaría
    sin poder tocar las horas que aún necesitan las otras dos.

    Se llama después de cerrar y de reabrir, y también desde `cerrar_mes()`. Es
    idempotente: recalcula el estado correcto, no lo alterna.
    """
    from . import servicios_calendario
    from .filtros import reportes_visibles

    quedan_abiertos = (reportes_visibles(usuario)
                       .filter(anno=anno, mes=mes, estado=EstadoReporte.BORRADOR)
                       .exists())
    if quedan_abiertos:
        servicios_calendario.reabrir_periodo(
            usuario, anno=anno, mes=mes, reabierto_por=usuario)
    else:
        servicios_calendario.cerrar_periodo(
            usuario, anno=anno, mes=mes, cerrado_por=usuario)


def cerrar_mes(usuario, anno, mes):
    """Cierra de una vez todos los reportes en Borrador de un año+mes.

    Es la acción «Cerrar mes» de Gestión de Reportes de Pagos: con los reportes
    repartidos por unidad, cerrarlos de uno en uno era el trabajo repetitivo que
    esta acción elimina.

    **No es una transacción única a propósito.** Cada reporte se cierra con su
    propia transacción (`cerrar_reporte`), así que uno que no pueda cerrarse —por
    ejemplo, sin trabajadores— no arrastra a los demás. Se devuelve el resumen
    `(cerrados, fallos)` para que la vista pueda decir exactamente qué quedó
    fuera y por qué, en vez de un «no se pudo» sin detalle.
    """
    from .filtros import reportes_visibles

    pendientes = list(reportes_visibles(usuario)
                      .filter(anno=anno, mes=mes, estado=EstadoReporte.BORRADOR)
                      .order_by('unidad_descripcion'))
    if not pendientes:
        raise ErrorDePreNomina(
            'No hay reportes en Borrador para ese período: no queda nada que cerrar.')

    cerrados, fallos = [], []
    for reporte in pendientes:
        try:
            cerrar_reporte(reporte, usuario)
            cerrados.append(reporte)
        except ErrorDePreNomina as error:
            fallos.append((reporte, str(error)))

    # `cerrar_reporte` ya sincroniza en cada vuelta, pero se repite al final por
    # si la lista quedó vacía de cerrados: el estado del calendario debe
    # reflejar la realidad aunque no se haya cerrado ni un reporte.
    sincronizar_calendario(usuario, anno, mes)
    return cerrados, fallos


@transaction.atomic
def reabrir_reporte(reporte, usuario):
    """Devuelve a Borrador un reporte cerrado.

    Solo si sigue siendo el **último** de su unidad. En cuanto se crea el
    reporte del mes siguiente, éste pasa a Histórico y queda bloqueado para
    siempre: reabrir un mes ya superado significaría cambiar una nómina que
    arrastra a las posteriores.
    """
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)

    if reporte.estado == EstadoReporte.BORRADOR:
        raise ErrorDePreNomina('El reporte ya está en Borrador.')
    if reporte.estado == EstadoReporte.HISTORICO:
        raise ErrorDePreNomina(
            'El reporte es histórico: ya existe un reporte posterior de esta '
            'unidad, así que no puede reabrirse.')
    if not reporte.es_ultimo:
        raise ErrorDePreNomina(
            'Existe un reporte posterior de esta unidad. Solo puede reabrirse '
            'el último.')

    reporte.estado = EstadoReporte.BORRADOR
    reporte.cerrado_por = None
    reporte.cerrado_por_nombre = ''
    reporte.fecha_cierre = None
    reporte.save(update_fields=['estado', 'cerrado_por', 'cerrado_por_nombre',
                                'fecha_cierre'])

    sincronizar_calendario(usuario, reporte.anno, reporte.mes)

    _auditar(usuario, AccionAuditoria.MODIFICAR, reporte,
             f'Reabierto el reporte de {reporte.unidad_descripcion} — '
             f'{reporte.etiqueta_periodo}')
    return reporte


# --------------------------------------------------------------------------- #
# Conceptos del reporte
# --------------------------------------------------------------------------- #

def _crear_filas_de_valor(reporte, *, ausencias=None, horas=None, importes=None,
                          trabajadores=None):
    """Crea las filas de valor que falten, todas a cero.

    Las filas son **densas, no dispersas**: existe una por cada par
    (trabajador × concepto). Cuesta un `bulk_create` de unos cientos de filas
    una vez al mes, y a cambio cada celda tiene identidad estable para el modal,
    la exportación y la importación, que así no tienen que decidir si crear o
    actualizar celda a celda.
    """
    trabajadores = (list(reporte.trabajadores.all()) if trabajadores is None
                    else trabajadores)
    if not trabajadores:
        return

    for modelo, conceptos, campo in (
        (ValorAusencia, ausencias, 'valores_ausencia'),
        (ValorHoras, horas, 'valores_horas'),
        (ValorImporte, importes, 'valores_importe'),
    ):
        if not conceptos:
            continue
        existentes = set(
            modelo.objects.filter(trabajador__reporte=reporte)
            .values_list('trabajador_id', 'concepto_id'))
        nuevas = [modelo(trabajador=trabajador, concepto=concepto)
                  for trabajador in trabajadores
                  for concepto in conceptos
                  if (trabajador.pk, concepto.pk) not in existentes]
        if nuevas:
            modelo.objects.bulk_create(nuevas)


@transaction.atomic
def configurar_conceptos(reporte, usuario, *, codigos_ausencia=(),
                         codigos_horas=(), codigos_importe=()):
    """Congela en el reporte los conceptos que se van a utilizar.

    Se puede reejecutar sobre un Borrador para cambiar la selección. Devuelve un
    resumen de lo que cambió, para poder enseñárselo al usuario.

    Tres reglas que conviene tener claras:

    * Los pagos por importe **relacionados** con un concepto por horas
      seleccionado entran solos (`automatico=True`) y no hace falta pedirlos.
      Pedirlos a mano además se ignora, no da error: es la misma intención.
    * Un concepto por horas es **derivado** si alguna ausencia seleccionada
      apunta a él. Sus valores dejan de ser editables y pasan a calcularse.
    * Quitar un concepto borra sus valores. Es una acción del reporte, y por eso
      el resumen dice cuántos valores se van a perder.
    """
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    codigos_ausencia = {int(c) for c in codigos_ausencia}
    codigos_horas = {int(c) for c in codigos_horas}
    codigos_importe = {int(c) for c in codigos_importe}

    claves = {c.codigo: c for c in
              NClaveAusencia.objects.filter(codigo__in=codigos_ausencia)
              .select_related('relacionado_con')}
    pagos_horas = {p.codigo: p for p in
                   NPagoHoras.objects.filter(codigo__in=codigos_horas)}

    _exigir_existencia(codigos_ausencia, claves, 'clave de ausencia')
    _exigir_existencia(codigos_horas, pagos_horas, 'pago asociado por horas')

    # Un concepto por horas al que apunte una ausencia seleccionada tiene que
    # estar en el reporte: si no, esas horas no tendrían dónde reflejarse.
    for clave in claves.values():
        destino = clave.relacionado_con
        if destino and destino.codigo not in pagos_horas:
            raise ErrorDePreNomina(
                f'La clave «{clave.etiqueta}» alimenta el concepto '
                f'«{destino.etiqueta}», así que ese concepto por horas también '
                f'debe estar seleccionado.')

    # Los importes relacionados con un concepto por horas seleccionado entran
    # automáticamente; el resto son los que pidió el Moderador.
    automaticos = {p.codigo: p for p in
                   NPagoImporte.objects.filter(
                       relacionado_con__codigo__in=codigos_horas)
                   .select_related('relacionado_con')}
    manuales = {p.codigo: p for p in
                NPagoImporte.objects.filter(codigo__in=codigos_importe)
                .exclude(codigo__in=automaticos)
                .select_related('relacionado_con')}
    _exigir_existencia(codigos_importe - set(automaticos), manuales,
                       'pago asociado por importe')

    # Un importe manual cuya fórmula use {{horas}} necesita su concepto por
    # horas dentro del reporte, o la fórmula se evaluaría siempre con cero.
    for pago in manuales.values():
        if pago.relacionado_con and pago.relacionado_con.codigo not in pagos_horas:
            raise ErrorDePreNomina(
                f'El importe «{pago.etiqueta}» toma las horas de '
                f'«{pago.relacionado_con.etiqueta}», que no está seleccionado.')

    derivados = {clave.relacionado_con.codigo for clave in claves.values()
                 if clave.relacionado_con}

    resumen = _sincronizar_conceptos(reporte, claves, pagos_horas,
                                     automaticos, manuales, derivados)

    calculos.recalcular_reporte(reporte)

    _auditar(usuario, AccionAuditoria.MODIFICAR, reporte,
             f'Conceptos del reporte {reporte.etiqueta_periodo}: '
             f'{len(claves)} ausencias, {len(pagos_horas)} por horas, '
             f'{len(automaticos) + len(manuales)} por importe')
    return resumen


def _exigir_existencia(codigos, encontrados, etiqueta):
    faltan = sorted(set(codigos) - set(encontrados))
    if faltan:
        raise ErrorDePreNomina(
            f'No existe ninguna {etiqueta} con el código '
            f'{", ".join(str(c) for c in faltan)}.')


def _sincronizar_conceptos(reporte, claves, pagos_horas, automaticos, manuales,
                           derivados):
    """Aplica la selección: borra lo que sobra, crea lo que falta, actualiza el resto."""
    resumen = {'valores_perdidos': 0, 'columnas_derivadas': sorted(derivados)}

    # --- Conceptos por horas. Primero, porque las ausencias y los importes
    #     apuntan a sus filas.
    sobran = reporte.conceptos_horas.exclude(codigo__in=pagos_horas)
    resumen['valores_perdidos'] += ValorHoras.objects.filter(
        concepto__in=sobran).exclude(horas=0).count()
    sobran.delete()

    filas_horas = {}
    for orden, codigo in enumerate(sorted(pagos_horas)):
        pago = pagos_horas[codigo]
        fila, _ = ReporteConceptoHoras.objects.update_or_create(
            reporte=reporte, codigo=codigo,
            defaults={'pago_id_original': pago.pk,
                      'descripcion': pago.descripcion,
                      'orden': orden,
                      'es_derivado': codigo in derivados})
        filas_horas[codigo] = fila

    # --- Claves de ausencia.
    sobran = reporte.conceptos_ausencia.exclude(codigo__in=claves)
    resumen['valores_perdidos'] += ValorAusencia.objects.filter(
        concepto__in=sobran).exclude(horas=0).count()
    sobran.delete()

    for orden, codigo in enumerate(sorted(claves)):
        clave = claves[codigo]
        destino = clave.relacionado_con
        ReporteConceptoAusencia.objects.update_or_create(
            reporte=reporte, codigo=codigo,
            defaults={'clave_id_original': clave.pk,
                      'descripcion': clave.descripcion,
                      'orden': orden,
                      'resta_horas_mes': clave.resta_horas_mes,
                      'resta_sistema_pago': clave.resta_sistema_pago,
                      'resta_utilidades': clave.resta_utilidades,
                      'relacionado_con': filas_horas.get(destino.codigo) if destino else None,
                      'relacionado_con_codigo': destino.codigo if destino else None})

    # --- Pagos por importe.
    todos_importes = {**automaticos, **manuales}
    sobran = reporte.conceptos_importe.exclude(codigo__in=todos_importes)
    resumen['valores_perdidos'] += ValorImporte.objects.filter(
        concepto__in=sobran).exclude(importe=0).count()
    sobran.delete()

    escala = NEscalaAnnosServicio.como_diccionario()
    for orden, codigo in enumerate(sorted(todos_importes)):
        pago = todos_importes[codigo]
        destino = pago.relacionado_con
        ReporteConceptoImporte.objects.update_or_create(
            reporte=reporte, codigo=codigo,
            defaults={'pago_id_original': pago.pk,
                      'descripcion': pago.descripcion,
                      'orden': orden,
                      'tipo_valor': pago.tipo_valor,
                      'importe_fijo': pago.importe_fijo,
                      'formula': pago.formula,
                      # La escala se congela entera: si cambia el nomenclador,
                      # este reporte sigue pagando lo que pagaba.
                      'escala_congelada': (
                          escala if pago.tipo_valor == TipoValorImporte.ESCALA else {}),
                      'relacionado_con': filas_horas.get(destino.codigo) if destino else None,
                      'relacionado_con_codigo': destino.codigo if destino else None,
                      'automatico': codigo in automaticos})

    ausencias, horas, importes = calculos.cargar_conceptos(reporte)
    _crear_filas_de_valor(reporte, ausencias=ausencias, horas=horas,
                          importes=importes)

    resumen.update({'ausencias': len(ausencias), 'horas': len(horas),
                    'importes': len(importes)})
    return resumen


# --------------------------------------------------------------------------- #
# Captura de valores
# --------------------------------------------------------------------------- #

@transaction.atomic
def guardar_valores(trabajador_pk, usuario, *, ausencias=None, horas=None):
    """Guarda las horas de una fila y recalcula solo esa fila.

    Se bloquea **la fila del trabajador**, no el reporte. Es la decisión de
    concurrencia más delicada del módulo: bloquear el reporte serializaría todos
    los guardados de esa unidad, y no hace falta, porque las horas derivadas y
    los importes son estrictamente por trabajador. El único estado compartido
    son los tres totales de cabecera, que se refrescan con un `aggregate()` en
    vez de con `+=`, así que no puede perderse una actualización.
    """
    trabajador = (ReporteTrabajador.objects.select_for_update()
                  .select_related('reporte').get(pk=trabajador_pk))
    reporte = trabajador.reporte
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    conceptos = calculos.cargar_conceptos(reporte)
    conceptos_ausencia, conceptos_horas, _ = conceptos

    ausencias = _normalizar(ausencias, trabajador, 'ausencia')
    horas = _normalizar(horas, trabajador, 'pago por horas')

    validos = {c.codigo for c in conceptos_ausencia}
    _exigir_conocidos(ausencias, validos, 'clave de ausencia')

    # Los conceptos derivados no se aceptan aunque lleguen: su valor ES la suma
    # de las ausencias que los alimentan, y permitir que diverjan metería en el
    # documento una contradicción que él mismo no puede explicar.
    editables = {c.codigo for c in conceptos_horas if not c.es_derivado}
    derivados = {c.codigo for c in conceptos_horas if c.es_derivado}
    intrusos = set(horas) & derivados
    if intrusos:
        nombres = ', '.join(
            c.etiqueta for c in conceptos_horas if c.codigo in intrusos)
        raise ErrorDePreNomina(
            f'Los conceptos «{nombres}» se calculan a partir de las ausencias '
            f'relacionadas y no se pueden escribir a mano.')
    _exigir_conocidos(horas, editables, 'pago asociado por horas')

    # Las horas de ausencia que restan no pueden pasarse del fondo del mes: si
    # no, las horas trabajadas saldrían negativas.
    descontadas = calculos.horas_descontadas(ausencias, conceptos_ausencia)
    if descontadas > trabajador.horas_mes:
        raise ErrorDePreNomina(
            f'Las horas de ausencia ({descontadas}) superan las horas del mes '
            f'de {trabajador.nombre_completo} ({trabajador.horas_mes}, jornada '
            f'{trabajador.calendario_descripcion or "sin asignar"}). Las horas '
            f'trabajadas no pueden ser negativas.')

    _escribir_valores(trabajador, ValorAusencia, 'valores_ausencia', ausencias)
    _escribir_valores(trabajador, ValorHoras, 'valores_horas', horas)

    calculos.recalcular_trabajador(trabajador, conceptos=conceptos)
    calculos.refrescar_totales(reporte)

    _auditar(usuario, AccionAuditoria.MODIFICAR, reporte,
             f'Valores de {trabajador.nombre_completo} ({trabajador.no_expediente}) '
             f'en el reporte {reporte.etiqueta_periodo}')
    return trabajador


def _normalizar(valores, trabajador, etiqueta):
    """Convierte a `Decimal` y rechaza negativos y disparates.

    El techo (`horas del mes × 3`) atrapa el error real y frecuente: teclear las
    horas del mes en la casilla de un concepto. Sin él, un 184 en «Horas Extra»
    pasa desapercibido hasta que alguien mira la nómina.

    El techo se calcula sobre las horas **de este trabajador** y no sobre un
    número único del reporte: con jornadas distintas, el techo de quien trabaja
    media jornada tiene que ser más bajo que el de quien trabaja completa.
    """
    from decimal import Decimal, InvalidOperation

    resultado = {}
    techo = trabajador.horas_mes * FACTOR_TECHO_HORAS
    for codigo, bruto in (valores or {}).items():
        try:
            valor = Decimal(str(bruto or 0))
        except (InvalidOperation, ValueError, TypeError):
            raise ErrorDePreNomina(
                f'«{bruto}» no es un número válido de horas.')
        if valor < 0:
            raise ErrorDePreNomina(
                f'Las horas de {etiqueta} no pueden ser negativas.')
        if valor > techo:
            raise ErrorDePreNomina(
                f'{valor} horas superan con mucho las horas del mes '
                f'({trabajador.horas_mes}). Revise el valor.')
        resultado[int(codigo)] = valor.quantize(Decimal('0.01'))
    return resultado


def _exigir_conocidos(valores, validos, etiqueta):
    desconocidos = sorted(set(valores) - validos)
    if desconocidos:
        raise ErrorDePreNomina(
            f'El reporte no incluye ninguna {etiqueta} con el código '
            f'{", ".join(str(c) for c in desconocidos)}.')


def _escribir_valores(trabajador, modelo, relacion, valores):
    if not valores:
        return
    filas = list(getattr(trabajador, relacion).select_related('concepto'))
    cambiadas = []
    for fila in filas:
        if fila.concepto.codigo in valores:
            nuevo = valores[fila.concepto.codigo]
            if fila.horas != nuevo:
                fila.horas = nuevo
                cambiadas.append(fila)
    if cambiadas:
        modelo.objects.bulk_update(cambiadas, ['horas'])


# --------------------------------------------------------------------------- #
# Importacion
# --------------------------------------------------------------------------- #

@transaction.atomic
def importar_valores(reporte, filas, usuario):
    """Escribe las filas ya validadas. Todo o nada.

    El análisis (`importar.analizar`) corre FUERA de transacción porque es largo
    y de solo lectura: mantener bloqueada la cabecera mientras se recorre un
    libro de 500 filas sería absurdo. Aquí dentro, con la cabecera bloqueada, se
    **reafirma** lo que se validó fuera: entre el análisis y este momento otro
    moderador pudo cerrar el reporte o quitar un trabajador.

    Validar largo y barato fuera; reafirmar y escribir corto dentro.
    """
    reporte = ReportePago.objects.select_for_update().get(pk=reporte.pk)
    _exigir_permiso(usuario, reporte.unidad_id)
    _exigir_borrador(reporte)

    presentes = set(reporte.trabajadores.values_list('pk', flat=True))
    ausentes = [f.no_expediente for f in filas if f.trabajador_pk not in presentes]
    if ausentes:
        raise ErrorDePreNomina(
            f'El reporte cambió mientras se analizaba el archivo: ya no contiene '
            f'a {", ".join(ausentes[:5])}. Vuelva a exportarlo.')

    conceptos = calculos.cargar_conceptos(reporte)
    trabajadores = {t.pk: t for t in reporte.trabajadores.all()}

    for fila in filas:
        trabajador = trabajadores[fila.trabajador_pk]
        _escribir_valores(trabajador, ValorAusencia, 'valores_ausencia',
                          fila.ausencias)
        _escribir_valores(trabajador, ValorHoras, 'valores_horas', fila.horas)
        calculos.recalcular_trabajador(trabajador, conceptos=conceptos)

    calculos.refrescar_totales(reporte)

    _auditar(usuario, AccionAuditoria.MODIFICAR, reporte,
             f'Importadas {len(filas)} filas en el reporte '
             f'{reporte.etiqueta_periodo} de {reporte.unidad_descripcion}')
    return {'filas': len(filas)}
