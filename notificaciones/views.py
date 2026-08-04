from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import Notificacion


def _notificaciones_visibles(usuario):
    """Notificaciones que PERTENECEN al usuario, leídas o no.

    Es la base de pertenencia, sin filtrar por `leido`: marcar como leída una
    notificación ya leída (un doble clic, o abrirla desde dos pestañas) no debe dar
    404. `_notificaciones_del_usuario()` la usa añadiendo el filtro de bandeja.
    """
    unidades_usuario = usuario.unidades.all()
    return Notificacion.objects.filter(
        Q(unidad__in=unidades_usuario) | Q(destinatario=usuario))


def _notificaciones_del_usuario(usuario):
    """La bandeja: lo que aún no se ha leído. Antes de añadir `destinatario`, esta
    consulta solo miraba `unidad__in`. Un administrador sin ninguna unidad asignada
    (el caso más común: un admin gestiona todo, no una unidad concreta) nunca vería
    un aviso dirigido a él por esa vía, así que las notificaciones personales entran
    con un OR, no sustituyendo al filtro por unidad que ya usaban las notificaciones
    existentes."""
    return _notificaciones_visibles(usuario).filter(leido=False)


def _serializar(n):
    return {
        'id': n.pk,
        'titulo': n.titulo,
        'mensaje': n.mensaje,
        'fecha': n.fecha_creado.strftime('%Y-%m-%d %H:%M'),
        'tipo': n.tipo,
        'severidad': n.severidad,
        'estado': n.estado,
    }


# Create your views here.
def notificaciones_json(request):
    notificaciones = _notificaciones_del_usuario(request.user)
    data = [_serializar(n) for n in notificaciones]
    return JsonResponse({'notificaciones': data})

# notificaciones/views.py
def ultimas_notificaciones(request):
    # Sin `.order_by()` explícito: se respeta `Meta.ordering` del modelo
    # (`['severidad', '-fecha_creado']`), para que una alerta crítica no quede tapada
    # por un evento reciente sin gravedad.
    notificaciones = _notificaciones_del_usuario(request.user)[:5]
    data = [_serializar(n) for n in notificaciones]
    return JsonResponse({'notificaciones': data})


@login_required
@require_POST
def marcar_leida(request, pk):
    """Marca UNA notificación como leída. Nunca toca `estado`."""
    notificacion = get_object_or_404(_notificaciones_visibles(request.user), pk=pk)
    notificacion.leido = True
    notificacion.save(update_fields=['leido'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def marcar_todas_leidas(request):
    """Marca como leídas todas las notificaciones pendientes del usuario."""
    actualizadas = _notificaciones_del_usuario(request.user).update(leido=True)
    return JsonResponse({'ok': True, 'actualizadas': actualizadas})
