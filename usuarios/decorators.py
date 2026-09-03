from functools import wraps
from django.contrib.auth.decorators import user_passes_test, login_required
from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login

def admin_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not getattr(request.user, 'es_admin', False):
            return HttpResponseForbidden("Acceso solo para Administradores.")
        return view(request, *args, **kwargs)
    return _wrapped

def _es_gestor(usuario):
    """Administrador o Moderador: los dos roles que gestionan datos.

    El Observador queda fuera. Es la MISMA pregunta que responde
    `usuarios.mixins.puede_editar`; aquí vive aparte porque los decoradores de
    este módulo cortan la petición con `HttpResponseForbidden` (texto plano) y
    el mixin lo hace con JSON o `PermissionDenied`, según el tipo de petición.
    """
    return bool(getattr(usuario, 'es_admin', False) or getattr(usuario, 'es_moderador', False))


def write_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _es_gestor(request.user):
            return HttpResponseForbidden("Solo lectura. No tienes permisos para modificar.")
        return view(request, *args, **kwargs)
    return _wrapped


def gestion_required(view):
    """Cierra una PANTALLA completa al Observador (no solo su escritura).

    Misma comprobación que `write_required`, pero otro mensaje: allí el usuario
    intentaba modificar algo y «Solo lectura» explica el rechazo; aquí lo único
    que intentaba era ABRIR la página, y ese mensaje le haría buscar un botón de
    guardar que nunca pulsó.

    Se usa donde el Observador no debe ni asomarse: el panel de Notificaciones
    (los avisos personales le siguen llegando por la campana de la barra
    lateral) y el listado del nomenclador de cargos.
    """
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _es_gestor(request.user):
            return HttpResponseForbidden(
                "Esta sección no está disponible para su rol.")
        return view(request, *args, **kwargs)
    return _wrapped

def observador_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not getattr(request.user, 'es_observador', False):
            return HttpResponseForbidden("Acceso solo para Observadores.")
        return view(request, *args, **kwargs)
    return _wrapped

# Si quieres proteger todas las vistas con login, usa un middleware (ver más abajo).