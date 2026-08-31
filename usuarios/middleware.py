from datetime import timedelta
from functools import lru_cache

from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from configuracion.models import Configuracion

from .models import CustomUser

# Cada cuánto se permite reescribir `ultima_actividad` como máximo (una escritura
# por usuario cada N segundos, sin importar cuántas peticiones haga mientras tanto).
THROTTLE_ACTIVIDAD = timedelta(seconds=60)

MENSAJE_MANTENIMIENTO = (
    "Orbith entrará en mantenimiento. Tu sesión ha sido cerrada. "
    "Por favor, intenta iniciar sesión nuevamente más tarde."
)
MENSAJE_EXPULSION = "Tu sesión ha sido cerrada por un Administrador."

# Los minutos salen de INACTIVIDAD_MAXIMA (definida justo debajo) para que el
# mensaje no pueda contradecir a la regla si alguien cambia el valor.
MENSAJE_INACTIVIDAD = (
    "Tu sesión se cerró tras {minutos} minutos sin actividad. "
    "Vuelve a iniciar sesión para continuar."
)

# --- Caducidad de sesión por inactividad ---
# Tiempo sin actividad REAL tras el cual se cierra la sesión. Protege el caso
# habitual en oficina: alguien deja Orbith abierto en un PC compartido y se va.
INACTIVIDAD_MAXIMA = timedelta(minutes=60)

# Cada cuánto se reescribe la marca de actividad en la sesión. Sin este freno se
# escribiría la sesión en base de datos en CADA petición (mismo motivo que
# THROTTLE_ACTIVIDAD, arriba).
REFRESCO_INACTIVIDAD = timedelta(seconds=60)

# Clave dentro de `request.session`. Va en la sesión y no en el usuario a
# propósito: `CustomUser.ultima_actividad` es por USUARIO, así que si alguien
# tiene Orbith abierto en dos equipos, la actividad en uno mantendría viva la
# sesión olvidada del otro, que es justo lo que se quiere evitar.
CLAVE_ACTIVIDAD = 'ultima_actividad_real'

# Peticiones automáticas del navegador que NO cuentan como actividad del usuario.
# `templates/base/navbar.html` consulta el contador de notificaciones cada 5
# minutos mientras haya una pestaña abierta: si eso contara como actividad, una
# pestaña olvidada mantendría la sesión viva indefinidamente y esta protección no
# serviría absolutamente para nada.
#
# Se guardan los NOMBRES de las rutas, no las direcciones: la dirección real de
# `notificaciones_json` es `/notificaciones/notificaciones/json/` (el prefijo del
# include se repite), así que escribirla a mano aquí sería un error silencioso
# —la comprobación no casaría nunca y la sesión no caducaría jamás—.
NOMBRES_RUTAS_AUTOMATICAS = ('notificaciones_json',)

MENSAJE_INACTIVIDAD = MENSAJE_INACTIVIDAD.format(
    minutos=int(INACTIVIDAD_MAXIMA.total_seconds() // 60))


@lru_cache(maxsize=1)
def rutas_automaticas():
    """Direcciones de `NOMBRES_RUTAS_AUTOMATICAS`, resueltas una sola vez.

    Se calcula de forma perezosa (y no al importar el módulo) porque el
    middleware se importa antes de que el mapa de URLs esté cargado.
    """
    rutas = set()
    for nombre in NOMBRES_RUTAS_AUTOMATICAS:
        try:
            rutas.add(reverse(nombre))
        except NoReverseMatch:
            # La ruta ya no existe: no es motivo para tumbar todas las peticiones.
            pass
    return frozenset(rutas)


class ControlAccesoMiddleware:
    """Registra actividad de sesión y aplica, en cada petición autenticada, el
    mantenimiento global y la expulsión individual de sesión.

    Debe ir al FINAL de MIDDLEWARE en settings.py: cuando corta la petición sin
    llamar a `get_response`, la respuesta todavía debe atravesar hacia afuera
    `MessageMiddleware` y `SessionMiddleware` (van antes en la lista) para que
    el mensaje flash y la sesión nueva post-logout se guarden correctamente.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if user is not None and user.is_authenticated:
            # La inactividad se comprueba ANTES y se aplica a TODOS, incluidos los
            # Administradores: un PC desatendido con una sesión de Administrador
            # abierta es precisamente el peor caso.
            respuesta = self._controlar_inactividad(request)
            if respuesta is not None:
                return respuesta

            if not getattr(user, 'es_admin', False):
                mensaje = self._motivo_de_bloqueo(user)
                if mensaje:
                    # No se refresca `ultima_actividad`: esta petición no cuenta como
                    # actividad real, es la que precisamente lo saca de Orbith. Si se
                    # actualizara aquí, el usuario expulsado seguiría viéndose como
                    # "Conectado" en Administración/Usuarios hasta que expire el umbral.
                    return self._forzar_salida(request, mensaje)

            self._actualizar_actividad(user)

        return self.get_response(request)

    def _controlar_inactividad(self, request):
        """Cierra la sesión si lleva demasiado tiempo sin actividad real.

        Devuelve la respuesta de salida, o None si la sesión sigue viva.

        La marca se guarda como segundos desde época (un número) y no como
        `datetime` porque la sesión se serializa a JSON, que no sabe guardar
        fechas.
        """
        ahora = timezone.now()
        marca = request.session.get(CLAVE_ACTIVIDAD)

        if marca:
            inactivo = ahora.timestamp() - marca
            if inactivo > INACTIVIDAD_MAXIMA.total_seconds():
                return self._forzar_salida(request, MENSAJE_INACTIVIDAD)

        # Las peticiones automáticas se COMPRUEBAN (arriba) pero no refrescan la
        # marca: el reloj debe seguir corriendo aunque la pestaña siga sondeando.
        if request.path in rutas_automaticas():
            return None

        if not marca or ahora.timestamp() - marca > REFRESCO_INACTIVIDAD.total_seconds():
            request.session[CLAVE_ACTIVIDAD] = ahora.timestamp()

        return None

    def _actualizar_actividad(self, user):
        ahora = timezone.now()
        if not user.ultima_actividad or ahora - user.ultima_actividad > THROTTLE_ACTIVIDAD:
            CustomUser.objects.filter(pk=user.pk).update(ultima_actividad=ahora)

    def _motivo_de_bloqueo(self, user):
        """None si puede continuar; en caso contrario, el mensaje a mostrar."""
        config = Configuracion.objects.first()
        if config and config.modo_mantenimiento:
            return MENSAJE_MANTENIMIENTO

        if user.sesion_invalidada_en and user.last_login and user.sesion_invalidada_en > user.last_login:
            return MENSAJE_EXPULSION

        return None

    def _forzar_salida(self, request, mensaje):
        es_ajax = (
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or bool(getattr(request, 'htmx', False))
        )
        logout(request)

        if es_ajax:
            return JsonResponse({'sesion_invalidada': True, 'mensaje': mensaje}, status=401)

        messages.error(request, mensaje)
        return redirect('login')
