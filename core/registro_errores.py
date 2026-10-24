"""Registro de errores en ficheros, uno por día (24-10-2026).

Antes Orbith no guardaba sus errores en ningún sitio: en producción solo salían
por la consola del servidor y nadie podía verlos. Ahora cada error (una
excepción no controlada de una vista o un `logger.exception(...)`) se añade al
fichero del día, `logs/orbith-AAAA-MM-DD.log`, y el Administrador lo consulta o lo
descarga desde el admin de Django (Soporte → Registro de errores).

Por qué un fichero por día escrito «abrir, añadir, cerrar» y no el
`TimedRotatingFileHandler` de Python: en el servidor hay VARIOS procesos de
gunicorn escribiendo a la vez, y ese manejador renombra el fichero a medianoche
desde cada proceso por su cuenta, así que se pisan y se pierden líneas. Aquí
nadie renombra nada: el nombre del fichero ya lleva la fecha, y añadir al final
de un fichero es seguro entre procesos.

Nada de esto puede tumbar Orbith: si la carpeta no existe y no se puede crear, o
no hay permiso para escribir, el error se descarta en silencio.
"""

import logging
import os
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

PREFIJO = 'orbith-'
EXTENSION = '.log'
#: Ficheros más antiguos que esto se borran solos.
DIAS_QUE_SE_GUARDAN = 30


def carpeta():
    from django.conf import settings
    return Path(getattr(settings, 'CARPETA_REGISTRO_ERRORES', '') or '')


def fichero_del_dia(fecha):
    return carpeta() / f'{PREFIJO}{fecha:%Y-%m-%d}{EXTENSION}'


def ficheros():
    """Los ficheros del registro, del más reciente al más antiguo."""
    raiz = carpeta()
    if not str(raiz) or not raiz.is_dir():
        return []
    return sorted((f for f in raiz.iterdir()
                   if f.is_file() and f.name.startswith(PREFIJO) and f.name.endswith(EXTENSION)),
                  key=lambda f: f.name, reverse=True)


def borrar_antiguos():
    limite = timezone.localdate() - timedelta(days=DIAS_QUE_SE_GUARDAN)
    nombre_limite = f'{PREFIJO}{limite:%Y-%m-%d}{EXTENSION}'
    for fichero in ficheros():
        if fichero.name < nombre_limite:
            try:
                fichero.unlink()
            except OSError:
                pass


class ManejadorDiario(logging.Handler):
    """Añade cada registro al fichero del día. Ver el docstring del módulo."""

    def emit(self, record):
        try:
            hoy = timezone.localdate()
            ruta = fichero_del_dia(hoy)
            nuevo = not ruta.exists()
            with open(ruta, 'a', encoding='utf-8') as salida:
                salida.write(self.format(record) + '\n' + '-' * 80 + '\n')
            if nuevo:
                # El primer error de cada día limpia los de hace más de un mes.
                borrar_antiguos()
        except Exception:
            # Un fallo al registrar nunca debe convertirse en otro error.
            pass


def configuracion_logging(ruta_carpeta):
    """El `LOGGING` de settings. Sin carpeta (`None`) o sin una utilizable, solo la
    consola."""
    manejadores = {'consola': {'class': 'logging.StreamHandler', 'level': 'ERROR'}}
    destino = ['consola']
    try:
        if ruta_carpeta is None:
            raise OSError('sin carpeta')
        os.makedirs(ruta_carpeta, exist_ok=True)
        if os.access(ruta_carpeta, os.W_OK):
            manejadores['fichero'] = {
                'class': 'core.registro_errores.ManejadorDiario',
                'level': 'ERROR',
                'formatter': 'detallado',
            }
            destino.append('fichero')
    except OSError:
        pass
    return {
        'version': 1,
        # Se conservan los registradores de Django (django.request, etc.): sus
        # errores suben hasta la raíz y de ahí al fichero.
        'disable_existing_loggers': False,
        'formatters': {
            'detallado': {
                'format': '%(asctime)s  %(levelname)s  [%(name)s]\n%(message)s',
                'datefmt': '%d/%m/%Y %H:%M:%S',
            },
        },
        'handlers': manejadores,
        'root': {'handlers': destino, 'level': 'ERROR'},
    }
