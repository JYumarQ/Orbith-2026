from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from dashboard import views as dashboard_views
from django.urls import path, include
from usuarios.views import CustomLoginView

urlpatterns = [

    path('', dashboard_views.DashboardView.as_view(), name='dashboard'),
    
    path('informes/economia/', dashboard_views.InformeEconomiaView.as_view(), name='informe_economia'),
    path('informes/economia/exportar-word/', dashboard_views.ExportarConsolidadoWordView.as_view(), name='exportar_consolidado_word'),
    path('informes/economia/exportar-pdf/', dashboard_views.ExportarConsolidadoPDFView.as_view(), name='exportar_consolidado_pdf'),

    path('informes/economia/trabajadores-ueb/', dashboard_views.InformeTrabajadoresUEBView.as_view(), name='informe_trabajadores_ueb'),
    path('informes/economia/trabajadores-ueb/exportar-word/', dashboard_views.ExportarResumenUEBWordView.as_view(), name='exportar_resumen_ueb_word'),

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
    path('accounts/login/', CustomLoginView.as_view(), name='login'),

    
    
    path('accounts/', include('django.contrib.auth.urls'))
        
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
