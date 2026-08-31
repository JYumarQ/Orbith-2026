"""Context processors globales de Orbith."""
from usuarios.mixins import puede_editar as _puede_editar

from .changelog import ORBITH_INFO, ORBITH_VERSION, obtener_changelog


def orbith(request):
    """Expone la versión, la ficha del sistema y las preferencias del usuario.

    El navbar se pinta en todas las páginas autenticadas, así que estos datos
    tienen que estar disponibles sin que cada vista los inyecte a mano.

    Las preferencias se leen, NUNCA se crean aquí: un context processor se
    ejecuta en cada petición (incluidas las de solo lectura) y no debe escribir
    en base de datos. La fila se crea cuando el usuario guarda una preferencia.
    """
    contexto = {
        # `puede_editar`: Administrador y Moderador sí, Observador no. Es la MISMA
        # función que usan `RequiereEdicionMixin`/`requiere_edicion` en el backend
        # (usuarios/mixins.py), así que lo que se ve en pantalla y lo que el
        # servidor permite no pueden quedar desalineados. Se expone aquí y no en
        # cada vista porque lo consumen los listados de Aspirantes, Bajas y
        # Contratos para pintar los botones de acción inactivos al Observador.
        'puede_editar': _puede_editar(getattr(request, 'user', None)),
        'orbith_version': ORBITH_VERSION,
        'orbith_info': ORBITH_INFO,
        'orbith_changelog': obtener_changelog(),
        # Valores por defecto: coinciden con los del modelo PreferenciasUsuario.
        'pref_sidebar_colapsada': False,
        'pref_animaciones_activas': True,
    }

    usuario = getattr(request, 'user', None)
    if usuario is not None and usuario.is_authenticated:
        preferencias = getattr(usuario, 'preferencias', None)
        if preferencias is not None:
            contexto['pref_sidebar_colapsada'] = preferencias.sidebar_colapsada
            contexto['pref_animaciones_activas'] = preferencias.animaciones_activas
        contexto['advertencias_pendientes'] = _contar_advertencias_pendientes(usuario)
        contexto['solicitudes_pendientes'] = _contar_solicitudes_pendientes(usuario)
        contexto.update(_progreso_guia(usuario))

    return contexto


def _progreso_guia(usuario):
    """Progreso del usuario en la Guía de Orbith, para el badge/resumen del
    navbar y del modal de perfil. Dos consultas por petición autenticada,
    ambas baratas: `TareaGuia` es una tabla de una docena de filas y el
    filtro por `usuario` en `TareaGuiaUsuario` está indexado (es la columna
    líder de su UniqueConstraint). No se cachea: el proyecto no tiene CACHES
    configurado (ver subsanacion/models.py, que por eso usa una restricción
    de base de datos en vez de un lock de aplicación) y estas tablas son
    demasiado pequeñas para justificar esa complejidad.
    """
    from django.db.models import Count, Q

    from progreso.models import TareaGuia, TareaGuiaUsuario

    total = TareaGuia.objects.filter(activo=True).count()
    agregados = TareaGuiaUsuario.objects.filter(usuario=usuario).aggregate(
        completadas=Count('id'),
        sin_ver=Count('id', filter=Q(visto=False)),
    )
    completadas = agregados['completadas'] or 0
    return {
        'progreso_total': total,
        'progreso_completadas': completadas,
        'progreso_sin_ver': agregados['sin_ver'] or 0,
        'progreso_porcentaje': round(100 * completadas / total) if total else 0,
    }


def _contar_advertencias_pendientes(usuario):
    """Advertencias ACTIVA y sin leer, visibles para `usuario` (por unidad
    organizativa o asignación directa; TODAS si `es_admin`), para el badge de
    `sidebar.html` — visible en TODA la app, no solo en la página de Notificaciones.
    Mismo criterio de "pertenencia" que `notificaciones.views._notificaciones_visibles`,
    reescrito aquí en pequeño en vez de importado: ese helper es privado de su módulo y
    este context processor corre en CADA petición autenticada, así que conviene que no
    dependa de las vistas de otra app.

    `leido=False` es imprescindible: sin él, el contador nunca baja aunque el usuario
    lea (o incluso descarte) todas sus advertencias, porque "leído" y "resuelto" son
    ejes independientes en el modelo (ver `Notificacion.leido`) y `estado=ACTIVA` por
    sí solo no dice nada sobre si el usuario ya las vio.
    """
    from django.db.models import Q

    from notificaciones.models import Notificacion

    base = Notificacion.objects.filter(
        tipo=Notificacion.Tipo.ALERTA, estado=Notificacion.Estado.ACTIVA, leido=False)

    if usuario.es_admin:
        return base.count()

    unidades_usuario = usuario.unidades.all()
    return base.filter(Q(unidad__in=unidades_usuario) | Q(destinatario=usuario)).count()


def _contar_solicitudes_pendientes(usuario):
    """Solicitudes pendientes que `usuario` puede gestionar, para el badge de
    "Solicitudes" en `sidebar.html`.

    A diferencia de `_contar_advertencias_pendientes`, aquí SÍ se importa el criterio de
    alcance en vez de reescribirlo: `solicitudes.filtros.solicitudes_visibles` no es un
    helper privado de una vista, es la función pública que el propio módulo documenta
    como "el único punto donde se decide el alcance" — duplicarla aquí sería la manera
    segura de que las dos copias diverjan con el tiempo.

    Sin acceso al módulo (el Observador) no hay nada que contar: ni siquiera puede ver
    "Solicitudes" en la sidebar.
    """
    if not (getattr(usuario, 'es_admin', False) or getattr(usuario, 'es_moderador', False)):
        return 0

    from solicitudes.filtros import contar_pendientes

    return contar_pendientes(usuario)
