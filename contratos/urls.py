from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [
    
    #*CONTRATO
    path('list_contrato/', login_required(views.ContratoListView.as_view()), name='list_contrato'),
    # contratos/urls.py
    path('add_contrato/<str:aspirante_id>/', login_required(views.ContratoCreateView.as_view()), name='add_contrato'),
    path('updt_contrato/<str:pk>/', login_required(views.ContratoUpdateView.as_view()), name='updt_contrato'),
    path('del_contrato/<str:pk>/', login_required(views.ContratoDeleteView.as_view()), name='del_contrato'),
    path('cargar_salarios/', login_required(views.cargar_salario), name='cargar_salarios'),
    path('search_contrato/', login_required(views.search_contratos), name='search_contrato'),
    
    #?REPORTES
    path('reporte/modelo_movimiento/<str:pk>/', login_required(views.ModeloMovimientoDocxView.as_view()), name='imprimir_modelo_movimiento'),
    

    #?Validaciones
    path('validar_datos_contrato/', login_required(views.validar_datos_contrato), name='validar_datos_contrato'),
    path('validar_plazas/', views.validar_plazas_cargo, name='validar_plazas_cargo'),

    path('ajax/cargar_departamentos/', login_required(views.cargar_departamentos), name='cargar_departamentos'),
    path('ajax/cargar_cargos/', login_required(views.cargar_cargos), name='cargar_cargos_contratos'),

    path('movimiento/solicitar/<pk>/', login_required(views.solicitar_movimiento_nomina), name='solicitar_movimiento'),

    # Agrega esta línea en urlpatterns
    # Agrega esta línea en urlpatterns
    path('movimiento_contrato/<pk>/', login_required(views.MovimientoUpdateView.as_view()), name='movimiento_contrato'),
    path('movimientos/nomina/', login_required(views.MovimientoNominaListView.as_view()), name='list_movimientos'),
    
    # --- RUTAS PARA EL WIZARD (FASE 3) ---
    # Registramos la misma vista con dos nombres para compatibilidad con el GET de Fase 1 y el POST de Fase 2
    path('wizard_movimiento/<str:aspirante_id>/', login_required(views.finalizar_contrato_wizard), name='wizard_movimiento_nomina'),
    path('finalizar_wizard/<str:aspirante_id>/', login_required(views.finalizar_contrato_wizard), name='finalizar_contrato_wizard'),
    
    path('ajax/historico/<int:aspirante_id>/', login_required(views.historico_trabajador), name='historico_trabajador'),

    path('ajax/datos_previos/', login_required(views.obtener_datos_previos), name='obtener_datos_previos'),

    path('ajax/cargar_roles/', login_required(views.cargar_roles), name='cargar_roles'),

    path('ajax/historico/detalle/<int:pk>/', login_required(views.movimiento_detalle_readonly), name='movimiento_detalle_readonly'),
    path('exportar/historico/pdf/<int:aspirante_id>/', login_required(views.ExportarHistoricoPDFView.as_view()), name='exportar_historico_pdf'),


    path('cargar-cargos-contrato/', views.cargar_cargos_contrato, name='cargar_cargos_contrato'),

    #? EXPORTACIONES
    path('exportar_excel/', login_required(views.exportar_contratos_excel), name='exportar_contratos_excel'),

    path('exportar_contrato/<int:pk>/', login_required(views.ExportarContratoWordView.as_view()), name='exportar_contrato_word')

]
