"""Copia completa de la base de datos, para descargarla desde el admin (18-11-2026).

El jefe de RRHH (un Administrador) la prepara y la descarga en Soporte → Copia de la
base de datos, igual que el registro de errores, sin que informática tenga que entrar
en el servidor. Sirve para que el desarrollador reproduzca con los datos reales los
errores de la empresa.

* La hace `pg_dump` (formato propio de PostgreSQL, comprimido) en un PROCESO APARTE:
  una base grande tarda más que el tiempo máximo de una petición y el servidor la
  cortaría a medias. La página se recarga sola hasta que está lista.
* Mientras se hace, el fichero acaba en `.parcial`; al terminar bien se renombra a
  `.dump`. Si falla, queda un `.error` con el mensaje de pg_dump.
* La carpeta (`COPIAS_DIR` en `core/.env`; por defecto `copias_bd` dentro de la
  carpeta de Orbith) no la sirve Nginx: solo se descarga desde el admin. Las copias
  llevan los datos personales de todos los trabajadores, así que se borran solas a
  las 24 horas.
* La contraseña de la base llega a pg_dump por variable de entorno, nunca en la orden
  (la orden de un proceso la puede ver cualquier usuario del servidor).
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PREFIJO = 'orbith-copia-'
EXTENSION = '.dump'
PARCIAL = '.parcial'
ERROR = '.error'
#: Las copias (y sus errores) más antiguas se borran solas.
HORAS_QUE_SE_GUARDAN = 24
#: Una copia «preparándose» desde hace más se da por muerta (se reinició el servidor).
HORAS_MAXIMAS_PREPARANDO = 2


def carpeta():
    from django.conf import settings
    return Path(settings.CARPETA_COPIAS_BD)


def _de_la_carpeta(sufijo):
    raiz = carpeta()
    if not raiz.is_dir():
        return []
    return sorted((f for f in raiz.iterdir()
                   if f.is_file() and f.name.startswith(PREFIJO) and f.name.endswith(sufijo)),
                  key=lambda f: f.name, reverse=True)


def copias():
    """Las copias terminadas, de la más reciente a la más antigua."""
    return _de_la_carpeta(EXTENSION)


def en_preparacion():
    return _de_la_carpeta(EXTENSION + PARCIAL)


def errores():
    return _de_la_carpeta(ERROR)


def _horas(fichero):
    return (time.time() - fichero.stat().st_mtime) / 3600


def borrar_antiguas():
    for fichero in copias() + errores():
        if _horas(fichero) > HORAS_QUE_SE_GUARDAN:
            fichero.unlink(missing_ok=True)
    for fichero in en_preparacion():
        if _horas(fichero) > HORAS_MAXIMAS_PREPARANDO:
            fichero.unlink(missing_ok=True)


def programa():
    """Ruta de pg_dump, o None si el servidor no lo tiene."""
    return shutil.which('pg_dump')


def preparar():
    """Lanza la copia en un proceso aparte y devuelve el nombre que tendrá al terminar.

    Lanza `RuntimeError` con el motivo, en español, si no se puede empezar.
    """
    from django.conf import settings
    from django.utils import timezone

    pg_dump = programa()
    if not pg_dump:
        raise RuntimeError('El servidor no tiene pg_dump, el programa de PostgreSQL que hace '
                           'la copia. Avise a informática.')
    if en_preparacion():
        raise RuntimeError('Ya se está preparando una copia. Espere a que termine.')

    raiz = carpeta()
    raiz.mkdir(parents=True, exist_ok=True)
    nombre = f'{PREFIJO}{timezone.localtime():%Y-%m-%d_%H%M%S}{EXTENSION}'
    final = raiz / nombre
    parcial = raiz / (nombre + PARCIAL)
    parcial.touch()

    base = settings.DATABASES['default']
    orden = [pg_dump, '-Fc', '-d', base['NAME'], '-U', base['USER'], '-f', str(parcial)]
    if base.get('HOST'):
        orden += ['-h', base['HOST']]
    if base.get('PORT'):
        orden += ['-p', str(base['PORT'])]
    entorno = dict(os.environ, PGPASSWORD=base.get('PASSWORD') or '')

    opciones = {}
    if os.name == 'nt':
        opciones['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        opciones['start_new_session'] = True
    # `-I`: el proceso no mira la carpeta de este fichero (core/) al importar, así que
    # ningún módulo de Orbith puede hacerse pasar por uno de Python.
    subprocess.Popen(
        [sys.executable, '-I', str(Path(__file__).resolve()), str(parcial), str(final), *orden],
        env=entorno, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, **opciones)
    return nombre


def ejecutar(parcial, final, orden):
    """Lo que hace el proceso aparte: pg_dump y, según termine, `.dump` o `.error`."""
    parcial, final = Path(parcial), Path(final)
    try:
        resultado = subprocess.run(orden, stdin=subprocess.DEVNULL, capture_output=True)
        if resultado.returncode == 0:
            parcial.replace(final)
            return True
        mensaje = resultado.stderr.decode('utf-8', errors='replace').strip()
    except Exception as exc:
        mensaje = str(exc)
    final.with_suffix(ERROR).write_text(
        mensaje or 'pg_dump terminó con un error sin mensaje.', encoding='utf-8')
    parcial.unlink(missing_ok=True)
    return False


if __name__ == '__main__':
    ejecutar(sys.argv[1], sys.argv[2], sys.argv[3:])
