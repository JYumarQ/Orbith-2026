"""Utilidades pequeñas y sin dependencias del resto de `usuarios`."""


def obtener_ip(request):
    """IP desde la que llega la petición, o None si no se puede determinar.

    Se prefiere el primer valor de `X-Forwarded-For` porque en producción Orbith
    va detrás de un proxy (ver `SECURE_PROXY_SSL_HEADER` en settings): sin mirar
    esa cabecera, TODAS las peticiones parecerían venir del propio servidor.

    Importante: esa cabecera la puede falsificar quien haga la petición, así que
    esta IP sirve para DEJAR CONSTANCIA (auditoría, bandeja de reportes), nunca
    como única barrera de seguridad. Por eso el bloqueo por intentos fallidos se
    cuenta por nombre de usuario y no por IP (ver `usuarios.models.IntentoAcceso`).
    """
    if request is None:
        return None

    reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if reenviada:
        # El formato es "cliente, proxy1, proxy2": el primero es el origen real.
        candidata = reenviada.split(',')[0].strip()
        if candidata:
            return candidata[:45]  # cabe una IPv6 completa

    return (request.META.get('REMOTE_ADDR') or None)
