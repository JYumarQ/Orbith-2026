"""Traduce hallazgos de Subsanación (y eventos de contratación) en `Notificacion`.

Es el único punto del proyecto que conoce a la vez `subsanacion` y `notificaciones`:
`subsanacion/en_caliente.py` no sabe que este módulo existe (devuelve datos puros),
y `contratos/models.py` solo llama a las funciones de aquí, sin saber nada de reglas.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from auditoria.middleware import get_current_user
from subsanacion.en_caliente import evaluar_reglas_de_instancia
from subsanacion.reglas import obtener_reglas

from .destinatarios import destinatarios_de_unidad
from .models import Notificacion

logger = logging.getLogger(__name__)


def _unidad_del_contrato(contrato):
    """Unidad organizativa de un contrato: la del cargo si tiene, si no la del aspirante.

    Mismo criterio de respaldo que ya usa `ReglaContratos.unidad_de()` en Subsanación
    (subsanacion/reglas/contratos.py), reimplementado aquí sobre la instancia real en
    vez de sobre un dict de `.values()` — son dos formas de acceder al mismo dato, no
    dos criterios distintos.
    """
    if contrato.cargo_id and contrato.cargo.departamento_id:
        return contrato.cargo.departamento.unidad_organizativa
    if contrato.aspirante_id:
        return contrato.aspirante.unidad_organizativa
    return None


def avisar_hallazgos_en_caliente(instancia):
    """Evalúa las reglas en caliente sobre `instancia` y notifica a quien la guardó.

    Deduplica por `(content_type, object_id, destinatario, codigo_regla, clave_extra)`:
    guardar el mismo registro sin corregir el campo actualiza la MISMA notificación en
    vez de crear una nueva. Si el problema se corrige, la notificación existente pasa a
    `estado=RESUELTA` sin tocar `leido` — nunca se borra.
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

    detectadas_claves = set()

    for regla, detectados in resultados:
        for detectado in detectados:
            clave_extra = detectado.clave_extra or ''
            detectadas_claves.add((regla.codigo, clave_extra))

            existente = Notificacion.objects.filter(
                content_type=tipo_ct, object_id=object_id, destinatario=destinatario,
                codigo_regla=regla.codigo, clave_extra=clave_extra,
            ).first()

            if existente and existente.estado == Notificacion.Estado.DESCARTADA:
                # Un descarte manual (falso positivo / caso aceptado) no lo revierte
                # la próxima evaluación automática — mismo criterio que Subsanación ya
                # aplica a sus hallazgos «Ignorado»/«Falso positivo».
                continue

            Notificacion.objects.update_or_create(
                content_type=tipo_ct, object_id=object_id, destinatario=destinatario,
                codigo_regla=regla.codigo, clave_extra=clave_extra,
                defaults={
                    'titulo': detectado.titulo,
                    'mensaje': detectado.detalle,
                    'tipo': Notificacion.Tipo.ALERTA,
                    'severidad': regla.criticidad,
                    'estado': Notificacion.Estado.ACTIVA,
                    'fecha_resolucion': None,
                },
            )

    if not codigos_relevantes:
        return

    # Resolver (sin borrar, sin tocar `leido`) las que ya no se detectan.
    candidatas = Notificacion.objects.filter(
        content_type=tipo_ct, object_id=object_id,
        estado=Notificacion.Estado.ACTIVA, codigo_regla__in=codigos_relevantes,
    )
    ahora = timezone.now()
    for notificacion in candidatas:
        if (notificacion.codigo_regla, notificacion.clave_extra) in detectadas_claves:
            continue
        notificacion.estado = Notificacion.Estado.RESUELTA
        notificacion.fecha_resolucion = ahora
        notificacion.save(update_fields=['estado', 'fecha_resolucion'])


def avisar_alta_contrato(contrato):
    """Notifica el alta de un contrato a los destinatarios de su unidad.

    Evento, no alerta: `tipo=EVENTO`, sin `severidad` (no describe un problema).
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

    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=titulo, mensaje=mensaje, tipo=Notificacion.Tipo.EVENTO,
            content_type=tipo_ct, object_id=str(contrato.pk),
            unidad=unidad, destinatario=destinatario,
        )
        for destinatario in destinatarios
    ])


def avisar_baja_contrato(contrato):
    """Notifica la baja de un contrato a los destinatarios de su unidad.

    Se llama ANTES de `super().delete()`: el `content_type`/`object_id` apuntan al
    `Aspirante` (que sigue existiendo), no al `CAlta` que está a punto de borrarse y
    quedaría inaccesible después.
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

    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=titulo, mensaje=mensaje, tipo=Notificacion.Tipo.EVENTO,
            content_type=tipo_ct, object_id=str(contrato.aspirante_id),
            unidad=unidad, destinatario=destinatario,
        )
        for destinatario in destinatarios
    ])
