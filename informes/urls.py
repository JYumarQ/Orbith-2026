from django.urls import path
from . import views

urlpatterns = [
    # ---------------------------------------------------------
    # 1. INFORMES: CONSOLIDADO DE FUERZA DE TRABAJO
    # ---------------------------------------------------------
    path('economia/', views.InformeEconomiaView.as_view(), name='informe_economia'),
    path('economia/exportar-word/', views.ExportarConsolidadoWordView.as_view(), name='exportar_consolidado_word'),
    path('economia/exportar-pdf/', views.ExportarConsolidadoPDFView.as_view(), name='exportar_consolidado_pdf'),

    # ---------------------------------------------------------
    # 2. INFORMES: TRABAJADORES X UEB
    # ---------------------------------------------------------
    path('economia/trabajadores-ueb/', views.InformeTrabajadoresUEBView.as_view(), name='informe_trabajadores_ueb'),
    path('economia/trabajadores-ueb/exportar-word/', views.ExportarResumenUEBWordView.as_view(), name='exportar_resumen_ueb_word'),

    # ---------------------------------------------------------
    # 3. INFORMES: RESUMEN PUESTOS CLAVE
    # ---------------------------------------------------------
    path('puestos-clave/', views.InformePuestosClaveView.as_view(), name='informe_puestos_clave'),
    path('puestos-clave/exportar/word/', views.ExportarPuestosClaveWordView.as_view(), name='exportar_puestos_clave_word'),
    path('puestos-clave/exportar/pdf/', views.ExportarPuestosClavePDFView.as_view(), name='exportar_puestos_clave_pdf'),

    # ---------------------------------------------------------
    # 4. INFORMES: MISIONES INTERNACIONALES
    # ---------------------------------------------------------
    path('misiones/', views.InformeMisionesView.as_view(), name='informe_misiones'),

    # ---------------------------------------------------------
    # 5. INFORMES: PLAN MENSUAL DE TRABAJO (REGISTRO DIARIO)
    # ---------------------------------------------------------
    path('registro-diario/', views.RegistroDiarioView.as_view(), name='informe_registro_diario'),
    path('registro-diario/guardar-plan/', views.GuardarPlanDiarioView.as_view(), name='guardar_plan_diario'),
]