"""Receptores de señales de otras apps.

Este archivo es el lado «notificaciones» del acoplamiento por señal que documenta
`subsanacion/signals.py`: Subsanación nunca importa `notificaciones` ni sabe que este
receptor existe, así que puede desconectarse o cambiar de forma sin tocar nada aquí
más que esta función.
"""

import logging

logger = logging.getLogger(__name__)


def avisar_criticas_nuevas(sender, ejecucion, **kwargs):
    """Crea una notificación personal a cada administrador si aparece una crítica nueva.

    «Nueva» significa que su `primera_deteccion` cae dentro de ESTA ejecución: nunca se
    había detectado antes. Un hallazgo crítico que REAPARECE tras haber sido corregido
    no entra por este camino (su `primera_deteccion` es antigua); es un caso más raro y
    se deja fuera a propósito, para mantener esta función simple y sin ambigüedad sobre
    qué cuenta como «nueva».

    Se ejecuta al terminar CUALQUIER análisis, completo o parcial: si un módulo con
    reglas críticas se analizó, sus hallazgos nuevos deben avisar igual.
    """
    from django.contrib.contenttypes.models import ContentType

    from subsanacion.constantes import CRITICIDAD_CRITICA
    from subsanacion.models import Hallazgo
    from usuarios.models import CustomUser

    from .avisos import _registrar_notificacion
    from .models import Notificacion

    nuevas_criticas = Hallazgo.objects.filter(
        ejecucion=ejecucion,
        criticidad=CRITICIDAD_CRITICA,
        primera_deteccion__gte=ejecucion.iniciada_en,
    )
    total = nuevas_criticas.count()
    if not total:
        return

    admins = CustomUser.objects.filter(es_admin=True, is_active=True)
    if not admins.exists():
        logger.warning(
            'Subsanación detectó %s hallazgo(s) crítico(s) nuevo(s), pero no hay '
            'ningún administrador activo al que avisar.', total)
        return

    tipo_ejecucion = ContentType.objects.get_for_model(ejecucion)
    titulo = f'Subsanación: {total} hallazgo{"s" if total != 1 else ""} crítico{"s" if total != 1 else ""} nuevo{"s" if total != 1 else ""}'
    mensaje = (
        f'El análisis del {ejecucion.iniciada_en:%d/%m/%Y %H:%M} detectó {total} '
        f'hallazgo{"s" if total != 1 else ""} de gravedad crítica que no se había'
        f'{"n" if total != 1 else ""} visto antes. Revíselo{"s" if total != 1 else ""} '
        f'en Subsanación.')

    # `object_id` (el pk de esta `EjecucionAnalisis`) ya es único por ejecución, así
    # que `codigo_regla='ALE-CRITICAS'` con `clave_extra=''` basta — el caso real que
    # protege es la MISMA señal `analisis_finalizado` disparándose dos veces para la
    # MISMA ejecución (antes se escribía con `bulk_create()` y `codigo_regla=''`, sin
    # ninguna clave natural que lo impidiera).
    for admin in admins:
        _registrar_notificacion(
            tipo_ct=tipo_ejecucion, object_id=str(ejecucion.pk), destinatario=admin,
            codigo_regla='ALE-CRITICAS', clave_extra='',
            defaults={
                'titulo': titulo, 'mensaje': mensaje,
                # Es una alerta de integridad, no un evento informativo — sin esto caía
                # en el default EVENTO y aparecía mezclada con altas/bajas/cargos nuevos
                # en vez de en la pestaña de Advertencias.
                'tipo': Notificacion.Tipo.ALERTA, 'estado': Notificacion.Estado.ACTIVA,
            },
        )


def borrar_avisos_del_contrato(sender, instance, **kwargs):
    """Al borrarse un contrato vivo (al causar baja, o desde el Admin) se borran:

    * TODOS los avisos que apuntaban al contrato («Designado sin código», «Nuevo
      contrato de alta»…). Antes se quedaban activos para siempre y su enlace
      llevaba a un contrato que ya no existe (error 404).
    * Si la persona se queda sin contrato vivo (ha causado baja), las ALERTAS de
      datos de su ficha («Sin dirección», «Tallas incompletas»…): ya nadie las va a
      completar. Los avisos de tipo Evento, como «Baja de contrato», se quedan:
      son los que informan de la baja. Si vuelve a ser contratada, el análisis de
      incidencias le crea de nuevo las alertas que sigan haciendo falta.

    Se borran y no se marcan «Resuelto» porque nadie los resolvió (decisión de
    RRHH del 13-10-2026)."""
    from django.contrib.contenttypes.models import ContentType

    from bolsa.models import Aspirante

    from .models import Notificacion

    borradas, _ = Notificacion.objects.filter(
        content_type=ContentType.objects.get_for_model(type(instance)),
        object_id=str(instance.pk)).delete()
    if instance.aspirante_id and not type(instance).objects.filter(
            aspirante_id=instance.aspirante_id).exists():
        de_la_ficha, _ = Notificacion.objects.filter(
            content_type=ContentType.objects.get_for_model(Aspirante),
            object_id=str(instance.aspirante_id),
            tipo=Notificacion.Tipo.ALERTA).delete()
        borradas += de_la_ficha
    if borradas:
        logger.info('Borrados %s avisos del contrato %s (y de su ficha), que ya no existe.',
                    borradas, instance.pk)
