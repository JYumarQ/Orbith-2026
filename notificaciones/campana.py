"""Qué cuenta en el número rojo de la campana (decisión de RRHH del 18-11-2026).

Solo lo que pide hacer algo:

* Advertencias activas Críticas y Altas (y las que no tienen gravedad, como «hallazgos
  críticos nuevos» de Subsanación). Las Medias y Bajas se ven en Advertencias,
  agrupadas, pero no suman.
* Recordatorios activos en rojo o amarillo: vencidos, de hoy o de los próximos
  `DIAS_RECORDATORIO_URGENTE` días (o sin fecha). Los naranja y verde no suman.
* Avisos de cierre (CIE-*), cualquiera que sea su gravedad.
* Eventos que no son actividad: solicitudes, decisiones, Ranking, cierre corregido…
  Las altas, bajas, cargos nuevos y cambios salariales (EVT-*) se ven en «Actividad
  de hoy» y no suman.

Siempre sobre lo NO leído de la bandeja personal del usuario.
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from subsanacion.constantes import CRITICIDAD_ALTA

from .models import Notificacion

DIAS_RECORDATORIO_URGENTE = 15

#: Prefijo de los eventos de actividad (alta, baja, cargo, rol, escala, importe,
#: estructura): van a «Actividad de hoy» y nunca cuentan.
PREFIJO_ACTIVIDAD = 'EVT-'
PREFIJO_CIERRE = 'CIE-'


def q_accionable(hoy=None):
    """Filtro de lo que cuenta en la campana (ver la cabecera del módulo)."""
    hoy = hoy or timezone.localdate()
    activa = Q(estado=Notificacion.Estado.ACTIVA)
    advertencia = Q(tipo=Notificacion.Tipo.ALERTA) & (
        Q(severidad__lte=CRITICIDAD_ALTA) | Q(severidad__isnull=True))
    recordatorio = Q(tipo=Notificacion.Tipo.RECORDATORIO) & (
        Q(fecha_objetivo__lte=hoy + timedelta(days=DIAS_RECORDATORIO_URGENTE))
        | Q(fecha_objetivo__isnull=True))
    cierre = Q(codigo_regla__startswith=PREFIJO_CIERRE)
    evento = Q(tipo=Notificacion.Tipo.EVENTO) & ~Q(codigo_regla__startswith=PREFIJO_ACTIVIDAD)
    return activa & (advertencia | recordatorio | cierre | evento)


def q_bandeja(usuario):
    """Las copias que son de `usuario` (bandeja personal, 25-10-2026). Las filas sin
    destinatario (datos anteriores al reparto) se ven por unidad; el Administrador,
    todas. Vive aquí, sin depender de las vistas, porque también lo usa el contador
    de la barra lateral, que corre en cada petición."""
    sin_destinatario = Q(destinatario__isnull=True)
    if not usuario.es_admin:
        sin_destinatario &= Q(unidad__in=usuario.unidades.all())
    return Q(destinatario=usuario) | sin_destinatario


def accionables(usuario):
    """Lo no leído de la bandeja de `usuario` que cuenta en la campana."""
    return Notificacion.objects.filter(q_bandeja(usuario), q_accionable(), leido=False)
