"""Regla cronológica ÚNICA del histórico del trabajador.

Todo lo que escribe un evento en el histórico (el alta o la recontratación desde el
asistente, el movimiento de nómina y la baja) comprueba aquí su fecha. Antes cada
vista hacía su propia comparación, el asistente no hacía ninguna en el servidor (solo
el JavaScript) y dos eventos podían quedar en el mismo día.

Decisiones de RRHH del 23-10-2026:
* Ningún evento puede tener fecha futura.
* Dos eventos del mismo trabajador nunca caen el mismo día: cada uno es
  ESTRICTAMENTE posterior al anterior. Por eso recontratar exige, como pronto, el
  día siguiente a la baja.

El «último evento» se mira en TODO el histórico de la persona (todos sus contratos,
movimientos y bajas), no solo en el contrato vigente: así una recontratación no
puede quedar antes de una baja anterior. Cuesta dos consultas agregadas por guardado.
"""

from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

#: Mismo corte que `contratos.forms.ANO_MINIMO_FECHAS` (se repite para no importar
#: los formularios desde aquí).
ANO_MINIMO = 1900


def _texto(fecha):
    return fecha.strftime('%d/%m/%Y')


def ultimo_evento(aspirante_id, contrato=None):
    """Fecha del último evento del histórico de la persona, o None si no tiene.

    Cuenta sus movimientos (de cualquier tipo y contrato), sus bajas y, si se pasa,
    la fecha de alta del contrato (un contrato antiguo puede no tener movimientos).
    """
    from .models import CBaja, TMovimiento

    filtro = Q(aspirante_id=aspirante_id)
    if contrato is not None and contrato.pk:
        filtro |= Q(contrato_id=contrato.pk)
    fechas = [
        TMovimiento.objects.filter(filtro).aggregate(f=Max('fecha_efectiva'))['f'],
        CBaja.objects.filter(aspirante_id=aspirante_id).aggregate(f=Max('fecha_baja'))['f'],
        getattr(contrato, 'fecha_alta', None),
    ]
    fechas = [f for f in fechas if f]
    return max(fechas) if fechas else None


def fecha_minima_permitida(aspirante_id, contrato=None):
    """Primer día en que se puede registrar un evento nuevo (el siguiente al último)."""
    ultimo = ultimo_evento(aspirante_id, contrato)
    return ultimo + timedelta(days=1) if ultimo else None


def validar_fecha_no_futura(fecha, etiqueta):
    """Mensaje de error si `fecha` es posterior a hoy; None si es válida o vacía."""
    if fecha and fecha > timezone.localdate():
        return f'{etiqueta} no puede ser una fecha futura ({_texto(fecha)}).'
    return None


def validar_fecha_evento(fecha, aspirante_id, contrato=None, etiqueta='La fecha'):
    """Comprueba la fecha de un evento nuevo del histórico.

    Devuelve el mensaje de error (en español) o None si la fecha es válida.
    """
    if not fecha:
        return f'{etiqueta} es obligatoria.'
    if fecha.year < ANO_MINIMO:
        return (f'El año de {etiqueta.lower()} debe ser {ANO_MINIMO} o posterior. Revise '
                f'que haya escrito el año completo (por ejemplo 2022, no 0002).')
    error = validar_fecha_no_futura(fecha, etiqueta)
    if error:
        return error
    ultimo = ultimo_evento(aspirante_id, contrato)
    if ultimo and fecha <= ultimo:
        return (f'{etiqueta} ({_texto(fecha)}) debe ser posterior al último evento del '
                f'histórico del trabajador ({_texto(ultimo)}). No se permiten dos '
                f'eventos el mismo día: la primera fecha válida es el '
                f'{_texto(ultimo + timedelta(days=1))}.')
    return None
