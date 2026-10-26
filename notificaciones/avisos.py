"""Traduce hallazgos de Subsanación (y eventos de contratación) en `Notificacion`.

Es el único punto del proyecto que conoce a la vez `subsanacion` y `notificaciones`:
`subsanacion/en_caliente.py` no sabe que este módulo existe (devuelve datos puros),
y `contratos/models.py` solo llama a las funciones de aquí, sin saber nada de reglas.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from auditoria.middleware import get_current_user
from subsanacion.en_caliente import evaluar_reglas_de_instancia
from subsanacion.reglas import obtener_reglas

from .destinatarios import destinatarios_de_unidad
from .models import Notificacion

logger = logging.getLogger(__name__)


def _unidad_del_contrato(contrato):
    """Unidad organizativa de un contrato: la de su cargo (None si no tiene).

    Mismo criterio que `ReglaContratos.unidad_de()` en Subsanación. La persona no
    guarda unidad propia (campo eliminado el 26-10-2026).
    """
    if contrato.cargo_id and contrato.cargo.departamento_id:
        return contrato.cargo.departamento.unidad_organizativa
    return None


def _registrar_notificacion(*, tipo_ct, object_id, destinatario, codigo_regla, clave_extra, defaults):
    """Punto único de escritura para Advertencias Y Recordatorios: un hecho detectado
    (un hallazgo de Subsanación o un recordatorio automático) + un destinatario ->
    una fila `Notificacion`. Antes existían dos copias casi idénticas de esta lógica
    (una por tipo); se unificaron aquí para que la protección de concurrencia de abajo
    no tuviera que mantenerse dos veces.

    Deduplica por `(content_type, object_id, destinatario, codigo_regla, clave_extra)`:
    volver a detectar el mismo problema actualiza la MISMA fila en vez de crear una
    nueva. Un descarte manual (falso positivo / caso aceptado, o "no molestar" en
    Recordatorios) no lo revierte la próxima evaluación automática.

    Concurrencia: el SELECT de `existente` de arriba y el `update_or_create()` de abajo
    NO son atómicos entre sí frente a OTRO proceso — dos moderadores pulsando "Buscar
    incidencias" casi a la vez, el comando programado solapándose con un clic manual, o
    varios workers evaluando la misma regla, pueden pasar ambos el SELECT (ninguno ve
    la fila del otro, que aún no confirmó) y los dos intentar crear la fila. Sin nada
    más, eso duplicaba la notificación tantas veces como procesos concurrentes
    coincidieran — el origen real de los duplicados vistos en producción. La restricción
    `UniqueConstraint` de `Notificacion.Meta` (misma clave, `codigo_regla != ''`) hace
    que el segundo INSERT falle con `IntegrityError` en vez de duplicar; aquí se captura
    y el perdedor de la carrera simplemente actualiza la fila que el ganador acaba de
    crear, en vez de propagar el error o crear una fila nueva.
    """
    clave_extra = clave_extra or ''
    filtro = dict(content_type=tipo_ct, object_id=object_id, destinatario=destinatario,
                  codigo_regla=codigo_regla, clave_extra=clave_extra)

    existente = Notificacion.objects.filter(**filtro).first()
    if existente and existente.estado == Notificacion.Estado.DESCARTADA:
        return existente

    try:
        with transaction.atomic():
            notificacion, _creada = Notificacion.objects.update_or_create(
                **filtro, defaults=defaults)
    except IntegrityError:
        notificacion = Notificacion.objects.get(**filtro)
        for campo, valor in defaults.items():
            setattr(notificacion, campo, valor)
        notificacion.save(update_fields=list(defaults.keys()))
    return notificacion


def _registrar_notificacion_de_hallazgo(*, tipo_ct, object_id, destinatario, regla, hallazgo):
    """Un `HallazgoDetectado` + un destinatario -> una fila `Notificacion` de tipo
    Advertencia. Ver `_registrar_notificacion` para la clave de deduplicación y la
    protección de concurrencia."""
    return _registrar_notificacion(
        tipo_ct=tipo_ct, object_id=object_id, destinatario=destinatario,
        codigo_regla=regla.codigo, clave_extra=hallazgo.clave_extra or '',
        defaults={
            'titulo': hallazgo.titulo,
            'mensaje': hallazgo.detalle,
            'tipo': Notificacion.Tipo.ALERTA,
            'severidad': regla.criticidad,
            'estado': Notificacion.Estado.ACTIVA,
            'fecha_resolucion': None,
            # El hallazgo ya trae su propia unidad (calculada por la regla); antes no
            # se guardaba aquí y el campo `unidad` de las alertas quedaba siempre
            # vacío, dejando sin efecto el filtro por unidad de Advertencias.
            'unidad_id': hallazgo.unidad_organizativa_id,
            'campo_formulario': hallazgo.campo_formulario,
        },
    )


def _registrar_recordatorio(*, tipo_ct, object_id, destinatario, codigo, clave_extra,
                             titulo, mensaje, fecha_objetivo, unidad_id):
    """Un recordatorio automático detectado (`notificaciones/recordatorios.py`) + un
    destinatario -> una fila `Notificacion` de tipo Recordatorio. Reutiliza el MISMO
    punto de escritura que Advertencias (`_registrar_notificacion`) en vez de un
    mecanismo paralelo — `codigo` ocupa el campo `codigo_regla` (identifica el TIPO de
    recordatorio: 'REC-CUMPLE', etc.), igual que una regla de Subsanación identifica un
    tipo de alerta."""
    return _registrar_notificacion(
        tipo_ct=tipo_ct, object_id=object_id, destinatario=destinatario,
        codigo_regla=codigo, clave_extra=clave_extra,
        defaults={
            'titulo': titulo,
            'mensaje': mensaje,
            'tipo': Notificacion.Tipo.RECORDATORIO,
            'origen': Notificacion.Origen.SISTEMA,
            'estado': Notificacion.Estado.ACTIVA,
            'fecha_resolucion': None,
            'fecha_objetivo': fecha_objetivo,
            'unidad_id': unidad_id,
        },
    )


def _resolver_notificaciones_obsoletas(*, destinatario, codigos_relevantes, claves_vigentes, alcance=None):
    """Marca `RESUELTA` (sin tocar `leido`) las notificaciones `ACTIVA` de
    `destinatario` cuyo `codigo_regla` está en `codigos_relevantes` pero cuya clave
    `(content_type_id, object_id, codigo_regla, clave_extra)` NO está en
    `claves_vigentes` — es decir, ya no se detectan. No se borran aquí: quedan
    `RESUELTA` y las purga `notificaciones/limpieza.py::purgar_notificaciones_antiguas()`
    a los 60 días (bandeja enfocada en lo vigente, no un historial permanente).

    `alcance` es un filtro adicional opcional sobre el queryset de candidatas (por
    ejemplo `{'content_type': tipo_ct, 'object_id': object_id}`): lo usa
    `avisar_hallazgos_en_caliente()` para acotar la resolución a la MISMA instancia
    que se acaba de guardar, sin tocar notificaciones de otros registros con el mismo
    código de regla. El escaneo en lote (`notificaciones/escaneo.py`) no lo pasa: su
    `claves_vigentes` ya cubre toda la empresa, así que no hace falta acotar más.
    """
    if not codigos_relevantes:
        return 0

    candidatas = Notificacion.objects.filter(
        destinatario=destinatario, estado=Notificacion.Estado.ACTIVA,
        codigo_regla__in=codigos_relevantes)
    if alcance:
        candidatas = candidatas.filter(**alcance)

    ahora = timezone.now()
    resueltas = 0
    for notificacion in candidatas:
        clave = (notificacion.content_type_id, notificacion.object_id,
                  notificacion.codigo_regla, notificacion.clave_extra)
        if clave in claves_vigentes:
            continue
        notificacion.estado = Notificacion.Estado.RESUELTA
        notificacion.fecha_resolucion = ahora
        notificacion.save(update_fields=['estado', 'fecha_resolucion'])
        resueltas += 1
    return resueltas


def avisar_hallazgos_en_caliente(instancia):
    """Evalúa las reglas en caliente sobre `instancia` y notifica a quien la guardó.

    Deduplica por `(content_type, object_id, destinatario, codigo_regla, clave_extra)`:
    guardar el mismo registro sin corregir el campo actualiza la MISMA notificación en
    vez de crear una nueva. Si el problema se corrige, la notificación existente pasa a
    `estado=RESUELTA` sin tocar `leido`; se conserva 60 días y después se purga (ver
    `notificaciones/limpieza.py`).
    """
    resultados = evaluar_reglas_de_instancia(instancia)

    usuario = get_current_user()
    destinatario = usuario if (usuario and getattr(usuario, 'is_authenticated', False)) else None

    etiqueta = f'{instancia._meta.app_label}.{instancia._meta.model_name}'
    tipo_ct = ContentType.objects.get_for_model(instancia)
    object_id = str(instancia.pk)

    # Reglas que podrían aplicar a este modelo, detectaran algo o no en esta pasada.
    # Sirve para acotar qué notificaciones ACTIVAS son candidatas a resolverse: solo
    # las que vienen de una regla evaluable en caliente de ESTE modelo, nunca las de
    # otra procedencia.
    codigos_relevantes = {
        r.codigo for r in obtener_reglas()
        if r.evaluable_en_caliente and r.modelo.lower() == etiqueta
    }

    if destinatario is None:
        # Comando de consola, script, migración de datos: no hay a quién notificar.
        # No es un error, así que no se lanza excepción; solo se registra para que
        # quede constancia de que la evaluación ocurrió sin destinatario.
        if resultados:
            logger.info(
                "Alertas de integridad detectadas en %s #%s sin usuario en contexto "
                "(script o migración); no se notifica a nadie.", etiqueta, instancia.pk)
        return

    claves_vigentes = set()
    # La ficha de quien causó baja no recibe alertas (ver `escaneo.notificar_resultados`).
    if instancia._meta.label_lower == 'bolsa.aspirante' and getattr(instancia, 'estado', '') == 'BAJA':
        resultados = []

    for regla, detectados in resultados:
        for detectado in detectados:
            claves_vigentes.add(
                (tipo_ct.id, object_id, regla.codigo, detectado.clave_extra or ''))
            _registrar_notificacion_de_hallazgo(
                tipo_ct=tipo_ct, object_id=object_id, destinatario=destinatario,
                regla=regla, hallazgo=detectado)

    _resolver_notificaciones_obsoletas(
        destinatario=destinatario, codigos_relevantes=codigos_relevantes,
        claves_vigentes=claves_vigentes,
        alcance={'content_type': tipo_ct, 'object_id': object_id})


#: Códigos de los eventos de contratación/plantilla — cumplen el mismo papel que
#: `codigo_regla` de una regla de Subsanación o un detector de Recordatorios: son la
#: clave que engancha estas filas a la `UniqueConstraint` de `Notificacion.Meta` (que
#: solo protege `codigo_regla != ''`) y a la protección de concurrencia de
#: `_registrar_notificacion`. Antes se creaban con `bulk_create()` y `codigo_regla=''`
#: (el valor por defecto de un EVENTO), sin ninguna clave natural que las protegiera —
#: el mismo hueco que causó los avisos de Solicitud duplicados en producción.
CODIGO_ALTA_CONTRATO = 'EVT-ALTA'
CODIGO_BAJA_CONTRATO = 'EVT-BAJA'
CODIGO_NUEVO_CARGO = 'EVT-CARGO'


def avisar_alta_contrato(contrato):
    """Notifica el alta de un contrato a los destinatarios de su unidad.

    Evento, no alerta: `tipo=EVENTO`, sin `severidad` (no describe un problema).

    `object_id=str(contrato.pk)` ya es único por sí solo (una `CAlta` se crea una
    sola vez), así que `clave_extra=''` no puede colisionar con la de otra alta.
    """
    unidad = _unidad_del_contrato(contrato)
    destinatarios = list(destinatarios_de_unidad(unidad)) if unidad else []

    if not destinatarios:
        logger.warning(
            "Alta del contrato %s sin ningún destinatario que notificar "
            "(unidad=%s sin moderador ni administradores activos).",
            contrato.pk, unidad)
        return

    tipo_ct = ContentType.objects.get_for_model(contrato)
    titulo = "Nuevo contrato de alta"
    # `Aspirante.__str__` ya devuelve "nombre papellido sapellido" limpio.
    mensaje = f"Se ha creado el contrato {contrato.no_expediente} de {contrato.aspirante}."

    for destinatario in destinatarios:
        _registrar_notificacion(
            tipo_ct=tipo_ct, object_id=str(contrato.pk), destinatario=destinatario,
            codigo_regla=CODIGO_ALTA_CONTRATO, clave_extra='',
            defaults={
                'titulo': titulo, 'mensaje': mensaje,
                'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                'unidad': unidad,
            },
        )


def avisar_baja_contrato(contrato):
    """Notifica la baja de un contrato a los destinatarios de su unidad.

    Se llama ANTES de `super().delete()`: el `content_type`/`object_id` apuntan al
    `Aspirante` (que sigue existiendo), no al `CAlta` que está a punto de borrarse y
    quedaría inaccesible después.

    `object_id` es el `Aspirante`, que puede tener varias bajas reales a lo largo del
    tiempo (recontratación) — a diferencia del alta, aquí `object_id` por sí solo NO
    discrimina eventos distintos. Por eso `clave_extra=str(contrato.pk)` (la `CAlta`
    concreta que se está dando de baja): cada baja real tiene una clave propia, y solo
    colapsa con otra si es literalmente el mismo evento repetido por una carrera de
    escritura, nunca con la baja de un contrato distinto del mismo trabajador.
    """
    if not contrato.aspirante_id:
        return

    unidad = _unidad_del_contrato(contrato)
    destinatarios = list(destinatarios_de_unidad(unidad)) if unidad else []

    if not destinatarios:
        logger.warning(
            "Baja del contrato %s sin ningún destinatario que notificar "
            "(unidad=%s sin moderador ni administradores activos).",
            contrato.pk, unidad)
        return

    tipo_ct = ContentType.objects.get_for_model(contrato.aspirante)
    titulo = "Baja de contrato"
    mensaje = f"Se ha dado de baja el contrato {contrato.no_expediente} de {contrato.aspirante}."

    for destinatario in destinatarios:
        _registrar_notificacion(
            tipo_ct=tipo_ct, object_id=str(contrato.aspirante_id), destinatario=destinatario,
            codigo_regla=CODIGO_BAJA_CONTRATO, clave_extra=str(contrato.pk),
            defaults={
                'titulo': titulo, 'mensaje': mensaje,
                'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                'unidad': unidad,
            },
        )


def avisar_nuevo_cargo(cargo):
    """Notifica un cargo nuevo en la plantilla a los destinatarios de su unidad.

    Movida aquí desde `strorganizativa/models.py::CargoPlantilla.save()` (donde vivía
    inline, con un `bulk_create()` sin protección) para que reutilice el mismo punto de
    escritura que el resto de eventos de este módulo. `object_id=str(cargo.pk)` ya es
    único (un `CargoPlantilla` se crea una sola vez), así que `clave_extra=''` basta.
    """
    unidad = cargo.departamento.unidad_organizativa
    destinatarios = list(destinatarios_de_unidad(unidad)) if unidad else []

    if not destinatarios:
        logger.warning(
            "Nuevo cargo %s sin ningún destinatario que notificar "
            "(unidad=%s sin moderador ni administradores activos).",
            cargo.pk, unidad)
        return

    tipo_ct = ContentType.objects.get_for_model(cargo)
    titulo = "Nuevo Cargo creado"
    mensaje = f"Se ha creado un nuevo cargo: {cargo.ncargo.descripcion} en {cargo.departamento}."

    for destinatario in destinatarios:
        _registrar_notificacion(
            tipo_ct=tipo_ct, object_id=str(cargo.pk), destinatario=destinatario,
            codigo_regla=CODIGO_NUEVO_CARGO, clave_extra='',
            defaults={
                'titulo': titulo, 'mensaje': mensaje,
                'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                'unidad': unidad,
            },
        )


CODIGO_CAMBIO_ROL = 'EVT-ROL'
CODIGO_CAMBIO_ESCALA = 'EVT-ESCALA'
CODIGO_CAMBIO_ESTRUCTURA = 'EVT-ESTRUC'
CODIGO_CAMBIO_IMPORTE = 'EVT-IMPORTE'


def avisar_cambio_salarial(objeto, *, codigo, titulo, mensaje, unidad=None):
    """Avisa de que un cambio en un cargo (su rol) o en la escala salarial actualizó
    el salario de contratos ya existentes (decisión de RRHH del 23-10-2026).

    Lo reciben los administradores activos, quien hizo el cambio y, si el cambio es
    de un cargo, el moderador de su unidad: un moderador no edita cargos
    directamente, lo pide con una Solicitud y quien la aplica es el administrador;
    así el moderador que lo pidió también se entera.

    Cada cambio es un hecho distinto (el mismo cargo puede cambiar de rol varias
    veces), así que `clave_extra` lleva el instante y nunca colapsa con uno anterior.
    """
    from usuarios.models import CustomUser

    destinatarios = set(CustomUser.objects.filter(es_admin=True, is_active=True))
    if unidad is not None:
        destinatarios.update(destinatarios_de_unidad(unidad))
    usuario = get_current_user()
    if usuario is not None and getattr(usuario, 'is_authenticated', False):
        destinatarios.add(usuario)

    tipo_ct = ContentType.objects.get_for_model(objeto)
    instante = timezone.now().strftime('%Y%m%d%H%M%S%f')
    for destinatario in destinatarios:
        _registrar_notificacion(
            tipo_ct=tipo_ct, object_id=str(objeto.pk), destinatario=destinatario,
            codigo_regla=codigo, clave_extra=instante,
            defaults={
                'titulo': titulo, 'mensaje': mensaje,
                'tipo': Notificacion.Tipo.EVENTO, 'estado': Notificacion.Estado.ACTIVA,
                'unidad': unidad,
            },
        )
