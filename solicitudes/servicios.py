"""Máquina de estados de una solicitud. Único sitio que cambia `estado`.

Las vistas no mutan solicitudes: llaman aquí. El motivo es que casi todas las
transiciones tienen que comprobar permisos, verificar que el estado de partida sigue
siendo el esperado y avisar a alguien — y esas tres cosas repartidas por las vistas
acaban divergiendo. Concentradas aquí se pueden leer juntas y probar sin HTTP.

Dos garantías que se mantienen en todas las transiciones:

* **`transaction.atomic()` + `select_for_update()`.** Dos administradores pulsando
  «Revisar» a la vez, o aprobando a la vez, se serializan: el segundo lee el estado que
  dejó el primero y falla con un mensaje claro en vez de pisarlo.
* **Los permisos se comprueban aquí, no solo en la vista.** La vista decide qué botones
  pinta; esto decide qué se puede hacer de verdad.
"""

from django.db import transaction
from django.utils import timezone

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar as registrar_auditoria
from solicitudes import avisos
from solicitudes.models import AccionSolicitud, EstadoSolicitud, Solicitud
from solicitudes.operaciones import (
    definicion_de, ejecutar, form_de_aprobacion, form_kwargs_de, preparar_ejecucion)

#: AccionSolicitud y AccionAuditoria comparten valores (ADD/UPD/DEL) para CREAR/
#: EDITAR/ELIMINAR, así que el mapeo es directo salvo por el nombre distinto de EDITAR.
_ACCION_AUDITORIA_DE = {
    AccionSolicitud.CREAR: AccionAuditoria.CREAR,
    AccionSolicitud.EDITAR: AccionAuditoria.MODIFICAR,
    AccionSolicitud.ELIMINAR: AccionAuditoria.ELIMINAR,
}


class ErrorDeSolicitud(Exception):
    """Operación no permitida o imposible. El mensaje se muestra tal cual al usuario,
    así que se escribe en español y sin jerga técnica."""


class PropuestaInvalida(ErrorDeSolicitud):
    """Los valores con los que se intenta aprobar no pasan la validación.

    Lleva el formulario para que la vista pueda repintar la pantalla de revisión con los
    errores en su sitio, en vez de un mensaje suelto que no dice qué campo corregir.
    """

    def __init__(self, formulario):
        self.formulario = formulario
        super().__init__('Revise los campos marcados en la propuesta.')


def _bloquear(solicitud):
    """Recarga la solicitud con la fila bloqueada en base de datos.

    Se relee a propósito en vez de usar la instancia que traía la vista: entre que se
    pintó la pantalla y llegó el POST, otra persona pudo revisarla o decidirla.
    """
    return Solicitud.objects.select_for_update().get(pk=solicitud.pk)


def _releer(objeto):
    """Copia del registro tal y como está en la base de datos, sin cambios en memoria.

    Ver la explicación en `crear_solicitud`: una instancia que ya pasó por la validación
    de un ModelForm trae aplicados los datos del formulario, y no sirve como fotografía
    del estado anterior.
    """
    if objeto is None or objeto.pk is None:
        return None
    return type(objeto)._default_manager.get(pk=objeto.pk)


def obtener_objeto(solicitud):
    """Registro afectado, o None en las creaciones.

    Lanza `ErrorDeSolicitud` si la solicitud apunta a un registro que ya no existe: es un
    caso real (alguien lo borró mientras la solicitud esperaba) y hay que decirlo con
    claridad en vez de fallar con un AttributeError más adelante.
    """
    if solicitud.object_id in (None, ''):
        return None
    objeto = solicitud.objeto_afectado
    if objeto is None:
        raise ErrorDeSolicitud(
            f'El registro afectado por esta solicitud ({solicitud.descriptor}) ya no '
            'existe. La solicitud no se puede aplicar; puede rechazarla o eliminarla.')
    return objeto


# ----------------------------------------------------------------------
# Alta y edición por el Moderador
# ----------------------------------------------------------------------

def hay_pendiente_sobre(content_type, object_id, excluir_pk=None):
    """¿Existe ya una solicitud sin decidir sobre ese registro?"""
    if object_id in (None, ''):
        return None
    consulta = Solicitud.objects.filter(
        content_type=content_type, object_id=str(object_id),
        estado__in=EstadoSolicitud.pendientes())
    if excluir_pk is not None:
        consulta = consulta.exclude(pk=excluir_pk)
    return consulta.select_related('solicitante').first()


@transaction.atomic
def crear_solicitud(*, operacion, usuario, formulario=None, objeto=None, motivo=''):
    """Registra la propuesta. NO aplica el cambio: eso solo ocurre al aprobar.

    `formulario` viene ya validado por la vista (que es quien sabe si el envío fue
    correcto y quién debe repintarlo si no). Es None en las eliminaciones, que no
    proponen datos: proponen que desaparezca lo que ya hay.
    """
    from solicitudes import serializacion
    from solicitudes.operaciones import content_type_de

    definicion = definicion_de(operacion)
    content_type = content_type_de(definicion)
    object_id = str(objeto.pk) if objeto is not None else None

    duplicada = hay_pendiente_sobre(content_type, object_id)
    if duplicada is not None:
        autor = duplicada.solicitante_nombre or 'otro usuario'
        raise ErrorDeSolicitud(
            f'Ya existe una solicitud pendiente sobre este registro, creada por {autor} '
            f'el {duplicada.created_at:%d/%m/%Y}. Debe resolverse antes de crear otra.')

    datos_propuestos = serializacion.serializar(formulario) if formulario else {}

    # La fotografía se toma AQUÍ y no vuelve a tocarse nunca. Es el punto de referencia
    # contra el que se comparará la propuesta durante toda la vida de la solicitud.
    #
    # El objeto se RELEE de la base de datos en vez de usar el que llega por parámetro:
    # cuando el formulario se validó con `instance=objeto`, Django ya aplicó sobre esa
    # instancia en memoria los datos del POST (`_post_clean`). Fotografiar esa instancia
    # daría una copia idéntica a la propuesta, y la pantalla de revisión no resaltaría ni
    # un solo campo — el fallo sería invisible hasta que alguien se preguntara por qué
    # nunca se ve nada en azul.
    form_kwargs = form_kwargs_de(definicion, usuario)
    original = _releer(objeto)
    datos_originales = serializacion.capturar(
        original, definicion['form'], form_kwargs=form_kwargs) if original is not None else {}

    solicitud = Solicitud(
        operacion=operacion,
        estado=EstadoSolicitud.EN_ESPERA,
        solicitante=usuario,
        solicitante_nombre=usuario.get_full_name() or usuario.username,
        content_type=content_type,
        object_id=object_id,
        descriptor=definicion['descriptor'](original, datos_propuestos)[:200],
        datos_originales=datos_originales,
        datos_propuestos=datos_propuestos,
        unidad=definicion['unidad'](original, datos_propuestos),
        motivo=motivo or '',
    )
    solicitud.save()

    avisos.avisar_nueva_solicitud(solicitud)
    return solicitud


@transaction.atomic
def actualizar_propuesta(solicitud, usuario, formulario, motivo=None):
    """El Moderador autor rehace su propuesta mientras nadie la revisa.

    `datos_originales` NO se recaptura: la fotografía es del momento de creación aunque
    el registro real haya cambiado desde entonces (ver `solicitudes/models.py`). Tampoco
    se toca el estado ni el descriptor congelado.
    """
    from solicitudes import serializacion

    solicitud = _bloquear(solicitud)
    if not solicitud.puede_editarla(usuario):
        if solicitud.bloqueada:
            raise ErrorDeSolicitud(
                f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud en este '
                'momento. No puede modificarla hasta que termine.')
        raise ErrorDeSolicitud('No puede modificar esta solicitud.')

    solicitud.datos_propuestos = serializacion.serializar(formulario)
    if motivo is not None:
        solicitud.motivo = motivo
    solicitud.save(update_fields=['datos_propuestos', 'motivo', 'updated_at', 'updated_by'])
    return solicitud


@transaction.atomic
def eliminar(solicitud, usuario):
    """Borrado físico. Sin estado «eliminada» ni borrado lógico: la fila desaparece.

    Cubre dos casos con la misma comprobación: el Administrador elimina cualquiera, y el
    Moderador retira la suya mientras siga En Espera y nadie la revise.
    """
    solicitud = _bloquear(solicitud)
    if not solicitud.puede_eliminarla(usuario):
        if solicitud.bloqueada:
            raise ErrorDeSolicitud(
                f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud. '
                'No puede retirarla en este momento.')
        raise ErrorDeSolicitud('No tiene permisos para eliminar esta solicitud.')
    solicitud.delete()


# ----------------------------------------------------------------------
# Revisión por el Administrador
# ----------------------------------------------------------------------

@transaction.atomic
def iniciar_revision(solicitud, usuario):
    """Abre la revisión y bloquea la solicitud para el resto.

    Reentrante a propósito: si el mismo administrador vuelve a entrar (recarga la
    página, o su bloqueo anterior caducó), se le renueva el bloqueo en vez de darle un
    error por algo que no ha hecho mal.
    """
    solicitud = _bloquear(solicitud)

    if solicitud.decidida:
        raise ErrorDeSolicitud(
            f'Esta solicitud ya fue {solicitud.get_estado_display().lower()}. '
            'No se puede revisar.')
    if not solicitud.puede_revisarla(usuario):
        if solicitud.bloqueada:
            raise ErrorDeSolicitud(
                f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud desde '
                f'las {timezone.localtime(solicitud.revision_iniciada):%H:%M}.')
        raise ErrorDeSolicitud('Solo un Administrador puede revisar solicitudes.')

    solicitud.estado = EstadoSolicitud.EN_REVISION
    solicitud.revisor = usuario
    solicitud.revision_iniciada = timezone.now()
    solicitud.save(update_fields=[
        'estado', 'revisor', 'revision_iniciada', 'updated_at', 'updated_by'])
    return solicitud


@transaction.atomic
def cancelar_revision(solicitud, usuario):
    """Sale de la revisión sin decidir nada.

    NO aprueba, NO rechaza, NO guarda lo que el Administrador hubiera escrito en la
    columna de propuesta, NO crea ningún estado nuevo y NO notifica a nadie. Devuelve la
    solicitud exactamente a como estaba: En Espera y sin bloqueo. Es la salida para
    cuando hay que consultar algo fuera del sistema antes de decidir.
    """
    solicitud = _bloquear(solicitud)

    if solicitud.decidida:
        raise ErrorDeSolicitud('Esta solicitud ya fue decidida.')
    if not (getattr(usuario, 'es_admin', False) or usuario.is_superuser):
        raise ErrorDeSolicitud('Solo un Administrador puede cancelar una revisión.')

    solicitud.estado = EstadoSolicitud.EN_ESPERA
    solicitud.revisor = None
    solicitud.revision_iniciada = None
    solicitud.save(update_fields=[
        'estado', 'revisor', 'revision_iniciada', 'updated_at', 'updated_by'])

    registrar_auditoria(
        usuario=usuario, accion=AccionAuditoria.CANCELAR,
        content_type=solicitud.content_type, object_id=solicitud.object_id,
        solicitud=solicitud, descriptor=solicitud.descriptor, unidad=solicitud.unidad)
    return solicitud


@transaction.atomic
def aprobar(solicitud, usuario, datos=None):
    """Aplica el cambio y marca la solicitud como aprobada.

    `datos` es el POST del Administrador desde la pantalla de revisión: puede diferir de
    lo que propuso el Moderador, porque la decisión final y los valores aprobados son
    suyos. Se guardan en `datos_propuestos` para que quede constancia de lo que realmente
    se aprobó, no de lo que se pidió.

    **Este es el único punto donde el cambio se ejecuta**, y por eso el orden importa:

    1. `preparar_ejecucion` deja la base de datos en condiciones de aceptarlo —para
       Departamento y Cargo, desplaza las posiciones de orden si la que eligió el
       Administrador está ocupada—.
    2. Recién entonces se construye y valida el formulario COMPLETO, con todas sus
       comprobaciones: es aquí donde tienen sentido, no cuando el Moderador propuso.
    3. Se aplica.

    Si algo falla en cualquiera de los tres pasos, la excepción sube y `atomic` deshace
    TODO, incluido el desplazamiento del paso 1: la solicitud no queda aprobada si el
    cambio no llegó a aplicarse, y el organigrama no queda descolocado a medias.
    """
    from solicitudes import serializacion

    solicitud = _bloquear(solicitud)

    if solicitud.decidida:
        raise ErrorDeSolicitud(
            f'Esta solicitud ya fue {solicitud.get_estado_display().lower()}.')
    if not (getattr(usuario, 'es_admin', False) or usuario.is_superuser):
        raise ErrorDeSolicitud('Solo un Administrador puede aprobar solicitudes.')
    if solicitud.bloqueada and solicitud.revisor_id != usuario.pk:
        raise ErrorDeSolicitud(
            f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud.')

    definicion = definicion_de(solicitud.operacion)
    objeto = obtener_objeto(solicitud)
    formulario = None
    form_kwargs = form_kwargs_de(definicion, usuario)

    # Fotografía del registro real ANTES de aplicar nada, para que Auditoría registre
    # lo que realmente ocurrió (el objeto puede haber cambiado desde que se creó la
    # solicitud, y el Administrador puede haber modificado la propuesta del Moderador).
    datos_antes = serializacion.capturar(
        objeto, definicion['form'], form_kwargs=form_kwargs) if objeto is not None else {}

    if definicion['accion'] != AccionSolicitud.ELIMINAR:
        if datos is None:
            raise ErrorDeSolicitud('Faltan los datos del cambio a aplicar.')

        preparar_ejecucion(solicitud, definicion, datos, objeto)

        # `form_de_aprobacion`, no `definicion['form']` a secas: los campos que de
        # verdad nadie edita desde esta pantalla —hoy, solo `fecha_alta` de
        # `CAltaForm`— siguen naciendo deshabilitados, así que Django usa el valor
        # actual de `objeto` en vez de interpretar su ausencia en el POST como "vacío".
        # Los de `campos_condicionales` (p. ej. `motivo`, `duracion`, los «No.
        # Resolución»...) SÍ quedan editables aquí para el Administrador —ver
        # `solicitudes/serializacion.py::formulario_de_aprobacion`—, así que ya no hace
        # falta forzarles ningún valor: lo que traiga `datos` (su POST) es lo que se usa,
        # igual que para cualquier otro campo editable de la pantalla.
        formulario = serializacion.construir_formulario(
            form_de_aprobacion(definicion), instancia=objeto, datos=datos,
            form_kwargs=form_kwargs)
        if not formulario.is_valid():
            raise PropuestaInvalida(formulario)

    resultado = ejecutar(solicitud, definicion, formulario, objeto)

    if definicion['accion'] == AccionSolicitud.ELIMINAR:
        # Al borrar, Django deja la instancia sin pk, y la GenericForeignKey de la
        # solicitud sigue apuntándola desde su caché. Guardar en ese estado falla con
        # «save() prohibited to prevent data loss due to unsaved related object». Se
        # vacía la caché —no el `content_type`/`object_id`, que deben conservarse como
        # rastro de qué se eliminó— para que el guardado use los valores ya persistidos.
        solicitud._state.fields_cache.pop('objeto_afectado', None)
        datos_despues = {}
        object_id_real = solicitud.object_id
    else:
        datos_despues = serializacion.capturar(
            resultado, definicion['form'], form_kwargs=form_kwargs)
        # En CREAR, `solicitud.object_id` sigue en None (comportamiento existente: no
        # se actualiza al aprobar), así que se usa el pk recién asignado al aplicar.
        object_id_real = (str(resultado.pk) if definicion['accion'] == AccionSolicitud.CREAR
                           else solicitud.object_id)

    if formulario is not None:
        solicitud.datos_propuestos = serializacion.serializar(formulario)
    solicitud.estado = EstadoSolicitud.APROBADA
    solicitud.decidida_por = usuario
    solicitud.fecha_decision = timezone.now()
    solicitud.revisor = None
    solicitud.revision_iniciada = None
    solicitud.save()

    avisos.avisar_decision(solicitud)

    registrar_auditoria(
        usuario=usuario, accion=_ACCION_AUDITORIA_DE[definicion['accion']],
        content_type=solicitud.content_type, object_id=object_id_real,
        datos_antes=datos_antes, datos_despues=datos_despues,
        solicitud=solicitud, descriptor=solicitud.descriptor, unidad=solicitud.unidad)
    return solicitud


@transaction.atomic
def rechazar(solicitud, usuario, motivo=''):
    """Rechaza sin aplicar nada. El registro afectado queda intacto."""
    solicitud = _bloquear(solicitud)

    if solicitud.decidida:
        raise ErrorDeSolicitud(
            f'Esta solicitud ya fue {solicitud.get_estado_display().lower()}.')
    if not (getattr(usuario, 'es_admin', False) or usuario.is_superuser):
        raise ErrorDeSolicitud('Solo un Administrador puede rechazar solicitudes.')
    if solicitud.bloqueada and solicitud.revisor_id != usuario.pk:
        raise ErrorDeSolicitud(
            f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud.')

    solicitud.estado = EstadoSolicitud.RECHAZADA
    solicitud.motivo_decision = motivo or ''
    solicitud.decidida_por = usuario
    solicitud.fecha_decision = timezone.now()
    solicitud.revisor = None
    solicitud.revision_iniciada = None
    solicitud.save()

    avisos.avisar_decision(solicitud)

    registrar_auditoria(
        usuario=usuario, accion=AccionAuditoria.RECHAZAR,
        content_type=solicitud.content_type, object_id=solicitud.object_id,
        solicitud=solicitud, descriptor=solicitud.descriptor, unidad=solicitud.unidad)
    return solicitud


@transaction.atomic
def devolver_a_espera(solicitud, usuario):
    """Reabre una solicitud rechazada. Existe para corregir un rechazo por error humano.

    Solo desde RECHAZADA: una aprobada ya aplicó su cambio, y reabrirla dejaría la
    solicitud diciendo «pendiente» sobre algo que ya ocurrió.
    """
    solicitud = _bloquear(solicitud)

    if not (getattr(usuario, 'es_admin', False) or usuario.is_superuser):
        raise ErrorDeSolicitud('Solo un Administrador puede devolver una solicitud a espera.')
    if solicitud.estado != EstadoSolicitud.RECHAZADA:
        raise ErrorDeSolicitud('Solo se pueden devolver a espera las solicitudes rechazadas.')

    duplicada = hay_pendiente_sobre(
        solicitud.content_type, solicitud.object_id, excluir_pk=solicitud.pk)
    if duplicada is not None:
        raise ErrorDeSolicitud(
            'No se puede reabrir: ya hay otra solicitud pendiente sobre este mismo '
            'registro. Resuelva esa primero.')

    solicitud.estado = EstadoSolicitud.EN_ESPERA
    solicitud.motivo_decision = ''
    solicitud.decidida_por = None
    solicitud.fecha_decision = None
    solicitud.save(update_fields=[
        'estado', 'motivo_decision', 'decidida_por', 'fecha_decision',
        'updated_at', 'updated_by'])

    avisos.avisar_devuelta_a_espera(solicitud)

    registrar_auditoria(
        usuario=usuario, accion=AccionAuditoria.DEVOLVER_A_ESPERA,
        content_type=solicitud.content_type, object_id=solicitud.object_id,
        solicitud=solicitud, descriptor=solicitud.descriptor, unidad=solicitud.unidad)
    return solicitud
