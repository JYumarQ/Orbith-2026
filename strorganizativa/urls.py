from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [
    
    #CARGO
    path('list_cargo/', login_required(views.CargoPlantillaListView.as_view()), name='list_cargos'),
    path('dpto/<int:dpto_id>/list_cargo/', login_required(views.CargoPlantillaListView.as_view()), name='list_cargos_x_dpto'),
    path('add_cargo/', login_required(views.CargoPlantillaCreateView.as_view()), name='add_cargo'),
    path('updt_cargo/<pk>/', login_required(views.CargoPlantillaUpdateView.as_view()), name='updt_cargo'),
    path('del_cargoplantilla/<pk>/', login_required(views.CargoPlantillaDeleteView.as_view()), name='del_cargoplantilla'),
    path('search_cargos_view/', login_required(views.search_cargos_view), name='search_cargos_view'), 
    path('cargar_cargos/', login_required(views.cargar_cargos), name='cargar_cargos'),
    
    #DPTO
    path('list_dpto/', login_required(views.DepartamentoListView.as_view()), name='list_dptos'),
    path('unidad/<int:unidad_id>/list_dpto/', login_required(views.DepartamentoListView.as_view()), name='list_dpto_x_unidad'),
    path('add_dpto/', login_required(views.DepartamentoCreateView.as_view()), name='add_dpto'),
    path('updt_dpto/<pk>/', login_required(views.DepartamentoUpdateView.as_view()), name='updt_dpto'),
    path('del_dpto/<pk>/', login_required(views.DepartamentoDeleteView.as_view()), name='del_dpto'), 
    path('search_dpto_view/', login_required(views.search_dpto_view), name='search_dpto_view'), 
    path('cargar_dptos/', login_required(views.cargar_dptos), name='cargar_dptos'),
    
    #UNIDAD ORGANIZATIVA
    path('list_uniorg/', login_required(views.UnidadOrganizativaListView.as_view()), name='list_uniorg'),
    path('add_uniorg/', login_required(views.UnidadOrganizativaCreateView.as_view()), name='add_uniorg'),
    path('updt_uniorg/<pk>/', login_required(views.UnidadOrganizativaUpdateView.as_view()), name='updt_uniorg'),
    path('del_uniorg/<pk>/', login_required(views.UnidadOrganizativaDeleteView.as_view()), name='del_uniorg'), 
    path('search_unidad_view/', login_required(views.search_unidades_views), name='search_unidad_view'), 
    
    path('categoria_ocupacional/', login_required(views.get_cat_ocup_from_ncargo), name='categoria_ocupacional'), 
]

