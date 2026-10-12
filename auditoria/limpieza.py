"""Borrado de la auditoría antigua, sin tareas programadas en el servidor.

El plazo lo decide el Administrador en Parámetros Generales
(`Configuracion.auditoria_borrar_antigua` y `auditoria_anios_conservar`). Apagado,
que es el valor inicial, significa «Nunca»: no se borra nada.

No hay ningún cron ni proceso aparte: la limpieza se hace al abrir la pantalla de
Auditoría (`auditoria.views.index`). Es una sola consulta; cuando no hay nada que
borrar apenas cuesta. Si nadie abre la pantalla en meses, lo antiguo simplemente
espera a la próxima vez: no hay riesgo de perder nada que debiera conservarse.
"""

from datetime import date

from django.utils import timezone

from .models import EventoAuditoria


def fecha_limite(anios, hoy=None):
    """El mismo día de hace `anios` años. Un 29 de febrero pasa al 28."""
    hoy = hoy or timezone.localdate()
    try:
        return hoy.replace(year=hoy.year - anios)
    except ValueError:
        return date(hoy.year - anios, 2, 28)


def borrar_auditoria_antigua(hoy=None):
    """Borra los eventos más antiguos que el plazo configurado. Devuelve cuántos."""
    from configuracion.models import Configuracion

    config = (Configuracion.objects
              .values('auditoria_borrar_antigua', 'auditoria_anios_conservar')
              .first())
    if not config or not config['auditoria_borrar_antigua']:
        return 0
    anios = config['auditoria_anios_conservar']
    if not anios or anios < 2:
        # Un plazo inválido nunca debe borrar de más: se respeta el mínimo de 2.
        return 0
    borrados, _ = EventoAuditoria.objects.filter(
        fecha__date__lt=fecha_limite(anios, hoy)).delete()
    return borrados
