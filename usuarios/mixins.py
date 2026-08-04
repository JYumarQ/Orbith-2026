"""Control de acceso por rol.

El modelo CustomUser ya define los roles (es_admin / es_moderador / es_observador)
y el menú lateral los usa para mostrar u ocultar opciones, pero las vistas de
contratación no comprobaban ninguno: bastaba con escribir la URL para crear,
modificar o dar de baja un contrato siendo observador.
"""
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

MENSAJE_SIN_PERMISO = (
    'No tiene permisos para realizar esta acción. Su usuario es de solo consulta.'
)


def puede_editar(user):
    """Administradores y moderadores pueden escribir; los observadores solo consultan."""
    if not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or getattr(user, 'es_admin', False):
        return True
    return bool(getattr(user, 'es_moderador', False))


def _respuesta_sin_permiso(request):
    """Devuelve JSON si la petición es AJAX/HTMX; si no, deja que salte el 403."""
    es_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.headers.get('HX-Request')
    )
    if es_ajax:
        return JsonResponse(
            {
                'form_is_valid': False,
                'success': False,
                'error_popup': MENSAJE_SIN_PERMISO,
                'message': MENSAJE_SIN_PERMISO,
            },
            status=403,
        )
    messages.error(request, MENSAJE_SIN_PERMISO)
    raise PermissionDenied(MENSAJE_SIN_PERMISO)


class RequiereEdicionMixin:
    """Bloquea las vistas de escritura a los usuarios de solo consulta."""

    def dispatch(self, request, *args, **kwargs):
        if not puede_editar(request.user):
            return _respuesta_sin_permiso(request)
        return super().dispatch(request, *args, **kwargs)


def requiere_edicion(view_func):
    """Equivalente al mixin para vistas basadas en función."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not puede_editar(request.user):
            return _respuesta_sin_permiso(request)
        return view_func(request, *args, **kwargs)

    return _wrapped
