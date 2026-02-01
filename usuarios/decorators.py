from django.contrib.auth.decorators import user_passes_test

def admin_required(view):
    return user_passes_test(
        lambda u: u.is_authenticated and getattr(u, 'es_admin', False)
    )(view)

# NUEVO: permite escribir solo a Admin o Moderador
from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.views import redirect_to_login

def write_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (getattr(request.user, 'es_admin', False) or getattr(request.user, 'es_moderador', False)):
            return HttpResponseForbidden("Solo lectura.")
        return view(request, *args, **kwargs)
    return _wrapped
