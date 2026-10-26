"""Rutas de Estructura Organizativa.

Los tres listados de página completa del sistema anterior (`list_cargos`,
`list_dptos`, `list_uniorg`) y sus buscadores (`search_cargos_view`,
`search_dpto_view`, `search_unidad_view`) se eliminaron: los sustituyó el
Gestor de Plantilla —la vista de tres columnas con HTMX (`gestor_plantilla` más
`htmx_load_*`)— y sus plantillas HTML ya se habían borrado, así que devolvían
`TemplateDoesNotExist` (error 500) a quien abriera la URL. Ninguna pantalla ni
ningún JavaScript del proyecto los llamaba.

Toda ruta que ESCRIBE queda cerrada al Observador en la propia vista, con
`RequiereEdicionMixin` (ver `strorganizativa/views.py`), y no aquí: así la
protección viaja con la vista aunque mañana se le añada otra ruta.
"""

from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required
from usuarios.decorators import admin_required
from usuarios.permisos_especiales import permiso_required

urlpatterns = [
    
    #CARGO
    path('add_cargo/', login_required(views.CargoPlantillaCreateView.as_view()), name='add_cargo'),
    path('updt_cargo/<pk>/', login_required(views.CargoPlantillaUpdateView.as_view()), name='updt_cargo'),
    path('del_cargoplantilla/<pk>/', login_required(views.CargoPlantillaDeleteView.as_view()), name='del_cargoplantilla'),
    path('cargar_cargos/', login_required(views.cargar_cargos), name='cargar_cargos'),
    
    #DPTO
    path('add_dpto/', login_required(views.DepartamentoCreateView.as_view()), name='add_dpto'),
    path('updt_dpto/<pk>/', login_required(views.DepartamentoUpdateView.as_view()), name='updt_dpto'),
    path('del_dpto/<pk>/', login_required(views.DepartamentoDeleteView.as_view()), name='del_dpto'), 
    path('cargar_dptos/', login_required(views.cargar_dptos), name='cargar_dptos'),
    
    # UNIDAD ORGANIZATIVA
    # Crear y eliminar unidades es competencia EXCLUSIVA del Administrador: no se pueden
    # ni solicitar. Editar sí puede pedirlo un Moderador, pero solo sobre las unidades que
    # tiene asignadas (se comprueba en `UnidadOrganizativaUpdateView.post`) y su envío se
    # convierte en solicitud.
    # Crear unidades: también el Moderador con «Gestor de plantilla completo» (25-10-2026).
    path('add_uniorg/', permiso_required('gestor_completo')(views.UnidadOrganizativaCreateView.as_view()), name='add_uniorg'),
    path('updt_uniorg/<pk>/', login_required(views.UnidadOrganizativaUpdateView.as_view()), name='updt_uniorg'),
    path('del_uniorg/<pk>/', admin_required(views.UnidadOrganizativaDeleteView.as_view()), name='del_uniorg'),
    
    path('categoria_ocupacional/', login_required(views.get_cat_ocup_from_ncargo), name='categoria_ocupacional'), 

    # === NUEVO GESTOR DE PLANTILLA (HTMX) ===
    path('gestor/', views.gestor_plantilla_view, name='gestor_plantilla'),

    # APIs HTMX (Fragmentos)
    path('htmx/departamentos/<int:unidad_id>/', views.htmx_load_departamentos, name='htmx_load_departamentos'),
    path('htmx/cargos/<int:dpto_id>/', views.htmx_load_cargos, name='htmx_load_cargos'),
    path('htmx/contratos/<int:cargo_id>/', views.htmx_load_contratos, name='htmx_load_contratos'),

    path('validar-orden-uniorg/', views.validar_orden_uniorg, name='validar_orden_uniorg'),
    path('validar-orden-dpto/', views.validar_orden_dpto, name='validar_orden_dpto'),
    path('validar_orden_cargo/', views.validar_orden_cargo, name='validar_orden_cargo'),
]

