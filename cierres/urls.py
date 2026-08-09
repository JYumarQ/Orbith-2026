"""Rutas de Cierres.

Sin `app_name`, como el resto de módulos de negocio del proyecto
(`solicitudes/urls.py`, `informes/urls.py`): los `{% url %}` van sin namespace.
`login_required` ya lo aplica cada vista; los decoradores de rol están en
`permisos.py`.
"""

from django.urls import path

from . import views

urlpatterns = [
    # Consulta
    path('', views.index, name='list_cierres'),
    path('buscar/', views.buscar, name='buscar_cierres'),
    path('<int:unidad_id>/historial/', views.historial, name='historial_cierres'),
    path('detalle/<int:cierre_id>/', views.detalle, name='detalle_cierre'),

    # Acciones que invoca la toolbar del Gestor de Plantilla (responden JSON)
    path('<int:unidad_id>/declarar/', views.declarar, name='declarar_cierre'),
    path('<int:unidad_id>/reabrir/', views.reabrir, name='reabrir_cierre'),

    # Procesamiento manual, solo Administrador
    path('procesar/', views.procesar, name='procesar_cierres'),
]
