from django.http import JsonResponse
from .models import Notificacion

# Create your views here.
def notificaciones_json(request):
    unidades_usuario = request.user.unidades.all()
    notificaciones = Notificacion.objects.filter(leido=False, unidad__in=unidades_usuario)
    data = [
        {
            'titulo': n.titulo,
            'mensaje': n.mensaje,
            'fecha': n.fecha_creado.strftime('%Y-%m-%d %H:%M'),
        }
        for n in notificaciones
    ]
    return JsonResponse({'notificaciones': data})

# notificaciones/views.py
def ultimas_notificaciones(request):
    unidades_usuario = request.user.unidades.all()
    notificaciones = Notificacion.objects.filter(leido=False, unidad__in=unidades_usuario).order_by('-fecha_creado')[:5]
    data = [
        {
            'titulo': n.titulo,
            'mensaje': n.mensaje,
            'fecha': n.fecha_creado.strftime('%Y-%m-%d %H:%M'),
        }
        for n in notificaciones
    ]
    return JsonResponse({'notificaciones': data})
