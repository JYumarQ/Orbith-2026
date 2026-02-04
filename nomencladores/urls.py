from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required
from usuarios.decorators import admin_required

urlpatterns = [
    
    #NCARGO
    path('list_ncargo/', login_required(views.NCargoListView.as_view()), name='list_ncargo'),
    path('add_ncargo/', login_required(views.NCargoCreateView.as_view()), name='add_ncargo'),
    path('updt_ncargo/<pk>/', login_required(views.NCargoUpdateView.as_view()), name='updt_ncargo'),
    path('del_ncargo/<pk>/', login_required(views.NCargoDeleteView.as_view()), name='del_ncargo'),
    path('salarios/modal/', login_required(views.crear_salarios_por_grupo), name='agregar_salarios_modal'),
    path('api/grupo/<int:id>/', views.obtener_grupo, name='obtener_grupo'),
    path('cargar_esp/', login_required(views.cargar_esp), name='cargar_esp'),
    path('cargar_municipios/', login_required(views.cargar_municipios), name='cargar_municipios'),
    path('modal/tabla/', views.tabla_salarios_modal, name='agregar_salarios_modal_tabla'),

    # CRUD NTridente
    path('api/tridentes/', login_required(views.tridente_create), name='tridente-create'),
    path('api/tridentes/<int:pk>/', login_required(views.tridente_update), name='tridente-update'),
    path('api/tridentes/<int:pk>/delete/', login_required(views.tridente_delete), name='tridente-delete'),

    # CRUD NRol
    path('api/roles/', login_required(views.rol_create), name='rol-create'),
    path('api/roles/<int:pk>/', login_required(views.rol_update), name='rol-update'),
    path('api/roles/<int:pk>/delete/', login_required(views.rol_delete), name='rol-delete'),

    # CRUD NGrupoEscala
    path('api/grupos/', login_required(views.grupo_create), name='grupo-create'),
    path('api/grupos/<int:pk>/', login_required(views.grupo_update), name='grupo-update'),
    path('api/grupos/<int:pk>/delete/', login_required(views.grupo_delete), name='grupo-delete'),

    # CRUD NProvincia
    path('api/provincias/', admin_required(views.provincia_create), name='provincia-create'),
    path('api/provincias/<int:pk>/', admin_required(views.provincia_update), name='provincia-update'),
    path('api/provincias/<int:pk>/delete/', admin_required(views.provincia_delete), name='provincia-delete'),


    # CRUD NMunicipio
    path('api/municipios/', admin_required(views.municipio_create), name='municipio-create'),
    path('api/municipios/<int:pk>/', admin_required(views.municipio_update), name='municipio-update'),
    path('api/municipios/<int:pk>/delete/', admin_required(views.municipio_delete), name='municipio-delete'),
    # ---------- TIEMPO DE TRABAJO ----------
    path('api/horarios/',          views.horario_create,  name='horario_create'),
    path('api/horarios/<int:pk>/', views.horario_update,  name='horario_update'),
    path('api/horarios/<int:pk>/delete/', views.horario_delete, name='horario_delete'),

    path('api/jornadas/',          views.jornada_create,  name='jornada_create'),
    path('api/jornadas/<int:pk>/', views.jornada_update,  name='jornada_update'),
    path('api/jornadas/<int:pk>/delete/', views.jornada_delete, name='jornada_delete'),

    path('api/causas/',            views.causa_create,    name='causa_create'),
    path('api/causas/<int:pk>/',   views.causa_update,    name='causa_update'),
    path('api/causas/<int:pk>/delete/',   views.causa_delete,   name='causa_delete'),

    # ---------- LABORALES Y PROFESIONALES ----------
    path('api/condiciones/', views.condicion_create, name='condicion_create'),
    path('api/condiciones/<int:pk>/', views.condicion_update, name='condicion_update'),
    path('api/condiciones/<int:pk>/delete/', views.condicion_delete, name='condicion_delete'),

    path('api/especialidades/', views.especialidad_create, name='especialidad_create'),
    path('api/especialidades/<int:pk>/', views.especialidad_update, name='especialidad_update'),
    path('api/especialidades/<int:pk>/delete/', views.especialidad_delete, name='especialidad_delete'),

    # ---------- CRUD NCargo API ----------
    path('api/cargos/', views.cargo_create, name='cargo-create'),
    path('api/cargos/<int:pk>/', views.cargo_update, name='cargo-update'),
    path('api/cargos/<int:pk>/delete/', views.cargo_delete, name='cargo-delete'),

    # ---------- Buscar cargos ----------
    path('search_cargos/', views.search_cargos, name='search_cargos'),
]