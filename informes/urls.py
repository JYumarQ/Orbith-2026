from django.urls import path
from . import views

urlpatterns = [
    # ---------------------------------------------------------
    # 1. INFORMES: CONSOLIDADO DE FUERZA DE TRABAJO
    # ---------------------------------------------------------
    path('economia/', views.InformeEconomiaView.as_view(), name='informe_economia'),
    path('economia/exportar-word/', views.ExportarConsolidadoWordView.as_view(), name='exportar_consolidado_word'),
    path('economia/exportar-pdf/', views.ExportarConsolidadoPDFView.as_view(), name='exportar_consolidado_pdf'),
    path('economia/exportar-excel/', views.ExportarConsolidadoExcelView.as_view(), name='exportar_consolidado_excel'),

    # ---------------------------------------------------------
    # 2. INFORMES: TRABAJADORES X UEB
    # ---------------------------------------------------------
    path('economia/trabajadores-ueb/', views.InformeTrabajadoresUEBView.as_view(), name='informe_trabajadores_ueb'),
    path('economia/trabajadores-ueb/exportar-word/', views.ExportarResumenUEBWordView.as_view(), name='exportar_resumen_ueb_word'),
    path('economia/trabajadores-ueb/exportar-pdf/', views.ExportarResumenUEBPDFView.as_view(), name='exportar_resumen_ueb_pdf'),
    path('economia/trabajadores-ueb/exportar-excel/', views.ExportarResumenUEBExcelView.as_view(), name='exportar_resumen_ueb_excel'),

    # ---------------------------------------------------------
    # 3. INFORMES: RESUMEN PUESTOS CLAVE
    # ---------------------------------------------------------
    path('puestos-clave/', views.InformePuestosClaveView.as_view(), name='informe_puestos_clave'),
    path('puestos-clave/exportar/word/', views.ExportarPuestosClaveWordView.as_view(), name='exportar_puestos_clave_word'),
    path('puestos-clave/exportar/pdf/', views.ExportarPuestosClavePDFView.as_view(), name='exportar_puestos_clave_pdf'),
    path('puestos-clave/exportar/excel/', views.ExportarPuestosClaveExcelView.as_view(), name='exportar_puestos_clave_excel'),

    # ---------------------------------------------------------
    # 4. INFORMES: MISIONES INTERNACIONALES
    # ---------------------------------------------------------
    path('misiones/', views.InformeMisionesView.as_view(), name='informe_misiones'),
    path('misiones/exportar-word/', views.ExportarMisionesWordView.as_view(), name='exportar_misiones_word'),
    path('misiones/exportar-pdf/', views.ExportarMisionesPDFView.as_view(), name='exportar_misiones_pdf'),
    path('misiones/exportar-excel/', views.ExportarMisionesExcelView.as_view(), name='exportar_misiones_excel'),

    # ---------------------------------------------------------
    # 5. INFORMES: PLAN MENSUAL DE TRABAJO (REGISTRO DIARIO)
    # ---------------------------------------------------------
    path('registro-diario/', views.RegistroDiarioView.as_view(), name='informe_registro_diario'),
    path('registro-diario/exportar-word/', views.ExportarRegistroDiarioWordView.as_view(), name='exportar_registro_diario_word'),
    path('registro-diario/exportar-pdf/', views.ExportarRegistroDiarioPDFView.as_view(), name='exportar_registro_diario_pdf'),
    path('registro-diario/exportar-excel/', views.ExportarRegistroDiarioExcelView.as_view(), name='exportar_registro_diario_excel'),
    path('registro-diario/guardar-plan/', views.GuardarPlanDiarioView.as_view(), name='guardar_plan_diario'),
    path('motivos-contratos/', views.InformeMotivosContratoView.as_view(), name='informe_motivos_contrato'),
    path('motivos-contratos/exportar-word/', views.ExportarMotivosWordView.as_view(), name='exportar_motivos_word'),
    path('motivos-contratos/exportar-pdf/', views.ExportarMotivosPDFView.as_view(), name='exportar_motivos_pdf'),
    path('motivos-contratos/exportar-excel/', views.ExportarMotivosExcelView.as_view(), name='exportar_motivos_excel'),

    # ---------------------------------------------------------
    # 7. INFORMES: ALTAS Y BAJAS DEL MES (modelo de la UNE)
    # ---------------------------------------------------------
    path('altas-bajas/', views.InformeAltasBajasView.as_view(), name='informe_altas_bajas'),
    path('altas-bajas/exportar-word/', views.ExportarAltasBajasWordView.as_view(), name='exportar_altas_bajas_word'),
    path('altas-bajas/exportar-pdf/', views.ExportarAltasBajasPDFView.as_view(), name='exportar_altas_bajas_pdf'),
    path('altas-bajas/exportar-excel/', views.ExportarAltasBajasExcelView.as_view(), name='exportar_altas_bajas_excel'),


    
]