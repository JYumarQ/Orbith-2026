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

def write_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (getattr(request.user, 'es_admin', False) or getattr(request.user, 'es_moderador', False)):
            return HttpResponseForbidden("Solo lectura. No tienes permisos para modificar.")
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