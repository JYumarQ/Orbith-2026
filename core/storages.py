"""Almacenamiento de ficheros estáticos de Orbith.

Ver `core/settings.py::STORAGES` para el porqué de usar el almacenamiento con
manifiesto de WhiteNoise (compresión + nombres con hash + caché inmutable).
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


def _sin_reglas_de_sourcemap(patrones):
    """Quita de `patterns` las reglas que reescriben `sourceMappingURL`.

    Django, al procesar los estáticos, reescribe TODA referencia que encuentre
    dentro de un .css/.js para apuntarla al nombre con hash, y revienta si el
    fichero referenciado no existe. Eso es lo que queremos para imágenes y
    fuentes —una fuente que falta es un icono que no se ve—, pero no para los
    mapas de código (`*.map`): son ficheros de depuración que solo pide el
    navegador cuando tienes las herramientas de desarrollo abiertas, y varias
    librerías de terceros de este proyecto (bootstrap, popper,
    perfect-scrollbar) traen el comentario `//# sourceMappingURL=...` sin
    incluir el .map correspondiente.

    Sin esta poda, `collectstatic` fallaría el despliegue por un fichero que a
    nadie le hace falta. Se filtra por patrón y no borrando el comentario de
    cada librería a mano, para que la próxima actualización de un paquete de
    terceros no vuelva a romper el despliegue.
    """
    limpios = []
    for extension, reglas in patrones:
        conservadas = tuple(
            regla for regla in reglas
            if 'sourceMappingURL' not in (regla[0] if isinstance(regla, (list, tuple)) else regla)
        )
        limpios.append((extension, conservadas))
    return tuple(limpios)


class AlmacenEstaticosOrbith(CompressedManifestStaticFilesStorage):
    """WhiteNoise con manifiesto, ignorando los mapas de código que no vienen."""

    patterns = _sin_reglas_de_sourcemap(CompressedManifestStaticFilesStorage.patterns)

    # Si un `{% static %}` apunta a un fichero que no está en el manifiesto, se
    # devuelve la ruta sin hash en lugar de reventar la petición.
    #
    # Con el valor de serie (True), un solo fichero que falte tumba con un 500
    # TODAS las páginas que lo mencionen —base.html incluido, o sea, la
    # aplicación entera— y encima solo en producción, porque en desarrollo
    # (DEBUG=True) no se usa el manifiesto. Es un fallo demasiado caro para lo
    # que evita.
    #
    # La comprobación que de verdad importa no se pierde: las referencias dentro
    # de CSS y JS (fuentes, imágenes) se siguen validando al ejecutar
    # `collectstatic`, y ahí sí falla el despliegue antes de publicar nada.
    #
    # También es lo que permite ejecutar `manage.py test` sin haber lanzado
    # `collectstatic`: el runner de Django pone DEBUG=False, así que sin esto
    # cualquier prueba que renderice una plantilla fallaría por no encontrar
    # `staticfiles.json`.
    manifest_strict = False

    def stored_name(self, name):
        """Nunca revienta por un estático que falte: devuelve la ruta sin hash.

        `manifest_strict = False` cubre el caso "no está en el manifiesto", pero
        Django resuelve ese caso calculando el hash al vuelo, y eso vuelve a
        fallar si el fichero tampoco está en `STATIC_ROOT` (por ejemplo, un
        `collectstatic` viejo al que le faltan ficheros nuevos). Aquí se cierra
        el círculo: como mucho se pierde ese recurso concreto, nunca la página.
        """
        try:
            return super().stored_name(name)
        except ValueError:
            return self.clean_name(name)
