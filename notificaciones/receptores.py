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

    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=titulo, mensaje=mensaje, destinatario=admin,
            content_type=tipo_ejecucion, object_id=str(ejecucion.pk))
        for admin in admins
    ])
