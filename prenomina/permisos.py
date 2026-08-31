"""Control de acceso del módulo Pre-Nómina.

Mismo reparto y mismas piezas que `cierres/permisos.py`, con una diferencia
propia de este módulo: la configuración (los nomencladores) es **exclusiva del
Administrador**, igual que el resto de Parámetros Generales.

El **Observador no tiene acceso**: ni de lectura ni de escritura. Es una
decisión explícita del usuario (antes entraba en solo lectura); `tiene_acceso()`
es la única puerta de las tres, así que basta con excluirlo aquí para que
quede fuera de todo el módulo, URL incluida.

El detalle no obvio, ya documentado en `solicitudes/permisos.py` y
`cierres/permisos.py`: `CustomUser.save()` fuerza `is_superuser=True` en los
administradores, así que `es_moderador()` tiene que excluirlos explícitamente o
un admin pasaría por los dos roles a la vez.

Ocultar un botón no es la protección: toda vista que escriba pasa por aquí, y el
alcance por unidad se aplica en el queryset (`filtros.py`), no con un `if`.
"""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

MENSAJE_SOLO_ADMIN = 'Esta acción solo puede realizarla un Administrador.'
MENSAJE_SIN_ACCESO = 'No tiene acceso al módulo de Pre-Nómina.'
MENSAJE_SOLO_LECTURA = 'Su rol solo permite consultar los reportes de pago.'
MENSAJE_UNIDAD_AJENA = (
    'Solo puede gestionar reportes de las Unidades Organizativas que tenga asignadas.')
MENSAJE_NO_EDITABLE = (
    'El reporte no está en Borrador: no admite cambios. Reábralo primero si es '
    'el último reporte de su unidad.')


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def es_moderador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)


def es_observador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_observador', False)) and not es_administrador(usuario)


def tiene_acceso(usuario):
    """Administrador y Moderador. El Observador queda fuera de todo el módulo."""
    return es_administrador(usuario) or es_moderador(usuario)


def puede_escribir(usuario):
    """¿Puede este usuario modificar reportes en general? (sin mirar la unidad)."""
    return es_administrador(usuario) or es_moderador(usuario)


def puede_gestionar_nomencladores(usuario):
    """Los conceptos de pago son configuración global: solo el Administrador."""
    return es_administrador(usuario)


def gestiona_unidad(usuario, unidad_pk):
    """¿Tiene este usuario la unidad asignada?

    El Administrador las tiene todas. El Moderador, las de su M2M `unidades`,
    misma comprobación que `cierres.permisos.puede_declarar`.
    """
    if es_administrador(usuario):
        return True
    if not es_moderador(usuario):
        return False
    return usuario.unidades.filter(pk=unidad_pk).exists()


def puede_editar(usuario, reporte):
    """¿Puede modificar ESTE reporte, ahora mismo?

    Tres condiciones, todas necesarias: rol de escritura, unidad asignada y
    reporte en Borrador. El estado se comprueba también en `servicios.py` dentro
    del bloqueo; aquí sirve para decidir qué botones se pintan.
    """
    if not puede_escribir(usuario):
        return False
    if not gestiona_unidad(usuario, reporte.unidad_id):
        return False
    return reporte.editable


def puede_reabrir(usuario, reporte):
    """Reabrir exige rol de escritura, unidad asignada y que sea el último.

    La regla de "el último de su unidad" vive en el modelo (`es_ultimo`) porque
    es una propiedad del reporte, no del usuario. Aquí solo se compone.
    """
    if not puede_escribir(usuario):
        return False
    if not gestiona_unidad(usuario, reporte.unidad_id):
        return False
    return reporte.reabrible


def puede_exportar(usuario, reporte):
    """Exportar es una lectura: cualquiera que vea el reporte puede descargarlo."""
    return tiene_acceso(usuario)


def _denegar(request, mensaje):
    """JSON si la petición es AJAX/HTMX; si no, 403 de Django.

    Mismo criterio que `cierres/permisos.py`: un fragmento HTML de error
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


def acceso_prenomina(vista):
    """Los tres roles. Es la puerta de las vistas de consulta."""
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not tiene_acceso(request.user):
            return _denegar(request, MENSAJE_SIN_ACCESO)
        return vista(request, *args, **kwargs)
    return _envuelta


def requiere_escritura(vista):
    """Administrador o Moderador. El Observador queda fuera."""
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not puede_escribir(request.user):
            return _denegar(request, MENSAJE_SOLO_LECTURA)
        return vista(request, *args, **kwargs)
    return _envuelta


def solo_admin(vista):
    """Configuración de nomencladores."""
    @wraps(vista)
    def _envuelta(request, *args, **kwargs):
        if not es_administrador(request.user):
            return _denegar(request, MENSAJE_SOLO_ADMIN)
        return vista(request, *args, **kwargs)
    return _envuelta


class AccesoPreNominaMixin:
    """Equivalente de `acceso_prenomina` para las vistas basadas en clase."""

    def dispatch(self, request, *args, **kwargs):
        if not tiene_acceso(request.user):
            return _denegar(request, MENSAJE_SIN_ACCESO)
        return super().dispatch(request, *args, **kwargs)


class SoloAdminMixin:
    """Equivalente de `solo_admin` para las vistas basadas en clase."""

    def dispatch(self, request, *args, **kwargs):
        if not es_administrador(request.user):
            return _denegar(request, MENSAJE_SOLO_ADMIN)
        return super().dispatch(request, *args, **kwargs)
