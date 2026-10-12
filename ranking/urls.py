from django.urls import path

from . import views

urlpatterns = [
    path('panel/', views.panel_ranking, name='ranking_panel'),
    path('estadisticas/', views.estadisticas_uso, name='ranking_estadisticas'),
    path('estadisticas/usuario/<int:pk>/', views.detalle_usuario, name='ranking_detalle_usuario'),
    path('estadisticas/recordar/<str:unidad_id>/', views.recordar_cierre, name='ranking_recordar_cierre'),
]
