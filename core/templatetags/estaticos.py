"""`{% estatico %}`: como `{% static %}`, pero sin caché rancia en desarrollo.

EL PROBLEMA. En producción los estáticos ya llevan un hash en el nombre
(`core/storages.AlmacenEstaticosOrbith`, WhiteNoise con manifiesto), así que
cambiar un .js publica una URL distinta y el navegador se la baja sola. En
desarrollo NO: `{% static 'js/x.js' %}` devuelve siempre `/static/js/x.js`, la
misma URL antes y después de editar el archivo. Algunos navegadores —Brave y
Chrome con caché agresiva— la sirven de su propia caché sin preguntarle al
servidor si cambió, así que el desarrollador sigue viendo la versión anterior
por más que recargue.

Se nota especialmente en los formularios que se abren en un modal por HTMX
(alta y edición de Aspirante): al inyectarse la plantilla, el navegador vuelve
a evaluar el `<script src>` con la copia que ya tenía cargada, sin pasar por el
servidor.

LA SOLUCIÓN. Añadir a la URL la fecha de modificación del propio archivo. Al
editarlo cambia la URL, y con ella la entrada de caché. Solo se hace con
`DEBUG=True`: en producción el hash del manifiesto ya cumple esa función y
además la marca de tiempo estorbaría a la caché inmutable de WhiteNoise.
"""

import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def estatico(ruta):
    """URL del estático `ruta`, con `?v=<fecha de modificación>` en desarrollo."""
    url = static(ruta)

    if not settings.DEBUG:
        return url

    # `finders.find` es la misma búsqueda que usa el servidor de desarrollo para
    # servir el archivo, así que encuentra tanto los de `static/` como los de las
    # apps. Si no lo localiza se devuelve la URL tal cual: un estático que falta
    # es un problema aparte y no debe romper el renderizado de la página.
    absoluta = finders.find(ruta)
    if not absoluta:
        return url

    return f'{url}?v={int(os.path.getmtime(absoluta))}'
