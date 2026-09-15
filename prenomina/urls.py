"""Rutas de Pre-Nómina.

Criterio, el mismo que documenta `nomencladores/urls.py`: **toda ruta que
escriba lleva su decorador de rol**. Aquí van más lejos y también las de lectura
lo llevan, porque las tarjetas de configuración pintan datos que solo el
Administrador debe ver.

`LoginRequiredMiddleware` ya exige sesión en todo el proyecto; los decoradores de
`permisos.py` deciden el rol, no la autenticación.

Los slugs de `<str:tipo>` se validan contra el diccionario `NOMENCLADORES` de
`views.py`, no contra la base de datos: un slug inventado da 404 sin llegar a
tocar ningún modelo.
"""

from django.urls import path

from . import views, views_calendario, views_plantilla

app_name = 'prenomina'

urlpatterns = [
    # ---------- Calendario (tres tarjetas) ----------
    # Van antes que `path('', ...)` y que `<int:pk>/` por claridad, no por
    # necesidad: todas cuelgan del prefijo fijo `calendario/`, que nunca puede
    # confundirse con el `<int:pk>` de un reporte.
    path('calendario/', views_calendario.calendario, name='calendario'),
    path('asignacion-trabajadores/', views_calendario.asignacion_trabajadores,
         name='asignacion_trabajadores'),

    # ---------- Mis Plantillas ----------
    path('plantillas/', views_plantilla.plantillas, name='plantillas'),
    path('plantillas/lista/', views_plantilla.lista_plantillas,
         name='lista_plantillas'),
    path('plantillas/validar/', views_plantilla.validar_plantilla,
         name='validar_plantilla'),
    path('plantillas/nueva/', views_plantilla.guardar_plantilla,
         name='nueva_plantilla'),
    path('plantillas/<int:pk>/editar/', views_plantilla.guardar_plantilla,
         {'modo': 'editar'}, name='editar_plantilla'),
    path('plantillas/<int:pk>/duplicar/', views_plantilla.guardar_plantilla,
         {'modo': 'duplicar'}, name='duplicar_plantilla'),
    path('plantillas/<int:pk>/eliminar/', views_plantilla.eliminar_plantilla,
         name='eliminar_plantilla'),
    path('plantillas/<int:pk>/previa/', views_plantilla.previa_plantilla,
         name='previa_plantilla'),
    path('calendario/tarjeta-calendarios/',
         views_calendario.tarjeta_calendarios, name='tarjeta_calendarios'),
    path('calendario/tarjeta-periodo/',
         views_calendario.tarjeta_periodo, name='tarjeta_periodo'),
    path('calendario/tarjeta-trabajadores/',
         views_calendario.tarjeta_trabajadores, name='tarjeta_trabajadores'),

    path('calendario/nuevo/', views_calendario.guardar_calendario,
         name='nuevo_calendario'),
    path('calendario/<int:pk>/editar/', views_calendario.guardar_calendario,
         name='editar_calendario'),
    path('calendario/<int:pk>/eliminar/', views_calendario.eliminar_calendario,
         name='eliminar_calendario'),
    path('calendario/<int:pk>/desactivar/',
         views_calendario.desactivar_calendario, name='desactivar_calendario'),

    path('calendario/periodos/nuevo/', views_calendario.nuevo_periodo,
         name='nuevo_periodo'),
    path('calendario/periodos/<int:pk>/eliminar/',
         views_calendario.eliminar_periodo, name='eliminar_periodo'),
    path('calendario/periodos/<int:pk>/seleccionar/',
         views_calendario.seleccionar_calendarios, name='seleccionar_calendarios'),
    path('calendario/detalles/<int:pk>/horas/', views_calendario.guardar_horas,
         name='guardar_horas'),
    path('calendario/detalles/<int:pk>/quitar/', views_calendario.quitar_detalle,
         name='quitar_detalle'),

    path('calendario/asignar/', views_calendario.asignar_calendario,
         name='asignar_calendario'),
    path('calendario/desasignar/', views_calendario.quitar_asignacion,
         name='quitar_asignacion'),

    # ---------- Configuración: tarjetas de Parámetros Generales ----------
    path('nomencladores/<str:tipo>/tarjeta/',
         views.tarjeta, name='tarjeta_nomenclador'),
    path('nomencladores/<str:tipo>/nuevo/',
         views.guardar, name='nuevo_nomenclador'),
    path('nomencladores/<str:tipo>/<int:pk>/editar/',
         views.guardar, name='editar_nomenclador'),
    path('nomencladores/<str:tipo>/<int:pk>/eliminar/',
         views.eliminar, name='eliminar_nomenclador'),
    path('nomencladores/validar-formula/',
         views.validar_formula, name='validar_formula'),

    # ---------- Reportes de pago ----------
    path('', views.lista_reportes, name='lista_reportes'),
    path('buscar/', views.buscar_reportes, name='buscar_reportes'),
    path('nuevo/', views.nuevo_reporte, name='nuevo_reporte'),
    # Bloque del período dentro del modal de alta. Se repinta al cambiar la
    # unidad, el año o el mes, porque de esos tres depende qué quincena toca y,
    # con ella, las fechas del período.
    path('nuevo/periodo/', views.periodo_reporte, name='periodo_reporte'),
    path('cerrar-mes/', views.cerrar_mes, name='cerrar_mes'),
    path('<int:pk>/cerrar/', views.cerrar_reporte, name='cerrar_reporte'),
    path('<int:pk>/reabrir/', views.reabrir_reporte, name='reabrir_reporte'),

    # ---------- Detalle: la rejilla ----------
    path('<int:pk>/', views.detalle_reporte, name='detalle_reporte'),
    # Sustituye al antiguo `configurar_conceptos`: los conceptos ya no se marcan
    # aquí uno a uno, se aplican desde una plantilla (Mis Plantillas).
    path('<int:pk>/plantilla/', views_plantilla.cambiar_plantilla,
         name='cambiar_plantilla'),
    path('<int:pk>/exportar/', views.exportar_reporte, name='exportar_reporte'),
    path('<int:pk>/importar/', views.importar_reporte, name='importar_reporte'),
    path('<int:pk>/trabajadores/agregar/',
         views.agregar_trabajador, name='agregar_trabajador'),
    path('<int:pk>/trabajadores/<int:trabajador_pk>/',
         views.fila_trabajador, name='fila_trabajador'),
    path('<int:pk>/trabajadores/<int:trabajador_pk>/valores/',
         views.valores_trabajador, name='valores_trabajador'),
    path('<int:pk>/trabajadores/<int:trabajador_pk>/quitar/',
         views.quitar_trabajador, name='quitar_trabajador'),
]
