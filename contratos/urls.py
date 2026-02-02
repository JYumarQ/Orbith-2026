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
    path('contratos/reporte/contratos/', login_required(views.ContratoPDFView.as_view()), name='contratos_pdf'),
    path('contratos/reporte/ncontrato/<str:no_expediente>/', login_required(views.PrintContratoPDFView.as_view()), name='ncontrato_pdf'),

    #?Validaciones
    path('validar_datos_contrato/', login_required(views.validar_datos_contrato), name='validar_datos_contrato'),
    path('validar_plazas/', views.validar_plazas_cargo, name='validar_plazas_cargo'),

    path('ajax/cargar_departamentos/', login_required(views.cargar_departamentos), name='cargar_departamentos'),
    path('ajax/cargar_cargos/', login_required(views.cargar_cargos), name='cargar_cargos'),

    path('movimiento/solicitar/<pk>/', login_required(views.solicitar_movimiento_nomina), name='solicitar_movimiento'),

    # Agrega esta línea en urlpatterns
    path('movimiento_contrato/<pk>/', login_required(views.MovimientoUpdateView.as_view()), name='movimiento_contrato'),
    path('movimientos/nomina/', login_required(views.MovimientoNominaListView.as_view()), name='list_movimientos'),
]
