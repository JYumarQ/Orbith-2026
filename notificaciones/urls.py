from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [
    path('notificaciones/json/', login_required(views.notificaciones_json), name='notificaciones_json'),
    path('notificaciones/ultimas/', login_required(views.ultimas_notificaciones), name='ultimas_notificaciones'),
]
