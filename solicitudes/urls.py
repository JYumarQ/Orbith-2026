"""Rutas del módulo Solicitudes.

Sin `app_name`, igual que el resto de módulos de negocio de Orbith: los nombres viven en
el espacio global y se referencian como `{% url 'list_solicitudes' %}`. Cambiar el
criterio aquí obligaría a distinguir dos convenciones en las mismas plantillas.

`login_required` explícito en cada ruta por coherencia con los demás `urls.py` del
proyecto, aunque `LoginRequiredMiddleware` ya lo cubra globalmente. El control de rol no
está aquí sino en los decoradores de cada vista (`solicitudes/permisos.py`), que saben
distinguir entre «entrar al módulo» y «decidir».
"""

from django.contrib.auth.decorators import login_required
from django.urls import path

from . import personalizadas, views

urlpatterns = [
    # Listado y búsqueda
    path('', login_required(views.lista_solicitudes), name='list_solicitudes'),
    path('buscar/', login_required(views.buscar_solicitudes), name='search_solicitudes'),

    # Alta desde la tabla (solo las operaciones de NCargo)
    path('nueva/', login_required(views.crear_solicitud), name='add_solicitud'),
    path('campos/', login_required(views.campos_solicitud), name='campos_solicitud'),

    # Ciclo de vida
    path('<int:pk>/', login_required(views.ver_solicitud), name='ver_solicitud'),
    path('<int:pk>/editar/', login_required(views.editar_solicitud), name='updt_solicitud'),
    path('<int:pk>/eliminar/', login_required(views.eliminar_solicitud), name='del_solicitud'),

    # Decisión (solo Administrador)
    path('<int:pk>/revisar/', login_required(views.revisar_solicitud), name='revisar_solicitud'),
    path('<int:pk>/aprobar/', login_required(views.aprobar_solicitud), name='aprobar_solicitud'),
    path('<int:pk>/rechazar/', login_required(views.rechazar_solicitud), name='rechazar_solicitud'),
    path('<int:pk>/cancelar/', login_required(views.cancelar_revision), name='cancelar_revision'),
    path('<int:pk>/devolver/', login_required(views.devolver_solicitud), name='devolver_solicitud'),

    # Solicitudes personalizadas: mensaje directo Moderador → Administrador (24-10-2026)
    path('personalizadas/', login_required(personalizadas.lista_personalizadas),
         name='list_solicitudes_personalizadas'),
    path('personalizadas/nueva/', login_required(personalizadas.crear_personalizada),
         name='add_solicitud_personalizada'),
    path('personalizadas/<int:pk>/', login_required(personalizadas.ver_personalizada),
         name='ver_solicitud_personalizada'),
    path('personalizadas/<int:pk>/responder/', login_required(personalizadas.responder_personalizada),
         name='responder_solicitud_personalizada'),
]
