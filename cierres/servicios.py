"""Máquina de estados de los cierres. Único sitio que declara, reabre o recalcula.

Mismo criterio que `solicitudes/servicios.py`: las vistas no escriben estado, solo
llaman aquí. Toda transición es `@transaction.atomic` y bloquea la unidad con
`select_for_update()` — dos moderadores de la misma unidad pulsando «Declarar» a
la vez producirían dos fotografías del mismo período, y la constraint de base de
datos lo rechazaría con un error feo en vez de con un mensaje en español.

El estado de una unidad **se deriva**, no se guarda: lo calcula `calcular_estado()`
a partir de sus cierres y de la fecha. `EstadoCierreUnidad` es solo la
materialización de ese cálculo, para poder listar y filtrar en SQL.
"""

import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_auditoria
from strorganizativa.models import UnidadOrganizativa

from . import captura, periodos
from .constantes import DIA_FIN_VENTANA, DIA_INICIO_VENTANA
from .models import CierreUnidad, EstadoCierreUnidad, EstadoUnidad
from .periodos import Periodo

logger = logging.getLogger(__name__)

MODULO = 'cierres'


class ErrorDeCierre(Exception):
    """Transición no permitida. El mensaje va directo al usuario, en español."""


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------

def ultimo_periodo_cerrado(unidad):
    """El período más reciente que la unidad tiene cerrado, o None si nunca declaró."""
    fila = (CierreUnidad.objects
            .filter(unidad=unidad)
            .order_by('-anno', '-mes')
            .values('anno', 'mes')
            .first())
    return Periodo(fila['anno'], fila['mes']) if fila else None


def calcular_estado(unidad, hoy=None):
    """Deriva el estado de la unidad. **Fuente de verdad del módulo.**

    Devuelve un diccionario, no toca la base de datos más allá de leer los
    cierres. `refrescar_estado()` es quien lo materializa.
    """
    hoy = hoy or date.today()
    ultimo = ultimo_periodo_cerrado(unidad)
    pendientes = periodos.periodos_pendientes(ultimo, hoy)

    if ultimo is None:
        # Sin primera declaración no hay obligación (regla 4): la unidad aparece
        # como Pendiente, pero no se le reclama ningún mes anterior.
        estado = EstadoUnidad.PENDIENTE
    elif not pendientes:
        estado = EstadoUnidad.ACTUALIZADA
    elif len(pendientes) == 1 and pendientes[0] == periodos.periodo_de(hoy) \
            and periodos.en_ventana(hoy):
        # Está dentro de su ventana y aún puede declarar: no es un incumplimiento.
        estado = EstadoUnidad.PENDIENTE
    else:
        estado = EstadoUnidad.DESACTUALIZADA

    return {
        'estado': estado,
        'ultimo_cerrado': ultimo,
        'pendientes': pendientes,
        'periodo_pendiente': pendientes[0] if pendientes else None,
        'declarable': periodos.periodo_declarable(ultimo, hoy),
    }


def _cierre_de(unidad, periodo):
    return CierreUnidad.objects.filter(
        unidad=unidad, anno=periodo.anno, mes=periodo.mes).first()


# --------------------------------------------------------------------------
# Materialización del estado
# --------------------------------------------------------------------------

def refrescar_estado(unidad, hoy=None):
    """Recalcula y guarda `EstadoCierreUnidad`. Idempotente."""
    calculo = calcular_estado(unidad, hoy)
    pendiente = calculo['periodo_pendiente']

    primero = (CierreUnidad.objects.filter(unidad=unidad)
               .order_by('anno', 'mes').first())
    ultimo = (CierreUnidad.objects.filter(unidad=unidad)
              .order_by('-anno', '-mes').first())

    fila, _ = EstadoCierreUnidad.objects.update_or_create(
        unidad=unidad,
        defaults={
            'estado': calculo['estado'],
            'primer_cierre': primero,
            'ultimo_cierre': ultimo,
            'periodo_pendiente_anno': pendiente.anno if pendiente else None,
            'periodo_pendiente_mes': pendiente.mes if pendiente else None,
            'meses_pendientes': len(calculo['pendientes']),
            'fecha_calculo': timezone.now(),
        },
    )
    return fila


def refrescar_todos(hoy=None):
    """Recalcula el estado de todas las unidades.

    Devuelve el reparto por estado para que quien lo invoque pueda resumirlo.
    """
    resumen = {'actualizadas': 0, 'pendientes': 0, 'desactualizadas': 0}
    etiquetas = {
        EstadoUnidad.ACTUALIZADA: 'actualizadas',
        EstadoUnidad.PENDIENTE: 'pendientes',
        EstadoUnidad.DESACTUALIZADA: 'desactualizadas',
    }
    for unidad in UnidadOrganizativa.objects.select_related('tipo').iterator():
        fila = refrescar_estado(unidad, hoy)
        resumen[etiquetas[fila.estado]] += 1
    return resumen


@transaction.atomic
def procesar_barrido(usuario=None, hoy=None):
    """Recalcula el estado de todas las unidades y emite los avisos del día.

    Es una **acción manual del Administrador**, no una tarea programada: se lanza
    desde la pantalla de Cierres cuando corresponda. Deliberadamente idempotente,
    porque un botón se pulsa dos veces con facilidad — los estados se recalculan
    desde cero y los avisos se deduplican por (unidad, código, período).

    No toca ningún dato de negocio: solo `EstadoCierreUnidad` y `Notificacion`.
    """
    from . import avisos
    from .constantes import DIA_FIN_VENTANA, DIAS_AVISO_FINAL
    from .permisos import es_principal

    hoy = hoy or date.today()
    estados = refrescar_todos(hoy)
    emitidos = {'plazo': 0, 'ultimo_dia': 0, 'desactualizadas': 0, 'sin_destinatario': 0}

    unidades = (UnidadOrganizativa.objects
                .select_related('estado_cierre', 'tipo')
                .filter(estado_cierre__isnull=False))

    for unidad in unidades:
        estado = unidad.estado_cierre

        # Las Direcciones Principales no declaran (su estado se deriva de sus
        # hijas), así que nunca tienen nada pendiente que sea suyo. Sin este
        # filtro, `refrescar_todos()` las deja para siempre en "nunca
        # declarada" — correcto en los datos, pero avisarles «declare su
        # unidad» sería reclamarle algo que estructuralmente no puede hacer.
        if es_principal(unidad):
            continue

        # Sin primera declaración no hay obligación, así que tampoco aviso:
        # reclamarle un cierre a una unidad recién creada sería ruido (regla 4).
        if estado.nunca_declarada:
            continue

        periodo = estado.periodo_pendiente
        if periodo is None:
            continue

        if estado.estado == EstadoUnidad.DESACTUALIZADA:
            enviados = avisos.avisar_desactualizada(
                unidad, periodo, estado.meses_pendientes)
            clave = 'desactualizadas'
        elif estado.estado == EstadoUnidad.PENDIENTE and periodos.en_ventana(hoy):
            if hoy.day >= DIA_FIN_VENTANA - DIAS_AVISO_FINAL:
                enviados = avisos.avisar_ultimo_dia(unidad, periodo, hoy)
                clave = 'ultimo_dia'
            else:
                enviados = avisos.avisar_ventana_abierta(unidad, periodo, hoy)
                clave = 'plazo'
        else:
            continue

        if enviados:
            emitidos[clave] += 1
        else:
            emitidos['sin_destinatario'] += 1

    resumen = {'estados': estados, 'avisos': emitidos, 'fecha': hoy}

    if usuario is not None:
        registrar_auditoria(
            usuario=usuario,
            accion=AccionAuditoria.MODIFICAR,
            content_type=_content_type_cierre(),
            modulo=MODULO,
            descriptor=f'Procesamiento manual de cierres — {hoy:%d/%m/%Y}',
            datos_despues={
                'estados': estados,
                'avisos_emitidos': emitidos,
            },
        )

    return resumen


# --------------------------------------------------------------------------
# Transiciones
# --------------------------------------------------------------------------

@transaction.atomic
def declarar_actualizada(unidad, usuario, hoy=None):
    """Declara la unidad actualizada y congela su fotografía.

    Cierra el período **más antiguo** que tenga pendiente, no el mes en curso: la
    cola es FIFO y no se puede saltar un mes (regla 8). Si al terminar todavía
    arrastra meses, la unidad sigue Desactualizada.
    """
    hoy = hoy or date.today()
    unidad = UnidadOrganizativa.objects.select_for_update().select_related('tipo').get(pk=unidad.pk)

    from . import permisos
    if permisos.es_principal(unidad):
        raise ErrorDeCierre(permisos.MENSAJE_ES_PRINCIPAL)
    if not permisos.puede_declarar(usuario, unidad):
        raise ErrorDeCierre(
            'Solo puede declarar Unidades Organizativas que tenga asignadas.')

    ultimo = ultimo_periodo_cerrado(unidad)
    periodo = periodos.periodo_declarable(ultimo, hoy)

    if periodo is None:
        if ultimo is not None and ultimo >= periodos.periodo_de(hoy):
            raise ErrorDeCierre(
                f'La unidad ya declaró el cierre de {ultimo.etiqueta}. '
                'El próximo ciclo comienza el mes que viene.')
        raise ErrorDeCierre(
            f'La declaración solo puede realizarse a partir del día '
            f'{DIA_INICIO_VENTANA} de cada mes.')

    # Redeclaración: se reemplaza la fotografía anterior por completo (regla 11).
    # La cabecera se conserva para no perder el id, pero sus filas se rehacen.
    cierre = _cierre_de(unidad, periodo)
    es_redeclaracion = cierre is not None
    if es_redeclaracion:
        cierre.cargos.all().delete()
        cierre.contratos.all().delete()
    else:
        cierre = CierreUnidad(unidad=unidad, anno=periodo.anno, mes=periodo.mes)

    nombre = ''
    if usuario is not None:
        nombre = usuario.get_full_name() or usuario.username

    cierre.declarado_por = usuario
    cierre.declarado_por_nombre = nombre
    cierre.fecha_declaracion = timezone.now()
    cierre.en_plazo = periodos.fue_en_plazo(periodo, hoy)
    for campo, valor in captura.datos_de_unidad(unidad).items():
        setattr(cierre, campo, valor)
    cierre.save()

    totales = captura.construir_fotografia(cierre)
    for campo, valor in totales.items():
        setattr(cierre, campo, valor)
    cierre.save(update_fields=list(totales.keys()))

    estado = refrescar_estado(unidad, hoy)

    registrar_auditoria(
        usuario=usuario,
        accion=AccionAuditoria.MODIFICAR if es_redeclaracion else AccionAuditoria.CREAR,
        instancia=cierre,
        unidad=unidad,
        modulo=MODULO,
        descriptor=(f'Cierre de {periodo.etiqueta} — {unidad.descripcion} '
                    f'({cierre.estado_plazo})'),
        datos_despues={
            'periodo': periodo.clave,
            'en_plazo': cierre.en_plazo,
            'redeclaracion': es_redeclaracion,
            'estado_resultante': estado.get_estado_display(),
            'meses_pendientes': estado.meses_pendientes,
            **totales,
        },
    )

    from . import avisos
    avisos.avisar_declaracion(cierre, estado)

    return cierre


@transaction.atomic
def reabrir(unidad, usuario, hoy=None):
    """Devuelve la unidad a Pendiente para corregir datos y volver a declarar.

    Solo el cierre del mes en curso y solo dentro de la ventana: pasado el día 25
    el cierre es definitivo y los cambios pertenecen ya al mes siguiente
    (regla 10). Borra la fotografía —el requisito acepta explícitamente perderla
    al ser reemplazada— pero deja el hecho registrado en Auditoría con sus
    totales, para que se pueda demostrar qué se descartó.
    """
    hoy = hoy or date.today()
    unidad = UnidadOrganizativa.objects.select_for_update().select_related('tipo').get(pk=unidad.pk)

    from . import permisos
    if permisos.es_principal(unidad):
        raise ErrorDeCierre(permisos.MENSAJE_ES_PRINCIPAL)
    if not permisos.puede_declarar(usuario, unidad):
        raise ErrorDeCierre(
            'Solo puede modificar Unidades Organizativas que tenga asignadas.')

    actual = periodos.periodo_de(hoy)
    cierre = _cierre_de(unidad, actual)
    if cierre is None:
        raise ErrorDeCierre(
            f'La unidad no tiene declarado el cierre de {actual.etiqueta}.')

    if not periodos.puede_reabrirse(actual, hoy):
        raise ErrorDeCierre(
            f'El cierre de {actual.etiqueta} ya no puede reabrirse: el plazo '
            f'terminó el día {DIA_FIN_VENTANA}. Cualquier cambio que '
            'haga ahora pertenece al mes siguiente.')

    datos_antes = {
        'periodo': actual.clave,
        'declarado_por': cierre.declarado_por_nombre,
        'fecha_declaracion': cierre.fecha_declaracion.isoformat() if cierre.fecha_declaracion else None,
        'total_cargos': cierre.total_cargos,
        'total_plazas_aprobadas': cierre.total_plazas_aprobadas,
        'total_plazas_cubiertas': cierre.total_plazas_cubiertas,
        'total_contratos': cierre.total_contratos,
    }
    cierre_id = cierre.pk
    cierre.delete()

    estado = refrescar_estado(unidad, hoy)

    registrar_auditoria(
        usuario=usuario,
        accion=AccionAuditoria.DEVOLVER_A_ESPERA,
        content_type=_content_type_cierre(),
        object_id=cierre_id,
        unidad=unidad,
        modulo=MODULO,
        descriptor=(f'Reapertura del cierre de {actual.etiqueta} — '
                    f'{unidad.descripcion}'),
        datos_antes=datos_antes,
        datos_despues={'estado_resultante': estado.get_estado_display()},
    )

    return estado


def _content_type_cierre():
    from django.contrib.contenttypes.models import ContentType
    return ContentType.objects.get_for_model(CierreUnidad)


# --------------------------------------------------------------------------
# Consultas para informes
# --------------------------------------------------------------------------

def periodos_disponibles():
    """Períodos que tienen al menos un cierre. Ordenados del más reciente al más
    antiguo, para que el selector de los informes no ofrezca meses inexistentes
    (regla 18)."""
    filas = (CierreUnidad.objects
             .values('anno', 'mes')
             .distinct()
             .order_by('-anno', '-mes'))
    return [Periodo(f['anno'], f['mes']) for f in filas]


def unidades_sin_cierre(periodo, unidades_ids=None):
    """Unidades que deberían tener cierre en ese período y no lo tienen.

    «Deberían» significa: ya habían hecho su primera declaración en ese momento.
    Una unidad creada en octubre no se reclama en el informe de agosto.
    """
    con_cierre = set(CierreUnidad.objects
                     .filter(anno=periodo.anno, mes=periodo.mes)
                     .values_list('unidad_id', flat=True))

    candidatas = UnidadOrganizativa.objects.all()
    if unidades_ids:
        candidatas = candidatas.filter(pk__in=unidades_ids)

    faltantes = []
    for unidad in candidatas.exclude(pk__in=con_cierre):
        primero = (CierreUnidad.objects.filter(unidad=unidad)
                   .order_by('anno', 'mes')
                   .values('anno', 'mes').first())
        if primero and Periodo(primero['anno'], primero['mes']) <= periodo:
            faltantes.append(unidad.descripcion)
    return sorted(faltantes)
