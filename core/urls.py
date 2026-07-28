from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from dashboard import views as dashboard_views
from django.urls import path, include
from usuarios.views import CustomLoginView

urlpatterns = [
    # DASHBOARD PRINCIPAL
    path('', dashboard_views.DashboardView.as_view(), name='dashboard'),
    
    ## ---------------------------------------------------------
    # LA NUEVA APP DE INFORMES (Esta línea sustituye a todas las anteriores)
    # ---------------------------------------------------------
    path('informes/', include('informes.urls')),
    path('informe-inteligente/', include('informe_inteligente.urls')),

    # ---------------------------------------------------------
    # MÓDULOS DE LA APLICACIÓN
    # ---------------------------------------------------------
    path('admin/', admin.site.urls),
    path('bolsa/', include('bolsa.urls')),
    path('contrato/', include('contratos.urls')),
    path('estructuras/', include('strorganizativa.urls')),
    path('config/', include('configuracion.urls')),
    path('nomencladores/', include('nomencladores.urls')),
    path('notificaciones/', include('notificaciones.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('solicitudes/', include('solicitudes.urls')),
    
    # SISTEMA DE AUTENTICACIÓN
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    path('accounts/', include('django.contrib.auth.urls'))

]

# CONFIGURACIÓN PARA ARCHIVOS ESTÁTICOS Y MULTIMEDIA EN DESARROLLO
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)