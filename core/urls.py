from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from dashboard import views as dashboard_views
from django.urls import path, include

urlpatterns = [
    path('', dashboard_views.DashboardView.as_view(), name='dashboard'),
    path('admin/', admin.site.urls),
    path('bolsa/', include('bolsa.urls')),
    path('contrato/', include('contratos.urls')),
    path('estructuras/', include('strorganizativa.urls')),
    path('config/', include('configuracion.urls')),
    path('nomencladores/', include('nomencladores.urls')),
    path('notificaciones/', include('notificaciones.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('solicitudes/', include('solicitudes.urls')),

    
    
    path('accounts/', include('django.contrib.auth.urls'))
        
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
