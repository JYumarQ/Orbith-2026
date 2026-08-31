"""Rastro de accesos: quién entró, quién falló y quién salió.

Se engancha a las tres señales de `django.contrib.auth`, y no al formulario del
login, por el mismo motivo que `usuarios.backends`: así queda registrado TODO
inicio de sesión, venga del login de Orbith o del panel de administración de
Django.

Regla de oro de este módulo: **nada de lo que pase aquí puede impedir que un
usuario entre o salga**. Un fallo escribiendo en Auditoría (base de datos llena,
migración pendiente...) dejaría a toda la empresa sin poder iniciar sesión, así
que cada gancho va envuelto en su propio try/except y solo deja un aviso en el
log.

Nunca se guarda la contraseña: Django ya la enmascara antes de emitir la señal
(`credentials` llega con '********'), y aquí solo se lee el nombre de usuario.
"""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed,
)
from django.dispatch import receiver

from auditoria.models import AccionAuditoria
from auditoria.servicios import registrar

from .models import IntentoAcceso
from .utils import obtener_ip

logger = logging.getLogger(__name__)

MODULO = 'usuarios'


def _auditar(usuario, accion, descriptor):
    try:
        registrar(usuario=usuario, accion=accion, modulo=MODULO,
                  descriptor=descriptor)
    except Exception:
        logger.warning("No se pudo auditar el acceso (%s): %s", accion, descriptor,
                       exc_info=True)


@receiver(user_logged_in)
def acceso_correcto(sender, request, user, **kwargs):
    ip = obtener_ip(request)
    try:
        IntentoAcceso.limpiar_tras_acceso_correcto(user.get_username())
    except Exception:
        logger.warning("No se pudieron limpiar los intentos fallidos de %s",
                       user, exc_info=True)

    _auditar(user, AccionAuditoria.ACCESO,
             f'Inicio de sesión de «{user.get_username()}»'
             + (f' desde {ip}' if ip else ''))


@receiver(user_logged_out)
def cierre_de_sesion(sender, request, user, **kwargs):
    # `user` es None cuando se cierra una sesión que ya no tenía usuario válido.
    if user is None:
        return

    nombre = user.get_username()

    # Hay un caso real en el que el objeto `user` todavía existe en memoria pero
    # su fila ya NO está en la base de datos: `usuarios.views.CustomUserDeleteView`
    # borra la cuenta y solo DESPUÉS llama a `logout()`, para no dejar a nadie
    # navegando con una sesión que apunta a un usuario inexistente. Enlazar el
    # evento a ese id rompería la clave foránea de Auditoría.
    #
    # El hecho sí se audita —importa saber que esa sesión se cerró— pero sin
    # relación: el nombre va en el descriptor, que es texto congelado y por eso
    # sobrevive a la desaparición de la cuenta.
    # `get_user_model()` y no `type(user)`: en un logout normal `user` llega
    # envuelto en el SimpleLazyObject de `request.user`, que no tiene manager.
    existe = bool(user.pk) and get_user_model().objects.filter(pk=user.pk).exists()

    _auditar(user if existe else None, AccionAuditoria.SALIDA,
             f'Cierre de sesión de «{nombre}»'
             + ('' if existe else ' (cuenta ya eliminada)'))


@receiver(user_login_failed)
def acceso_fallido(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get('username') or ''
    if not username:
        # Autenticaciones que no usan nombre de usuario (tokens, backends de
        # terceros): no hay cuenta que proteger ni que auditar.
        return

    ip = obtener_ip(request)

    try:
        IntentoAcceso.registrar_fallo(username, ip)
    except Exception:
        logger.warning("No se pudo registrar el intento fallido de %s", username,
                       exc_info=True)

    # `usuario=None` a propósito: el intento falló, así que no hay usuario
    # autenticado al que atribuirlo, y el nombre tecleado puede ni existir. Va en
    # el descriptor, que es texto congelado y sobrevive a cualquier cambio.
    _auditar(None, AccionAuditoria.ACCESO_FALLIDO,
             f'Intento de acceso fallido para «{username}»'
             + (f' desde {ip}' if ip else ''))
