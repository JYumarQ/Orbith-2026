"""Context processors globales de Orbith."""
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

    return contexto
