from django.urls import path
from . import views

app_name = "informe_inteligente"

urlpatterns = [
    # Vista principal (index)
    path("", views.index, name="index"),

    # Endpoints HTMX / AJAX
    path("campos/<str:modelo_raiz>/", views.campos_del_modelo, name="campos_del_modelo"),
    path("vista-previa/", views.generar_vista_previa, name="generar_vista_previa"),
    path("evolucion/", views.datos_evolucion, name="datos_evolucion"),
    # Se consulta ANTES de exportar: dice si el informe cabe en un documento
    # y si trae demasiadas filas, para poder preguntar en vez de que el
    # usuario lo descubra con el fichero ya descargado.
    path("comprobar-exportacion/", views.comprobar_exportacion,
         name="comprobar_exportacion"),
    path("exportar-pdf/", views.exportar_pdf, name="exportar_pdf"),
    path("exportar-word/", views.exportar_word, name="exportar_word"),
    path("exportar-excel/", views.exportar_excel, name="exportar_excel"),
    path("guardar-favorito/", views.guardar_favorito, name="guardar_favorito"),
    path("favorito/<int:informe_id>/", views.cargar_favorito, name="cargar_favorito"),
    path("favorito/<int:informe_id>/editar/", views.editar_favorito, name="editar_favorito"),
    path("favorito/<int:informe_id>/compartir/", views.compartir_favorito, name="compartir_favorito"),
    path("compartido/<int:informe_id>/", views.ver_informe_compartido, name="ver_compartido"),
    path("favorito/<int:informe_id>/eliminar/", views.eliminar_favorito, name="eliminar_favorito"),
]
