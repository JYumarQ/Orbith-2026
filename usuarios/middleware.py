from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
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
