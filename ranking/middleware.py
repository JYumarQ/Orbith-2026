import re

from progreso.middleware import FORMATO_POR_CONTENT_TYPE

from .models import Actividad
from .servicios import cerrar_mes_si_toca, registrar_actividad

# Nombre del fichero en Content-Disposition (filename="..." o filename=...).
_NOMBRE_FICHERO = re.compile(r'filename="?([^";]+)"?')


class RankingMiddleware:
    """Dos trabajos del Ranking Mensual que no pertenecen a ninguna vista:

    1. Antes de la vista, cierra el mes anterior si toca (la primera petición
       del mes). Solo consulta la base de datos una vez al mes por proceso.
    2. Después, cuenta cada descarga (PDF, Word o Excel) de cualquier módulo,
       reconocida por su Content-Type, igual que `DeteccionExportacionMiddleware`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cerrar_mes_si_toca()
        response = self.get_response(request)

        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated or response.status_code != 200:
            return response

        content_type = response.get('Content-Type', '').split(';')[0].strip()
        formato = FORMATO_POR_CONTENT_TYPE.get(content_type)
        if not formato:
            return response
        # Los ficheros subidos (media) que sirve Django no son exportaciones.
        coincidencia = getattr(request, 'resolver_match', None)
        if coincidencia and getattr(coincidencia.func, '__module__', '') == 'django.views.static':
            return response

        nombre = _NOMBRE_FICHERO.search(response.get('Content-Disposition', ''))
        registrar_actividad(usuario, Actividad.DESCARGA, formato=formato,
                            detalle=nombre.group(1) if nombre else '')
        return response
