from django.urls import path

from . import views

app_name = 'subsanacion'

urlpatterns = [
    path('', views.index, name='index'),

    # Paneles (fragmentos HTMX de las pestañas)
    path('panel/dashboard/', views.panel_dashboard, name='panel_dashboard'),
    path('panel/hallazgos/', views.panel_hallazgos, name='panel_hallazgos'),
    path('panel/revisiones/', views.panel_revisiones, name='panel_revisiones'),
    path('panel/estadisticas/', views.panel_estadisticas, name='panel_estadisticas'),
    path('panel/analisis/', views.panel_analisis, name='panel_analisis'),

    # Exportaciones: respetan los mismos filtros y la misma búsqueda de la pantalla
    path('exportar/excel/', views.exportar_excel, name='exportar_excel'),
    path('exportar/pdf/', views.exportar_pdf, name='exportar_pdf'),

    # Hallazgos
    path('hallazgo/<int:pk>/', views.detalle_hallazgo, name='detalle_hallazgo'),
    path('hallazgo/<int:pk>/estado/', views.cambiar_estado, name='cambiar_estado'),

    # Cadena de análisis: una petición por categoría
    path('analisis/iniciar/', views.iniciar_analisis, name='iniciar_analisis'),
    path('analisis/<int:pk>/modulo/<str:clave>/', views.ejecutar_modulo, name='ejecutar_modulo'),
    path('analisis/<int:pk>/finalizar/', views.finalizar_analisis, name='finalizar_analisis'),
]
