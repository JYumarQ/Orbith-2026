"""Rutas de Nomencladores.

Los nomencladores se gestionan desde Configuración → Parámetros Generales, que es una
pantalla exclusiva del Administrador. Hasta ahora eso solo se aplicaba en el menú lateral:
las APIs quedaban abiertas a cualquier usuario autenticado, así que un Moderador podía
crear, editar o borrar cualquier nomenclador con una petición directa —incluidos los
NCargo, que son justamente lo que ahora debe pedirse por Solicitud—.

Criterio aplicado: **toda ruta que escriba lleva `admin_required`**. Las de solo lectura
se dejan con `login_required` porque las consumen otros módulos que sí usan Moderadores
(las cascadas de especialidades y municipios de los filtros de Contratos y Aspirantes, o
la información de tipo de contrato del formulario de alta); cerrarlas rompería esas
pantallas sin cerrar ningún agujero, porque no modifican nada.
"""

from django.contrib.auth.decorators import login_required
from django.urls import path

from usuarios.permisos_especiales import permiso_required

# Administrador, o Moderador con el permiso especial «Nomencladores y parámetros»
# (25-10-2026, ver `usuarios/permisos_especiales.py`).
admin_required = permiso_required('nomencladores')

from . import views, views_importes, views_orden
from .proteccion import json_seguro


def api(vista):
    """Ruta de escritura JSON: permiso de nomencladores y red de seguridad (3.8.2):
    ningún fallo llega a la pantalla como error técnico («Unexpected token»)."""
    return admin_required(json_seguro(vista))

urlpatterns = [

    # ---------- NCargo ----------
    # La pantalla de página completa de Cargos (`list_ncargo` y su CRUD) se eliminó:
    # estaba rota en tres sitios a la vez —la vista consultaba `familia` y `activo`,
    # dos campos que `NCargo` ya no tiene desde que la relación con las familias pasó
    # a ser Many-to-Many, y la plantilla llamaba a una ruta `search_cargos` que no
    # existe—, así que devolvía un error 500 a cualquiera, Administrador incluido.
    # Ninguna pantalla de la interfaz enlazaba con ella y duplicaba el trabajo de
    # Configuración → Familias de Cargos, que sí funciona.
    #
    # `NCargoForm` NO se tocó: sigue vivo y lo usa el módulo de Solicitudes para el
    # flujo de proponer un cargo nuevo (ver `solicitudes/operaciones.py`). Los cargos
    # se crean y editan desde el editor en línea de Configuración (`api/cargos/`).

    path('salarios/modal/', admin_required(views.crear_salarios_por_grupo), name='agregar_salarios_modal'),
    path('api/grupo/<int:id>/', login_required(views.obtener_grupo), name='obtener_grupo'),

    # Cascadas de solo lectura que consumen los filtros de Contratos y Aspirantes.
    path('cargar_esp/', login_required(views.cargar_esp), name='cargar_esp'),
    path('cargar_municipios/', login_required(views.cargar_municipios), name='cargar_municipios'),
    path('modal/tabla/', login_required(views.tabla_salarios_modal), name='agregar_salarios_modal_tabla'),

    # ---------- CRUD NTridente ----------
    path('api/tridentes/', api(views.tridente_create), name='tridente-create'),
    path('api/tridentes/<int:pk>/', api(views.tridente_update), name='tridente-update'),
    path('api/tridentes/<int:pk>/delete/', api(views.tridente_delete), name='tridente-delete'),

    # ---------- CRUD NRol ----------
    path('api/roles/', api(views.rol_create), name='rol-create'),
    path('api/roles/<int:pk>/', api(views.rol_update), name='rol-update'),
    path('api/roles/<int:pk>/delete/', api(views.rol_delete), name='rol-delete'),

    # ---------- CRUD NGrupoEscala ----------
    path('api/grupos/', api(views.grupo_create), name='grupo-create'),
    path('api/grupos/<int:pk>/', api(views.grupo_update), name='grupo-update'),
    path('api/grupos/<int:pk>/delete/', api(views.grupo_delete), name='grupo-delete'),
    path('grupos_escala/tabla/', login_required(views.grupos_escala_tabla_parcial), name='grupos_escala_tabla'),

    # ---------- CRUD NProvincia ----------
    path('api/provincias/', api(views.provincia_create), name='provincia-create'),
    path('api/provincias/<int:pk>/', api(views.provincia_update), name='provincia-update'),
    path('api/provincias/<int:pk>/delete/', api(views.provincia_delete), name='provincia-delete'),
    path('api/verificar-siglas/', login_required(views.verificar_siglas), name='verificar_siglas'),

    # ---------- Modal y guardado de grupos ----------
    path('modal/grupo/', admin_required(views.grupo_escala_modal), name='grupo_escala_modal'),
    path('modal/grupo/<int:pk>/', admin_required(views.grupo_escala_modal), name='grupo_escala_modal_edit'),
    path('api/grupos/save/', api(views.grupo_escala_save), name='grupo_escala_save'),
    path('api/grupos/<int:pk>/save/', api(views.grupo_escala_save), name='grupo_escala_save_edit'),

    # ---------- CRUD NMunicipio ----------
    path('api/municipios/', api(views.municipio_create), name='municipio-create'),
    path('api/municipios/<int:pk>/', api(views.municipio_update), name='municipio-update'),
    path('api/municipios/<int:pk>/delete/', api(views.municipio_delete), name='municipio-delete'),
    path('api/provincia/<int:prov_id>/municipios_tabla/', login_required(views.municipios_provincia_tabla), name='municipios_provincia_tabla'),

    # ---------- Tiempo de trabajo ----------
    # Las rutas de horarios y jornadas se eliminaron con sus modelos: no tenían
    # interfaz que las llamara. El tiempo de trabajo vive en Pre-Nómina → Calendario.
    path('api/causas/', api(views.causa_create), name='causa_create'),
    path('api/causas/<int:pk>/', api(views.causa_update), name='causa_update'),
    path('api/causas/<int:pk>/delete/', api(views.causa_delete), name='causa_delete'),

    # ---------- Laborales y profesionales ----------
    path('api/condiciones/', api(views.condicion_create), name='condicion_create'),
    path('api/condiciones/update/<int:pk>/', api(views.condicion_update), name='condicion_update'),
    path('api/condiciones/<int:pk>/', api(views.condicion_update), name='condicion_update'),
    path('api/condiciones/<int:pk>/delete/', api(views.condicion_delete), name='condicion_delete'),

    path('api/especialidades/', api(views.especialidad_create), name='especialidad_create'),
    path('api/especialidades/<int:pk>/', api(views.especialidad_update), name='especialidad_update'),
    path('api/especialidades/<int:pk>/delete/', api(views.especialidad_delete), name='especialidad_delete'),

    # ---------- CRUD NCargo API ----------
    # Es el editor en línea real de la tabla de cargos de Configuración. Sin este cierre,
    # un Moderador podría seguir creando y editando NCargo directamente y el flujo de
    # Solicitud sería evitable.
    path('api/cargos/', api(views.cargo_create), name='cargo-create'),
    path('api/cargos/<int:pk>/', api(views.cargo_update), name='cargo-update'),
    path('api/cargos/<int:pk>/delete/', api(views.cargo_delete), name='cargo-delete'),

    path('salarios/editar/<int:grupo_id>/', admin_required(views.editar_salarios_grupo), name='editar_salarios'),
    path('salarios/eliminar/<int:grupo_id>/', admin_required(views.eliminar_salarios_grupo), name='eliminar_salarios'),

    # ---------- Familias de cargos ----------
    path('api/familias/create/', api(views.api_familia_create), name='api_familia_create'),
    path('api/familias/<int:pk>/delete/', api(views.api_familia_delete), name='api_familia_delete'),
    path('api/cargos/move/', api(views.api_cargo_move), name='api_cargo_move'),
    path('api/cargos/move-bulk/', api(views.api_cargo_move_bulk), name='api_cargo_move_bulk'),
    path('api/familias/<int:pk>/update/', api(views.api_familia_update), name='api_familia_update'),
    # `api/familias/contexto/` se eliminó con su vista: ninguna pantalla la usaba y
    # no podía funcionar (campo inexistente + plantilla que no existe). Ver la nota
    # en `views.py`, donde estaba `api_get_contexto_familias`.

    # ---------- CRUD Tipo Familia ----------
    path('api/tipos-familia/create/', api(views.tipo_familia_create), name='tipo_familia_create'),
    path('api/tipos-familia/<int:pk>/delete/', api(views.tipo_familia_delete), name='tipo_familia_delete'),

    # ---------- CRUD NNivelPreparacion ----------
    path('api/niveles-preparacion/', api(views.nivel_preparacion_create), name='nivel_preparacion_create'),
    path('api/niveles-preparacion/<int:pk>/', api(views.nivel_preparacion_update), name='nivel_preparacion_update'),
    path('api/niveles-preparacion/<int:pk>/delete/', api(views.nivel_preparacion_delete), name='nivel_preparacion_delete'),

    # ---------- CRUD Tipo de Contrato ----------
    path('api/tipo_contrato/create/', api(views.tipo_contrato_create), name='tipo_contrato_create'),
    path('api/tipo_contrato/<int:pk>/update/', api(views.tipo_contrato_update), name='tipo_contrato_update'),
    path('api/tipo_contrato/<int:pk>/delete/', api(views.tipo_contrato_delete), name='tipo_contrato_delete'),
    path('api/tipo_contrato/<int:pk>/toggle_plaza/', api(views.tipo_contrato_toggle_plaza), name='tipo_contrato_toggle_plaza'),
    path('api/tipo_contrato/<int:pk>/toggle_motivo/', api(views.tipo_contrato_toggle_motivo), name='tipo_contrato_toggle_motivo'),
    path('api/tipo_contrato/<int:pk>/toggle_adiestrado/', api(views.toggle_tipo_adiestrado), name='toggle_tipo_adiestrado'),
    # Solo lectura: la consume el formulario de alta de contrato, que sí usan Moderadores.
    path('api/tipo_contrato/<int:pk>/info/', login_required(views.tipo_contrato_info), name='tipo_contrato_info'),

    # ---------- CRUD Motivo de Contrato ----------
    path('api/motivo_contrato/create/', api(views.motivo_contrato_create), name='motivo_contrato_create'),
    path('api/motivo_contrato/<int:pk>/update/', api(views.motivo_contrato_update), name='motivo_contrato_update'),
    path('api/motivo_contrato/<int:pk>/delete/', api(views.motivo_contrato_delete), name='motivo_contrato_delete'),

    # ---------- CRUD Tipos de Unidad Organizativa ----------
    path('api/tipo_unidad/guardar/', api(views.guardar_tipo_unidad), name='guardar_tipo_unidad'),
    path('api/tipo_unidad/<int:pk>/eliminar/', api(views.eliminar_tipo_unidad), name='eliminar_tipo_unidad'),

    # ---------- Importes del contrato: Maestría, Doctorado, Instructor y CNCI ----------
    # Las cuatro tarjetas de «Laborales y Profesionales» que alimentan los campos
    # de importe del contrato. Van con el patrón de tarjeta + modal de Pre-Nómina
    # (ver `views_importes.py`), no con el editor en línea del resto de esta
    # pantalla. `admin_required` lo ponen las propias vistas.
    path('importes/<str:slug>/tarjeta/', views_importes.tarjeta, name='importe_tarjeta'),
    path('importes/<str:slug>/nuevo/', views_importes.guardar, name='importe_nuevo'),
    path('importes/<str:slug>/<int:pk>/editar/', views_importes.guardar, name='importe_editar'),
    path('importes/<str:slug>/<int:pk>/eliminar/', views_importes.eliminar, name='importe_eliminar'),

    # ---------- Orden por arrastre (3.8.2) ----------
    path('api/orden/<str:slug>/', api(views_orden.guardar_orden), name='nomenclador_orden'),

    # ---------- Nocturnidad ----------
    path('api/nocturnidad/create/', api(views.nocturnidad_create), name='nocturnidad_create'),
    path('api/nocturnidad/delete/<int:pk>/', api(views.nocturnidad_delete), name='nocturnidad_delete'),
]
