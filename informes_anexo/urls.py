from django.urls import path
from . import views

app_name = "informes_anexo"

urlpatterns = [
    # --- Las dos pantallas ---
    path("anexo14/", views.AnexoCatorceView.as_view(), name="anexo14"),
    path("anexo14a/", views.AnexoCatorceAView.as_view(), name="anexo14a"),
    path("anexo14b/", views.AnexoCatorceBView.as_view(), name="anexo14b"),

    # --- El contenido de UNA pestaña, que se pide por HTMX al pulsarla ---
    path("anexo14/unidad/<int:codigo>/", views.PanelUnidadAnexo14View.as_view(),
         name="anexo14_panel_unidad"),
    path("anexo14a/unidad/<int:codigo>/", views.PanelUnidadAnexo14AView.as_view(),
         name="anexo14a_panel_unidad"),
    path("anexo14b/unidad/<int:codigo>/", views.PanelUnidadAnexo14BView.as_view(),
         name="anexo14b_panel_unidad"),

    # --- Los tres libros ---
    # Una sola vista con el modo en la URL: lo único que cambia entre ellos es
    # qué hojas de unidad se escriben. `ambos` es el fichero que imita al
    # original de Capital Humano, con el 14 y el 14-A en el mismo libro.
    #
    # No hay exportación a PDF: el Anexo 14 la tenía y se retiró porque no se
    # usaba, y lo que se entrega al organismo es el libro de Excel.
    path("anexo14/excel/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_14}, name="anexo14_excel"),
    path("anexo14a/excel/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_14A}, name="anexo14a_excel"),
    # El 14-B va en libro APARTE: no entra en el combinado.
    path("anexo14b/excel/", views.ExportarAnexo14BExcelView.as_view(),
         name="anexo14b_excel"),
    path("anexo/excel/combinado/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_AMBOS}, name="anexo_excel_combinado"),
]
