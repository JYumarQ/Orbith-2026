from django.urls import path

from . import views

app_name = "soporte"

urlpatterns = [
    path("reportar/", views.crear_reporte, name="crear_reporte"),
    # Accesible SIN iniciar sesión: la usa el enlace «¿Problemas para acceder?»
    # de la pantalla de login (ver la vista para las restricciones que lleva).
    path("ayuda-acceso/", views.crear_reporte_acceso, name="crear_reporte_acceso"),
    path("reportes/", views.lista_reportes, name="lista_reportes"),
    path("reportes/<int:pk>/estado/", views.cambiar_estado_reporte, name="cambiar_estado_reporte"),
    path("reportes/<int:pk>/eliminar/", views.eliminar_reporte, name="eliminar_reporte"),
]
