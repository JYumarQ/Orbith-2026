from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [
    path('notificaciones/json/', login_required(views.notificaciones_json), name='notificaciones_json'),
    path('notificaciones/ultimas/', login_required(views.ultimas_notificaciones), name='ultimas_notificaciones'),
    path('notificaciones/<int:pk>/leer/', views.marcar_leida, name='notificacion_marcar_leida'),
    path('notificaciones/leer-todas/', views.marcar_todas_leidas, name='notificaciones_marcar_todas_leidas'),
    path('notificaciones/lista/', login_required(views.lista_notificaciones), name='lista_notificaciones'),
    path('notificaciones/panel-advertencias/', views.panel_advertencias, name='panel_advertencias'),
    path('notificaciones/panel-recordatorios/', views.panel_recordatorios, name='panel_recordatorios'),
    path('notificaciones/buscar-incidencias/', views.buscar_incidencias, name='buscar_incidencias'),
    path('notificaciones/recordatorios/actualizar/', views.actualizar_recordatorios, name='actualizar_recordatorios'),
    path('notificaciones/<int:pk>/descartar/', views.descartar_advertencia, name='descartar_advertencia'),
    path('notificaciones/<int:pk>/reactivar/', views.reactivar_advertencia, name='reactivar_advertencia'),
    path('notificaciones/recordatorios/crear/', views.recordatorio_crear, name='recordatorio_crear'),
    path('notificaciones/recordatorios/<int:pk>/completar/', views.recordatorio_completar, name='recordatorio_completar'),
]
