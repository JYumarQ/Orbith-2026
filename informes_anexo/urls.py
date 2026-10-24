from django.urls import path
from . import views

app_name = "informes_anexo"

urlpatterns = [
    # --- Las dos pantallas ---
    path("anexo17/", views.AnexoDiecisieteView.as_view(), name="anexo17"),
    path("anexo17_1/", views.AnexoDiecisieteUnoView.as_view(), name="anexo17_1"),
    path("anexo17_2/", views.AnexoDiecisieteDosView.as_view(), name="anexo17_2"),

    # --- El contenido de UNA pestaña, que se pide por HTMX al pulsarla ---
    path("anexo17/unidad/<int:codigo>/", views.PanelUnidadAnexo17View.as_view(),
         name="anexo17_panel_unidad"),
    path("anexo17_1/unidad/<int:codigo>/", views.PanelUnidadAnexo17_1View.as_view(),
         name="anexo17_1_panel_unidad"),
    path("anexo17_2/unidad/<int:codigo>/", views.PanelUnidadAnexo17_2View.as_view(),
         name="anexo17_2_panel_unidad"),

    # --- Los tres libros ---
    # Una sola vista con el modo en la URL: lo único que cambia entre ellos es
    # qué hojas de unidad se escriben. `ambos` es el fichero que imita al
    # original de Capital Humano, con el 17 y el 17.1 en el mismo libro.
    #
    # No hay exportación a PDF: el Anexo 17 la tenía y se retiró porque no se
    # usaba, y lo que se entrega al organismo es el libro de Excel.
    path("anexo17/excel/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_17}, name="anexo17_excel"),
    path("anexo17_1/excel/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_17_1}, name="anexo17_1_excel"),
    # El 17.2 va en libro APARTE: no entra en el combinado.
    path("anexo17_2/excel/", views.ExportarAnexo17_2ExcelView.as_view(),
         name="anexo17_2_excel"),
    path("anexo/excel/combinado/", views.ExportarAnexoExcelView.as_view(),
         {"modo": views.MODO_AMBOS}, name="anexo_excel_combinado"),
]
