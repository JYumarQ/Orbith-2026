"""Control de acceso del módulo de Subsanación.

Mismo reparto que `cierres/permisos.py`: el Administrador ve y actúa sobre toda la
empresa; el Moderador solo sobre las Unidades Organizativas que tiene asignadas en
`CustomUser.unidades`; el Observador queda completamente fuera — a diferencia del
Dashboard general (`dashboard/filtros.py`), donde el Observador ve todo igual que el
Administrador, aquí Subsanación expone qué está mal en los datos de la empresa, no un
resumen informativo, así que se le niega el acceso por completo.

El barrido completo (`servicios.ejecutar_analisis_completo()` y toda la cadena
`iniciar_analisis`/`ejecutar_modulo`/`finalizar_analisis`) sigue siendo EXCLUSIVO del
Administrador — el aviso al principio de `servicios.py` explica por qué un barrido
parcial rompería la reconciliación: leería solo una parte de la empresa y daría por
corregidos hallazgos de unidades que nunca llegó a mirar. Por la misma razón, el
Dashboard, las Estadísticas y el Historial de revisiones (que describen ese barrido
completo, agregado a TODA la empresa) también quedan solo para Administrador.

Lo que sí puede consultar y gestionar un Moderador es el LISTADO de Hallazgos
(`panel_hallazgos`, `detalle_hallazgo`, `cambiar_estado`, las exportaciones), acotado
a sus propias Unidades Organizativas mediante el campo denormalizado
`Hallazgo.unidad_organizativa` — exactamente el punto de extensión que ya preveía el
docstring de `servicios.py`: «El alcance por rol se aplica al LEER el listado (en las
vistas), usando el campo denormalizado `Hallazgo.unidad_organizativa`».
"""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

MENSAJE_SIN_ACCESO = 'No tiene acceso al módulo de Subsanación.'
MENSAJE_SOLO_ADMIN = (
    'Esta sección de Subsanación describe el análisis completo de toda la empresa '
    'y solo está disponible para Administradores.')


def es_administrador(usuario):
    """Administrador de Subsanación: el Administrador, y el Moderador con el permiso
    especial «Subsanación como administrador» (25-10-2026), que ve y lanza lo mismo."""
    if not getattr(usuario, 'is_authenticated', False):
        return False
    if usuario.is_superuser or getattr(usuario, 'es_admin', False):
        return True
    from usuarios.permisos_especiales import por_permiso_especial
    return por_permiso_especial(usuario, 'subsanacion')


def es_moderador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    # `CustomUser.save()` fuerza `is_superuser=True`/`es_admin` en los administradores,
    # así que hay que excluirlos explícitamente o un admin pasaría por los dos roles a
    # la vez (mismo detalle ya documentado en `cierres/permisos.py`).
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)


def tiene_acceso(usuario):
    """Administrador o Moderador. El Observador (o cualquier otro rol) no entra."""
    return es_administrador(usuario) or es_moderador(usuario)


def unidades_visibles(usuario):
    """Unidades Organizativas cuyos hallazgos puede ver/gestionar este usuario.

    Único punto de alcance de Subsanación — todo lo que filtra hallazgos por unidad
    (listado, detalle, cambio de estado, exportaciones) pasa por aquí, igual que
    `cierres/filtros.py::unidades_visibles()`.
    """
    from strorganizativa.models import UnidadOrganizativa

    if es_administrador(usuario):
        return UnidadOrganizativa.objects.all()
    if es_moderador(usuario):
        return usuario.unidades.all()
    return UnidadOrganizativa.objects.none()


def _denegar(request, mensaje):
    """JSON si la petición es AJAX/HTMX; si no, un 403 real de Django.

    Mismo criterio que `cierres/permisos.py::_denegar` (y `solicitudes/permisos.py`):
    un fragmento HTML de error inyectado en un modal/panel HTMX no se ve como un
    fallo de permisos, se ve como una pantalla rota.
    """
    es_ajax = (request.headers.get('x-requested-with') == 'XMLHttpRequest'
               or request.headers.get('HX-Request'))
    if es_ajax:
        return JsonResponse(
            {'success': False, 'error_popup': mensaje, 'message': mensaje}, status=403)
    messages.error(request, mensaje)
    raise PermissionDenied(mensaje)


def acceso_subsanacion(vista):
    """Reemplaza a `admin_required` en las vistas del módulo abiertas a Moderador:
    deja pasar a Administrador y Moderador; a cualquier otro (incluido Observador,
    o un usuario sin autenticar) le devuelve 403 sin revelar nada del contenido."""
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not tiene_acceso(request.user):
            return _denegar(request, MENSAJE_SIN_ACCESO)
        return vista(request, *args, **kwargs)
    return _envuelta


def solo_admin_subsanacion(vista):
    """Dashboard, Estadísticas, Historial y la cadena de análisis (iniciar/ejecutar/
    finalizar): todas describen o lanzan el barrido COMPLETO de la empresa, así que
    quedan exclusivas del Administrador (ver el docstring del módulo)."""
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not es_administrador(request.user):
            return _denegar(request, MENSAJE_SOLO_ADMIN)
        return vista(request, *args, **kwargs)
    return _envuelta
