from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from dashboard import views as dashboard_views
from dashboard import ventanas as dashboard_ventanas
from django.urls import path, include
from usuarios.views import CustomLoginView

urlpatterns = [
    # DASHBOARD PRINCIPAL
    path('', dashboard_views.DashboardView.as_view(), name='dashboard'),
    path('dashboard/piramide-edades/', dashboard_views.piramide_edades_json, name='dashboard_piramide_json'),
    path('dashboard/piramide-edades/detalle/', dashboard_views.piramide_detalle_html, name='dashboard_piramide_detalle'),
    path('dashboard/advertencias/', dashboard_views.advertencias_json, name='dashboard_advertencias_json'),
    path('dashboard/antiguedad/', dashboard_views.antiguedad_html, name='dashboard_antiguedad_html'),
    path('dashboard/antiguedad/detalle/', dashboard_views.antiguedad_detalle_html, name='dashboard_antiguedad_detalle'),
    path('dashboard/altas-bajas-mes/', dashboard_views.altas_bajas_mes_html, name='dashboard_altas_bajas_mes'),
    path('dashboard/salario/', dashboard_views.salario_desglose_html, name='dashboard_salario'),
    path('dashboard/cumpleanos/', dashboard_views.cumpleanos_html, name='dashboard_cumpleanos'),
    path('dashboard/recordatorios/', dashboard_views.recordatorios_html, name='dashboard_recordatorios'),
    path('dashboard/plazas/', dashboard_views.plazas_html, name='dashboard_plazas'),
    path('dashboard/plazas/<int:cargo_id>/ocupantes/', dashboard_views.plazas_ocupantes_html,
         name='dashboard_plazas_ocupantes'),
    # Ventanas de la Dashboard con «Ver más» y Excel (24-10-2026), ver dashboard/ventanas.py.
    path('dashboard/ventana/<slug:clave>/', dashboard_ventanas.ventana_html, name='dashboard_ventana'),
    path('dashboard/ventana/<slug:clave>/excel/', dashboard_ventanas.ventana_excel,
         name='dashboard_ventana_excel'),

    ## ---------------------------------------------------------
    # LA NUEVA APP DE INFORMES (Esta línea sustituye a todas las anteriores)
    # ---------------------------------------------------------
    path('informes/', include('informes.urls')),
    path('informe-inteligente/', include('informe_inteligente.urls')),
    path('informes-anexo/', include('informes_anexo.urls')),

    # ---------------------------------------------------------
    # MÓDULOS DE LA APLICACIÓN
    # ---------------------------------------------------------
    path('admin/', admin.site.urls),
    path('auditoria/', include('auditoria.urls')),
    path('bolsa/', include('bolsa.urls')),
    path('cierres/', include('cierres.urls')),
    path('contrato/', include('contratos.urls')),
    path('estructuras/', include('strorganizativa.urls')),
    path('config/', include('configuracion.urls')),
    path('nomencladores/', include('nomencladores.urls')),
    path('notificaciones/', include('notificaciones.urls')),
    path('progreso/', include('progreso.urls')),
    path('ranking/', include('ranking.urls')),
    path('prenomina/', include('prenomina.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('solicitudes/', include('solicitudes.urls')),
    path('soporte/', include('soporte.urls')),
    path('subsanacion/', include('subsanacion.urls')),
    
    # ---------------------------------------------------------
    # SISTEMA DE AUTENTICACIÓN
    #
    # Antes había aquí `include('django.contrib.auth.urls')`, que publica de
    # golpe SIETE rutas prefabricadas de Django. De ellas, Orbith solo usa
    # `login` y `logout`; las cinco de cambio y reseteo de contraseña quedaban
    # publicadas SIN su plantilla, así que devolvían TemplateDoesNotExist (error
    # 500). Y las de reseteo Django las marca accesibles sin iniciar sesión, de
    # modo que cualquiera en la red podía provocar ese error sin tener cuenta.
    #
    # No se crean esas plantillas porque el reseteo de Django funciona enviando
    # un correo, y Orbith es un sistema offline (EMAIL_BACKEND es el de consola,
    # sin EMAIL_HOST en ninguna parte): sería una función que aparenta funcionar
    # y no funciona. En Orbith el cambio de contraseña ya existe y es otro:
    # `usuarios.views.CambiarPasswordView`, desde «Mi Perfil» o, para un tercero,
    # desde el listado de usuarios.
    # ---------------------------------------------------------
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

]

# CONFIGURACIÓN PARA ARCHIVOS ESTÁTICOS Y MULTIMEDIA EN DESARROLLO
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)