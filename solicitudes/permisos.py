"""Control de acceso del módulo Solicitudes.

`usuarios/mixins.py` distingue quién puede escribir y quién solo consulta, que es la
pregunta correcta para el resto de Orbith. Aquí hacen falta dos respuestas más finas:

* Solicitudes es un módulo de Moderador y Administrador. El Observador **no lo ve**, ni
  siquiera en solo lectura: no participa en el flujo de aprobación.
* Revisar, aprobar, rechazar, cancelar una revisión y devolver a espera son
  exclusivamente del Administrador. `puede_editar()` no sirve para esto, porque devuelve
  True también para los moderadores.

Las comprobaciones por solicitud concreta (quién la ve, quién la edita, quién la retira)
no están aquí sino en el propio modelo, junto a los datos de los que dependen.
"""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

MENSAJE_SOLO_ADMIN = 'Esta acción solo puede realizarla un Administrador.'
MENSAJE_SIN_ACCESO = 'No tiene acceso al módulo de Solicitudes.'


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def es_moderador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    # Un administrador es superusuario en Orbith (`CustomUser.save()` lo fuerza), así que
    # hay que excluirlo explícitamente para no confundir los dos roles.
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)


def tiene_acceso(usuario):
    """Administrador o Moderador. El Observador queda fuera."""
    return es_administrador(usuario) or es_moderador(usuario)


def _denegar(request, mensaje):
    """JSON si la petición es AJAX/HTMX; si no, 403 de Django.

    Mismo criterio que `usuarios/mixins.py::_respuesta_sin_permiso`: un fragmento HTML de
    error inyectado en un modal no se ve como un fallo, se ve como una pantalla rota.
    """
    es_ajax = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
               or request.headers.get('HX-Request'))
    if es_ajax:
        return JsonResponse(
            {'success': False, 'form_is_valid': False,
             'error_popup': mensaje, 'message': mensaje},
            status=403)
    messages.error(request, mensaje)
    raise PermissionDenied(mensaje)


class AccesoSolicitudesMixin:
    """Entrada al módulo: Administrador o Moderador."""

    def dispatch(self, request, *args, **kwargs):
        if not tiene_acceso(request.user):
            return _denegar(request, MENSAJE_SIN_ACCESO)
        return super().dispatch(request, *args, **kwargs)


class SoloAdminMixin:
    """Acciones de decisión: revisar, aprobar, rechazar, cancelar, devolver."""

    def dispatch(self, request, *args, **kwargs):
        if not es_administrador(request.user):
            return _denegar(request, MENSAJE_SOLO_ADMIN)
        return super().dispatch(request, *args, **kwargs)


def acceso_solicitudes(vista):
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not tiene_acceso(request.user):
            return _denegar(request, MENSAJE_SIN_ACCESO)
        return vista(request, *args, **kwargs)
    return _envuelta


def solo_admin(vista):
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not es_administrador(request.user):
            return _denegar(request, MENSAJE_SOLO_ADMIN)
        return vista(request, *args, **kwargs)
    return _envuelta
