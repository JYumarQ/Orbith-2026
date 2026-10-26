"""Permisos especiales de los Moderadores (25-10-2026).

En la empresa había muchos Administradores, y todo Administrador es además
superusuario del admin de Django. Para no tener que dar ese poder a tanta gente,
el Administrador crea PERFILES de permisos con nombre (p. ej. «Jefe de RRHH
municipal»), marca qué permisos lleva cada uno y asigna UN perfil (o ninguno) a
cada Moderador, con caducidad y motivo opcionales.

* Los permisos valen para TODA LA EMPRESA, no solo para las unidades del Moderador.
* Límites fijos para cualquier perfil: nunca el admin de Django, nunca usuarios
  ni perfiles, nunca resolver una solicitud propia.
* Lo que se haga gracias a un permiso especial queda en Auditoría marcado
  «con permiso especial» (`con_permiso` / `permiso_en_uso`).

Uso:

    from usuarios.permisos_especiales import tiene_permiso, permiso_required

    if tiene_permiso(request.user, 'editor_historico'): ...

    @permiso_required('nomencladores')
    def vista(request): ...
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.utils import timezone

#: (código, nombre, explicación). El código es también el nombre del campo
#: booleano de `PerfilPermisos`.
PERMISOS = (
    ('resolver_solicitudes', 'Resolver solicitudes',
     'Aprueba o rechaza cualquier solicitud, como un Administrador (nunca las suyas), y '
     'recibe en la campana las solicitudes nuevas. Incluye «Editar sin solicitud»: no '
     'tiene que pedirse permiso a sí mismo.'),
    ('editar_sin_solicitud', 'Editar sin solicitud',
     'Lo que hoy pide por solicitud (editar contratos, crear y editar cargos, departamentos '
     'y unidades) lo guarda directamente.'),
    ('nomencladores', 'Nomencladores y parámetros',
     'Entra a todos los nomencladores y a los Parámetros generales.'),
    ('gestor_completo', 'Gestor de plantilla completo',
     'Crea y edita unidades organizativas y trabaja en la plantilla de toda la empresa.'),
    ('editor_historico', 'Editor del histórico',
     'Corrige el histórico de cualquier trabajador, con motivo obligatorio.'),
    ('subsanacion', 'Subsanación como administrador',
     'Ve todos los avisos de la empresa y lanza el análisis completo.'),
    ('auditoria', 'Auditoría y estadísticas',
     'Ve la Auditoría completa y las Estadísticas de uso.'),
)
CODIGOS = tuple(codigo for codigo, _, _ in PERMISOS)
NOMBRES = {codigo: nombre for codigo, nombre, _ in PERMISOS}


def perfil_vigente(usuario):
    """El perfil del Moderador si está asignado y no ha caducado; si no, None."""
    if not getattr(usuario, 'is_authenticated', False):
        return None
    if getattr(usuario, 'es_admin', False) or not getattr(usuario, 'es_moderador', False):
        return None
    if not getattr(usuario, 'perfil_permisos_id', None):
        return None
    vence = getattr(usuario, 'perfil_vence', None)
    if vence is not None and vence < timezone.localdate():
        return None
    return usuario.perfil_permisos


def por_permiso_especial(usuario, codigo):
    """True solo si el usuario lo puede hacer GRACIAS a su perfil (un Moderador),
    no por ser Administrador. Es lo que se marca en Auditoría."""
    if codigo not in CODIGOS:
        raise ValueError('Permiso especial desconocido: %s' % codigo)
    perfil = perfil_vigente(usuario)
    if perfil is None:
        return False
    # Quien resuelve las solicitudes de los demás guarda lo suyo directamente
    # (decisión del usuario, 25-10-2026).
    if codigo == 'editar_sin_solicitud' and perfil.resolver_solicitudes:
        return True
    return bool(getattr(perfil, codigo, False))


def tiene_permiso(usuario, codigo):
    """¿Puede hacerlo? El Administrador siempre; el Moderador, si su perfil lo lleva."""
    if getattr(usuario, 'is_authenticated', False) and getattr(usuario, 'es_admin', False):
        return True
    return por_permiso_especial(usuario, codigo)


def usuarios_con_permiso(codigo):
    """Moderadores activos cuyo perfil vigente lleva ese permiso (para avisarles)."""
    from django.db.models import Q

    from .models import CustomUser
    return CustomUser.objects.filter(
        Q(perfil_vence__isnull=True) | Q(perfil_vence__gte=timezone.localdate()),
        es_moderador=True, is_active=True, **{'perfil_permisos__%s' % codigo: True})


def puede_resolver(usuario, solicitud=None):
    """Resolver solicitudes: el Administrador, o el Moderador con ese permiso
    especial, NUNCA sobre una solicitud suya."""
    if getattr(usuario, 'is_authenticated', False) and (
            getattr(usuario, 'es_admin', False) or usuario.is_superuser):
        return True
    if not por_permiso_especial(usuario, 'resolver_solicitudes'):
        return False
    return solicitud is None or getattr(solicitud, 'solicitante_id', None) != usuario.pk


def permisos_de(usuario):
    """`{código: bool}` para las plantillas (ver `core.context_processors`)."""
    return {codigo: tiene_permiso(usuario, codigo) for codigo in CODIGOS}


# --------------------------------------------------------------------------
# Marca en Auditoría
# --------------------------------------------------------------------------

_permiso_en_uso = ContextVar('permiso_especial_en_uso', default='')
# Solo dentro de una petición web (lo pone `PermisoEspecialMiddleware`): fuera de ella
# —un comando, una prueba— nadie limpiaría la marca y pasaría a lo siguiente.
_en_peticion = ContextVar('permiso_especial_en_peticion', default=False)


def permiso_en_uso():
    """Nombre del permiso especial con el que se está trabajando ahora ('' si ninguno)."""
    return _permiso_en_uso.get()


@contextmanager
def con_permiso(usuario, codigo):
    """Todo lo que se audite dentro del bloque lleva la marca «con permiso
    especial: …» si el usuario actúa gracias a su perfil (no si es Administrador)."""
    if not por_permiso_especial(usuario, codigo):
        yield
        return
    token = _permiso_en_uso.set(NOMBRES[codigo])
    try:
        yield
    finally:
        _permiso_en_uso.reset(token)


def marcar_en_esta_peticion(codigo):
    """Marca el resto de la petición actual (lo deshace `PermisoEspecialMiddleware`
    al terminar). Para cuando el permiso se decide a mitad de una vista, como el
    salto de la solicitud en `solicitudes.integracion.requiere_solicitud`."""
    if _en_peticion.get():
        _permiso_en_uso.set(NOMBRES[codigo])


class PermisoEspecialMiddleware:
    """Cada petición empieza sin marca y la deja limpia al terminar: así una marca
    puesta con `marcar_en_esta_peticion` nunca pasa a la petición siguiente del hilo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _permiso_en_uso.set('')
        dentro = _en_peticion.set(True)
        try:
            return self.get_response(request)
        finally:
            _en_peticion.reset(dentro)
            _permiso_en_uso.reset(token)


def permiso_required(codigo):
    """Como `admin_required`, pero también deja pasar al Moderador cuyo perfil
    lleva ese permiso (y marca en Auditoría lo que haga)."""
    def decorador(vista):
        @wraps(vista)
        def _envuelta(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not tiene_permiso(request.user, codigo):
                return HttpResponseForbidden(
                    'Acceso solo para Administradores o Moderadores con el permiso especial '
                    '«%s».' % NOMBRES[codigo])
            with con_permiso(request.user, codigo):
                return vista(request, *args, **kwargs)
        return _envuelta
    return decorador


class PermisoRequeridoMixin:
    """`permiso_required` para vistas basadas en clase: `permiso_especial = 'código'`."""
    permiso_especial = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not tiene_permiso(request.user, self.permiso_especial):
            return HttpResponseForbidden(
                'Acceso solo para Administradores o Moderadores con el permiso especial '
                '«%s».' % NOMBRES[self.permiso_especial])
        with con_permiso(request.user, self.permiso_especial):
            return super().dispatch(request, *args, **kwargs)


# --------------------------------------------------------------------------
# Asignar, cambiar o quitar el perfil: Auditoría y aviso al Moderador
# --------------------------------------------------------------------------

def _foto_de_asignacion(usuario):
    perfil = getattr(usuario, 'perfil_permisos', None)
    vence = getattr(usuario, 'perfil_vence', None)
    return {
        'perfil': perfil.nombre if perfil else '',
        'vence': vence.strftime('%d/%m/%Y') if vence else '',
        'motivo': getattr(usuario, 'perfil_motivo', '') or '',
    }


def foto_de_asignacion(usuario_id):
    """Cómo estaba la asignación en la base de datos (antes de guardar el formulario,
    que ya ha cambiado la instancia al validar)."""
    from .models import CustomUser
    usuario = CustomUser.objects.select_related('perfil_permisos').filter(pk=usuario_id).first()
    return _foto_de_asignacion(usuario) if usuario else {'perfil': '', 'vence': '', 'motivo': ''}


def registrar_cambio_de_perfil(usuario, antes):
    """Si cambió la asignación, la deja en Auditoría y avisa al Moderador."""
    from auditoria.models import AccionAuditoria
    from auditoria.registro_automatico import registrar

    despues = _foto_de_asignacion(usuario)
    if despues == antes:
        return
    etiquetas = {'perfil': 'Perfil de permisos especiales', 'vence': 'Hasta', 'motivo': 'Motivo'}
    registrar(usuario, AccionAuditoria.MODIFICAR,
              antes={etiquetas[k]: v or '—' for k, v in antes.items()},
              despues={etiquetas[k]: v or '—' for k, v in despues.items()},
              descriptor='Permisos especiales de «%s»' % usuario.username, unidad=None)
    _avisar_al_moderador(usuario, antes, despues)


def _avisar_al_moderador(usuario, antes, despues):
    from django.contrib.contenttypes.models import ContentType

    from notificaciones.avisos import _registrar_notificacion
    from notificaciones.models import Notificacion

    if despues['perfil']:
        titulo = 'Tiene permisos especiales: «%s»' % despues['perfil']
        perfil = usuario.perfil_permisos
        mensaje = 'Puede: %s.' % ', '.join(perfil.permisos_marcados() or ['ningún permiso marcado todavía'])
        if despues['vence']:
            mensaje += ' Hasta el %s.' % despues['vence']
        if despues['motivo']:
            mensaje += ' Motivo: %s' % despues['motivo']
    else:
        titulo = 'Ya no tiene permisos especiales'
        mensaje = 'Se le quitó el perfil «%s».' % antes['perfil']
    _registrar_notificacion(
        tipo_ct=ContentType.objects.get_for_model(type(usuario)), object_id=str(usuario.pk),
        destinatario=usuario, codigo_regla='PERMISOS-ESPECIALES',
        clave_extra=timezone.now().strftime('%Y%m%d%H%M%S%f'),
        defaults={'titulo': titulo[:150], 'mensaje': mensaje, 'tipo': Notificacion.Tipo.EVENTO,
                  'estado': Notificacion.Estado.ACTIVA})
