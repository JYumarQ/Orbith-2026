"""Control de acceso del módulo Cierres.

Mismo reparto que `solicitudes/permisos.py`, con una diferencia importante: aquí
el Moderador no solo *ve* su unidad, es **quien declara**. El Administrador puede
declarar cualquiera; el Moderador únicamente las que tenga asignadas en
`CustomUser.unidades`. El Observador queda fuera del flujo.

El detalle no obvio (ya documentado en `solicitudes/permisos.py`): `CustomUser.save()`
fuerza `is_superuser=True` en los administradores, así que `es_moderador()` tiene
que excluirlos explícitamente o un admin pasaría por los dos roles a la vez.
"""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

MENSAJE_SOLO_ADMIN = 'Esta acción solo puede realizarla un Administrador.'
MENSAJE_SIN_ACCESO = 'No tiene acceso al módulo de Cierres.'
MENSAJE_UNIDAD_AJENA = 'Solo puede declarar Unidades Organizativas que tenga asignadas.'
MENSAJE_ES_PRINCIPAL = (
    'Las Unidades Organizativas principales no se declaran directamente: no '
    'tienen departamentos ni cargos propios, toda su plantilla vive en sus '
    'subunidades. Su estado se calcula a partir del de sus subunidades.'
)


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def es_moderador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)


def tiene_acceso(usuario):
    """Administrador o Moderador."""
    return es_administrador(usuario) or es_moderador(usuario)


def es_principal(unidad):
    """¿Es esta unidad una Dirección Principal (padre)?

    Mismo criterio estructural que ya usa `selectUnit()` en
    `gestor_plantilla.html` para deshabilitar «Añadir Departamento» en un
    padre: `unidad.tipo.es_principal`. Se reutiliza aquí para bloquear
    también la declaración, no se introduce un concepto nuevo.
    """
    return bool(unidad.tipo and unidad.tipo.es_principal)


def puede_declarar(usuario, unidad):
    """¿Puede este usuario declarar actualizada esta unidad concreta?

    Dos comprobaciones distintas, en orden:

    1. **Estructural, sin excepción de rol.** Una Dirección Principal no
       tiene departamentos ni cargos propios — toda su plantilla vive en sus
       subunidades — así que declararla generaría una fotografía vacía. Ni
       siquiera el Administrador puede saltarse esto: no es un permiso, es
       que la acción no tiene sentido para este tipo de unidad. Su estado se
       deriva del de sus hijas (ver `integracion.color_por_unidad`).
    2. **De alcance.** La misma comprobación de siempre, la de
       `strorganizativa/views.py:645`: la M2M `unidades` decide qué puede
       tocar un Moderador.
    """
    if es_principal(unidad):
        return False
    if es_administrador(usuario):
        return True
    if not es_moderador(usuario):
        return False
    return usuario.unidades.filter(pk=unidad.pk).exists()


def unidades_declarables(usuario):
    """Unidades sobre las que el usuario puede actuar. Único punto de alcance."""
    from strorganizativa.models import UnidadOrganizativa

    if es_administrador(usuario):
        return UnidadOrganizativa.objects.all()
    if es_moderador(usuario):
        return usuario.unidades.all()
    return UnidadOrganizativa.objects.none()


def _denegar(request, mensaje):
    """JSON si la petición es AJAX/HTMX; si no, 403 de Django.

    Mismo criterio que `solicitudes/permisos.py`: un fragmento HTML de error
    inyectado en un modal no se ve como un fallo, se ve como una pantalla rota.
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


def acceso_cierres(vista):
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
