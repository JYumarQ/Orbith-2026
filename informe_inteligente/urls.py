from django.urls import path
from . import views

app_name = "informe_inteligente"

urlpatterns = [
    # Vista principal (index)
    path("", views.index, name="index"),
    
    # Endpoints HTMX
    path("campos/<str:modelo_raiz>/", views.campos_del_modelo, name="campos_del_modelo"),
    path("vista-previa/", views.generar_vista_previa, name="generar_vista_previa"),
    path("guardar-favorito/", views.guardar_favorito, name="guardar_favorito"),
]