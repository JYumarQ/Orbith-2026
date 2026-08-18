from django.urls import path

from . import views

urlpatterns = [
    path('panel/', views.panel_guia, name='progreso_panel'),
    path('marcar-vistas/', views.marcar_vistas, name='progreso_marcar_vistas'),
    path('tarea/<slug:codigo>/', views.tarea_guiada, name='progreso_tarea_guiada'),
]
