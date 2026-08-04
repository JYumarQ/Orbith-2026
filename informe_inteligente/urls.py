from django.urls import path
from . import views

app_name = "informe_inteligente"

urlpatterns = [
    # Vista principal (index)
    path("", views.index, name="index"),

    # Endpoints HTMX / AJAX
    path("campos/<str:modelo_raiz>/", views.campos_del_modelo, name="campos_del_modelo"),
    path("vista-previa/", views.generar_vista_previa, name="generar_vista_previa"),
    path("guardar-favorito/", views.guardar_favorito, name="guardar_favorito"),
    path("favorito/<int:informe_id>/", views.cargar_favorito, name="cargar_favorito"),
    path("favorito/<int:informe_id>/eliminar/", views.eliminar_favorito, name="eliminar_favorito"),
]
