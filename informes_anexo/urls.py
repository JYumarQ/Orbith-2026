from django.urls import path
from . import views

app_name = "informes_anexo"

urlpatterns = [
    path("anexo14/", views.AnexoCatorceView.as_view(), name="anexo14"),
    path("anexo14/excel/", views.ExportarAnexo14ExcelView.as_view(), name="anexo14_excel"),
    path("anexo14/pdf/", views.ExportarAnexo14PDFView.as_view(), name="anexo14_pdf"),
]
