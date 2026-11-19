"""Diagnóstico del servidor y ENSAYO de actualización desde el admin (18-11-2026).

Seguridad Informática autorizó que el especialista de RRHH (un Administrador)
actualice Orbith desde la web, sin informática. Antes de hacerlo de verdad hay que
saber cómo está montado el servidor, así que esta versión trae dos cosas que NO
tocan el Orbith en uso:

* **Diagnóstico** (`diagnostico`): cómo arranca Orbith, su servicio, Nginx, carpetas,
  permisos, espacio y PostgreSQL. Solo lee; nunca enseña contraseñas.
* **Ensayo** (`ensayar`): con el paquete subido por trozos (`recibir_trozo`, así cabe
  en el límite de 1 MB de Nginx), lo comprueba con su lista de huellas, prepara la
  versión nueva en una carpeta aparte, instala sus paquetes de Python sin internet,
  ejecuta `check` y prueba los cambios de la base en una COPIA de la base. Corre en
  un proceso aparte (`manage.py ensayar_actualizacion`) y lo apunta todo en un
  registro que se descarga desde el admin (Soporte → Actualizar Orbith).

La actualización real llegará en la versión siguiente, con lo que diga este registro.
"""

import getpass
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

#: Lista de huellas que va dentro de cada paquete: «sha256  ruta» por archivo.
MANIFIESTO = 'despliegue/MANIFIESTO.txt'
#: Trozos de la subida: por debajo del límite de 1 MB que Nginx trae por defecto.
TAMANO_TROZO = 512 * 1024
#: Tamaño máximo de un paquete (hoy son unos 76 MB).
TAMANO_MAXIMO = 400 * 1024 * 1024
PATRON_PAQUETE = re.compile(r'^orbith-[0-9][\w.\-]*\.tar\.gz$')
#: Registros de ensayo que se guardan; los más antiguos se borran solos.
DIAS_QUE_SE_GUARDAN = 60
#: Un ensayo «en curso» desde hace más se da por muerto (se reinició el servidor).
HORAS_MAXIMAS_ENSAYO = 2
#: Palabras que delatan un secreto en una línea de configuración: su valor no se enseña.
SECRETOS = re.compile(r'(PASSWORD|PASSWD|SECRET|TOKEN|CLAVE|KEY)', re.IGNORECASE)


# --------------------------------------------------------------------------
# Carpetas
# --------------------------------------------------------------------------

def carpeta():
    from django.conf import settings
    return Path(settings.CARPETA_ACTUALIZACIONES)


def _sub(nombre):
    ruta = carpeta() / nombre
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def subidas():
    return _sub('subidas')


def registros():
    return _sub('registros')


def trabajo():
    return _sub('ensayos')


def paquetes_subidos():
    if not (carpeta() / 'subidas').is_dir():
        return []
    return sorted((f for f in subidas().iterdir() if f.is_file() and PATRON_PAQUETE.match(f.name)),
                  key=lambda f: f.stat().st_mtime, reverse=True)


def lista_de_registros():
    if not (carpeta() / 'registros').is_dir():
        return []
    return sorted((f for f in registros().iterdir() if f.is_file() and f.suffix == '.log'),
                  key=lambda f: f.name, reverse=True)


def borrar_antiguos():
    limite = time.time() - DIAS_QUE_SE_GUARDAN * 86400
    for fichero in lista_de_registros() + paquetes_subidos():
        if fichero.stat().st_mtime < limite:
            fichero.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def sin_secretos(texto):
    """Quita el valor de las líneas que parecen llevar una contraseña o una clave."""
    lineas = []
    for linea in str(texto).splitlines():
        if SECRETOS.search(linea) and ('=' in linea or ':' in linea):
            separador = '=' if '=' in linea else ':'
            linea = linea.split(separador, 1)[0] + separador + ' ***'
        lineas.append(linea)
    return '\n'.join(lineas)


def ejecutar(orden, timeout=120, entorno=None, cwd=None):
    """`(codigo, salida)` de una orden; nunca lanza (el fallo va en la salida)."""
    try:
        resultado = subprocess.run(orden, capture_output=True, text=True, timeout=timeout,
                                   env=entorno, cwd=cwd, stdin=subprocess.DEVNULL,
                                   encoding='utf-8', errors='replace')
        return resultado.returncode, (resultado.stdout or '') + (resultado.stderr or '')
    except FileNotFoundError:
        return 127, 'No se encuentra el programa «%s».' % orden[0]
    except subprocess.TimeoutExpired:
        return 124, 'Tardó más de %d segundos y se detuvo.' % timeout
    except OSError as exc:
        return 1, str(exc)


def _leer(ruta, limite=200_000):
    try:
        with open(ruta, encoding='utf-8', errors='replace') as fichero:
            return fichero.read(limite)
    except OSError as exc:
        return None if isinstance(exc, FileNotFoundError) else '(no se puede leer: %s)' % exc


def _escribible(ruta):
    ruta = Path(ruta)
    return 'sí' if ruta.exists() and os.access(ruta, os.W_OK) else ('no existe' if not ruta.exists() else 'NO')


def _mb(octetos):
    return '%.0f MB' % (octetos / 1048576)


# --------------------------------------------------------------------------
# 1. Diagnóstico (solo lee)
# --------------------------------------------------------------------------

def _cadena_de_procesos():
    """Quién arrancó a quién, desde este proceso hasta el 1 (solo Linux)."""
    if not Path('/proc/self').exists():
        return ['(no es Linux: no aplica)']
    lineas, pid = [], os.getpid()
    for _ in range(12):
        orden = (_leer('/proc/%d/cmdline' % pid) or '').replace('\x00', ' ').strip()
        estado = _leer('/proc/%d/status' % pid) or ''
        padre = re.search(r'^PPid:\s*(\d+)', estado, re.M)
        cwd = ''
        try:
            cwd = os.readlink('/proc/%d/cwd' % pid)
        except OSError:
            pass
        lineas.append('pid %d: %s%s' % (pid, sin_secretos(orden) or '(sin datos)', ' [cwd %s]' % cwd if cwd else ''))
        if not padre or int(padre.group(1)) <= 1:
            break
        pid = int(padre.group(1))
    return lineas


def _servicio():
    """El servicio de systemd que arranca Orbith, si lo hay."""
    cgroup = _leer('/proc/self/cgroup') or ''
    unidad = re.search(r'([\w@.\-]+\.service)', cgroup)
    if not unidad:
        return None, ['(Orbith no corre dentro de un servicio de systemd, o no se puede saber)']
    unidad = unidad.group(1)
    lineas = ['Servicio: %s' % unidad]
    _, salida = ejecutar(['systemctl', 'show', unidad, '--no-pager', '--property=Id,FragmentPath,ExecStart,'
                          'WorkingDirectory,User,Group,Restart,RestartUSec,MainPID,ActiveState,'
                          'TimeoutStopUSec,KillMode'], timeout=20)
    lineas += ['  ' + linea for linea in sin_secretos(salida).splitlines()]
    _, salida = ejecutar(['systemctl', 'cat', unidad, '--no-pager'], timeout=20)
    lineas += ['--- systemctl cat %s ---' % unidad] + sin_secretos(salida).splitlines()
    return unidad, lineas


def _nginx():
    lineas = []
    ficheros = sorted(set(glob.glob('/etc/nginx/nginx.conf') + glob.glob('/etc/nginx/sites-enabled/*')
                          + glob.glob('/etc/nginx/conf.d/*.conf')))
    if not ficheros:
        return ['(no se encuentran ficheros de Nginx en /etc/nginx, o no es Linux)']
    for ruta in ficheros:
        contenido = _leer(ruta)
        if contenido is None:
            continue
        importante = 'proxy_pass' in contenido or 'orbith' in contenido.lower() or 'server_name' in contenido
        if ruta.endswith('nginx.conf') and not importante:
            claves = [l for l in contenido.splitlines() if re.search(
                r'client_max_body_size|proxy_read_timeout|user |worker_processes|include', l)]
            lineas += ['--- %s (líneas importantes) ---' % ruta] + claves
        else:
            lineas += ['--- %s ---' % ruta] + sin_secretos(contenido).splitlines()[:400]
    cuerpo = '\n'.join(lineas)
    tope = re.findall(r'client_max_body_size\s+([^;]+);', cuerpo)
    lineas.append('client_max_body_size: %s' % (', '.join(tope) if tope else 'no aparece (Nginx usa 1m por defecto)'))
    return lineas


def _postgres():
    from django.db import connection
    lineas = []
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT version()')
            lineas.append('Servidor: %s' % cursor.fetchone()[0])
            cursor.execute('SELECT current_user, current_database(), pg_database_size(current_database())')
            usuario, base, tamano = cursor.fetchone()
            lineas.append('Usuario de la base: %s · base: %s · tamaño: %s' % (usuario, base, _mb(tamano)))
            cursor.execute('SELECT rolcreatedb, rolsuper FROM pg_roles WHERE rolname = current_user')
            crear, superusuario = cursor.fetchone()
            lineas.append('Puede crear bases (CREATEDB): %s · superusuario: %s'
                          % ('sí' if crear else 'NO', 'sí' if superusuario else 'no'))
    except Exception as exc:  # el diagnóstico nunca debe romperse
        lineas.append('(no se pudo consultar PostgreSQL: %s)' % exc)
    for programa in ('pg_dump', 'pg_restore', 'psql'):
        ruta = shutil.which(programa)
        version = ejecutar([ruta, '--version'], timeout=20)[1].strip() if ruta else ''
        lineas.append('%s: %s %s' % (programa, ruta or 'NO ENCONTRADO', version))
    return lineas


def puede_crear_bases():
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user')
            return bool(cursor.fetchone()[0])
    except Exception:
        return False


def _python_base():
    """El Python con el que se creó el venv de Orbith (el que creará el del ensayo)."""
    return getattr(sys, '_base_executable', None) or shutil.which('python3') or sys.executable


def diagnostico():
    """El informe completo, en texto. Solo lee."""
    from django.conf import settings

    from core.changelog import ORBITH_VERSION

    base = Path(settings.BASE_DIR)
    padre = base.parent
    secciones = []

    try:
        usuario = getpass.getuser()
    except Exception:
        usuario = '(desconocido)'
    secciones.append(('Orbith', [
        'Versión: %s' % ORBITH_VERSION,
        'Carpeta: %s' % base,
        'Python: %s (%s)' % (sys.version.split()[0], sys.executable),
        'Entorno (venv): %s' % sys.prefix,
        'Python base para crear entornos: %s' % _python_base(),
        'Usuario del sistema: %s · proceso %d' % (usuario, os.getpid()),
        'DEBUG: %s' % settings.DEBUG,
    ]))
    secciones.append(('Cómo arranca Orbith (procesos)', _cadena_de_procesos()))
    secciones.append(('Servicio (systemd)', _servicio()[1]))
    secciones.append(('Nginx', _nginx()))

    libre = shutil.disk_usage(padre).free if padre.exists() else 0
    carpetas = ['Carpeta de las versiones: %s · escribible: %s · libre: %s' % (padre, _escribible(padre), _mb(libre))]
    for nombre, ruta in (('Orbith', base), ('Fotos (MEDIA)', settings.MEDIA_ROOT),
                         ('Registro de errores', settings.CARPETA_REGISTRO_ERRORES),
                         ('Copias de la base', settings.CARPETA_COPIAS_BD),
                         ('Actualizaciones', settings.CARPETA_ACTUALIZACIONES),
                         ('Estáticos', settings.STATIC_ROOT)):
        carpetas.append('%s: %s · escribible: %s' % (nombre, ruta, _escribible(ruta)))
    try:
        hermanas = sorted(p.name for p in padre.iterdir() if p.name.lower().startswith('orbith'))
    except OSError:
        hermanas = []
    carpetas.append('Carpetas de Orbith junto a esta: %s' % (', '.join(hermanas) or '(ninguna)'))
    secciones.append(('Carpetas, permisos y espacio', carpetas))
    secciones.append(('PostgreSQL', _postgres()))

    herramientas = []
    _, salida = ejecutar([_python_base(), '-c', 'import ensurepip, venv; print("venv y ensurepip: sí")'], timeout=60)
    herramientas.append(salida.strip() or 'venv: no se pudo comprobar')
    herramientas.append('pip del entorno: %s' % (ejecutar([sys.executable, '-m', 'pip', '--version'], timeout=60)[1].strip()))
    herramientas.append('Subida máxima de Django: %s en memoria' % _mb(settings.DATA_UPLOAD_MAX_MEMORY_SIZE or 0))
    secciones.append(('Herramientas', herramientas))

    salida = ['DIAGNÓSTICO DEL SERVIDOR · Orbith %s · %s' % (ORBITH_VERSION, datetime.now().strftime('%d/%m/%Y %H:%M:%S')),
              '=' * 100]
    for titulo, lineas in secciones:
        salida += ['', '## ' + titulo] + [str(l) for l in lineas]
    return '\n'.join(salida)


# --------------------------------------------------------------------------
# 2. Subida por trozos
# --------------------------------------------------------------------------

class ErrorDeActualizacion(Exception):
    """Mensaje para el Administrador, en español."""


def recibir_trozo(nombre, indice, total, datos):
    """Añade un trozo del paquete. Devuelve la ruta del paquete al llegar el último.

    Los trozos llegan en orden (el navegador espera a cada uno): el 0 empieza de cero.
    """
    if not PATRON_PAQUETE.match(nombre or ''):
        raise ErrorDeActualizacion('El archivo tiene que ser el paquete de Orbith: orbith-<versión>.tar.gz.')
    if not (0 <= indice < total) or total * TAMANO_TROZO > TAMANO_MAXIMO + TAMANO_TROZO:
        raise ErrorDeActualizacion('La subida no es válida. Vuelva a empezarla.')
    parcial = subidas() / (nombre + '.parcial')
    if indice == 0:
        parcial.unlink(missing_ok=True)
    elif not parcial.exists() or parcial.stat().st_size != indice * TAMANO_TROZO:
        raise ErrorDeActualizacion('Se perdió un trozo de la subida. Vuelva a empezarla.')
    with open(parcial, 'ab') as fichero:
        fichero.write(datos)
    if indice < total - 1:
        return None
    final = subidas() / nombre
    parcial.replace(final)
    return final


# --------------------------------------------------------------------------
# 3. Lista de huellas del paquete
# --------------------------------------------------------------------------

def huella(ruta):
    sha = hashlib.sha256()
    with open(ruta, 'rb') as fichero:
        for bloque in iter(lambda: fichero.read(1 << 20), b''):
            sha.update(bloque)
    return sha.hexdigest()


def escribir_manifiesto(raiz):
    """Crea `despliegue/MANIFIESTO.txt` con la huella de cada archivo de `raiz` (al
    preparar el paquete). Rutas con «/», ordenadas."""
    raiz = Path(raiz)
    lineas = []
    for ruta in sorted(p for p in raiz.rglob('*') if p.is_file()):
        relativa = ruta.relative_to(raiz).as_posix()
        if relativa != MANIFIESTO:
            lineas.append('%s  %s' % (huella(ruta), relativa))
    destino = raiz / MANIFIESTO
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    return len(lineas)


def comprobar_manifiesto(raiz):
    """Lista de problemas (vacía si el paquete está entero)."""
    raiz = Path(raiz)
    texto = _leer(raiz / MANIFIESTO)
    if texto is None:
        return ['El paquete no trae su lista de huellas (%s): no se puede comprobar que esté entero.' % MANIFIESTO]
    esperados = {}
    for linea in texto.splitlines():
        if linea.strip():
            sha, _, relativa = linea.partition('  ')
            esperados[relativa] = sha
    problemas = []
    for relativa, sha in esperados.items():
        ruta = raiz / relativa
        if not ruta.is_file():
            problemas.append('Falta %s.' % relativa)
        elif huella(ruta) != sha:
            problemas.append('%s está dañado o cambiado.' % relativa)
    sobrantes = [p.relative_to(raiz).as_posix() for p in raiz.rglob('*')
                 if p.is_file() and p.relative_to(raiz).as_posix() not in esperados
                 and p.relative_to(raiz).as_posix() != MANIFIESTO]
    problemas += ['%s no está en la lista de huellas.' % s for s in sobrantes[:20]]
    return problemas


# --------------------------------------------------------------------------
# 4. El ensayo
# --------------------------------------------------------------------------

def _en_curso():
    return carpeta() / 'ENSAYO_EN_CURSO'


def ensayo_en_curso():
    """Nombre del registro del ensayo en marcha, o None. Limpia uno muerto."""
    marca = _en_curso()
    if not marca.exists():
        return None
    if time.time() - marca.stat().st_mtime > HORAS_MAXIMAS_ENSAYO * 3600:
        marca.unlink(missing_ok=True)
        return None
    return (_leer(marca) or '').strip() or None


def lanzar_ensayo(paquete):
    """Empieza el ensayo en un proceso aparte. Devuelve el nombre de su registro."""
    paquete = Path(paquete)
    if paquete.parent.resolve() != subidas().resolve() or not PATRON_PAQUETE.match(paquete.name):
        raise ErrorDeActualizacion('Ese paquete no está entre los subidos.')
    if ensayo_en_curso():
        raise ErrorDeActualizacion('Ya hay un ensayo en marcha. Espere a que termine.')
    nombre = 'ensayo-%s.log' % datetime.now().strftime('%Y-%m-%d_%H%M%S')
    _en_curso().write_text(nombre, encoding='utf-8')
    from django.conf import settings
    opciones = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
                if os.name == 'nt' else {'start_new_session': True})
    subprocess.Popen([sys.executable, str(Path(settings.BASE_DIR) / 'manage.py'), 'ensayar_actualizacion',
                      str(paquete), nombre], cwd=str(settings.BASE_DIR), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **opciones)
    return nombre


class Registro:
    """El registro del ensayo: cada paso, con ✓ o ✗ y lo que dijo."""

    def __init__(self, nombre):
        self.ruta = registros() / nombre
        self.errores = 0
        self.avisos = 0

    def escribir(self, texto=''):
        with open(self.ruta, 'a', encoding='utf-8') as fichero:
            fichero.write(texto + '\n')
        _en_curso().touch(exist_ok=True)   # sigue vivo

    def paso(self, titulo):
        self.escribir('')
        self.escribir('>>> %s  [%s]' % (titulo, datetime.now().strftime('%H:%M:%S')))

    def bien(self, texto):
        self.escribir('    ✓ ' + texto)

    def mal(self, texto, detalle=''):
        self.errores += 1
        self.escribir('    ✗ ERROR: ' + texto)
        if detalle:
            self.escribir('      ' + sin_secretos(detalle.strip()[-4000:]).replace('\n', '\n      '))

    def aviso(self, texto):
        self.avisos += 1
        self.escribir('    ! AVISO: ' + texto)


def _bin(venv):
    return Path(venv) / ('Scripts' if os.name == 'nt' else 'bin')


def _extraer(paquete, destino):
    """Descomprime sin dejar escribir fuera de `destino`. Devuelve la carpeta de Orbith."""
    with tarfile.open(paquete, 'r:gz') as tar:
        miembros = tar.getmembers()
        raices = {m.name.split('/', 1)[0] for m in miembros}
        if len(raices) != 1 or not next(iter(raices)).startswith('orbith-'):
            raise ErrorDeActualizacion('El paquete no trae una sola carpeta orbith-<versión>.')
        for m in miembros:
            if m.name.startswith('/') or '..' in Path(m.name).parts or not (m.isfile() or m.isdir()):
                raise ErrorDeActualizacion('El paquete trae una ruta no permitida: %s' % m.name)
        if sys.version_info >= (3, 12):
            tar.extractall(destino, filter='data')
        else:
            tar.extractall(destino)
    return Path(destino) / next(iter(raices))


def _version_de(raiz):
    texto = _leer(Path(raiz) / 'core' / 'changelog.py') or ''
    texto = texto[texto.find('CHANGELOG = ['):]
    encontrado = re.search(r'"version":\s*"([^"]+)"', texto)
    return encontrado.group(1) if encontrado else None


def _probar_base(nueva, python, entorno, r):
    """Los cambios de la base en una COPIA: nunca en la base en uso."""
    from django.conf import settings
    from django.db import connection

    base = settings.DATABASES['default']
    r.paso('Cambios de la base que traería la versión nueva (solo se listan)')
    codigo, salida = ejecutar([python, 'manage.py', 'migrate', '--plan'], timeout=600, entorno=entorno, cwd=nueva)
    if codigo:
        r.mal('No se pudo calcular la lista de cambios de la base.', salida)
    else:
        r.bien('Lista de cambios:')
        r.escribir('      ' + (salida.strip() or '(ninguno)').replace('\n', '\n      '))

    r.paso('Probar esos cambios en una COPIA de la base')
    if not puede_crear_bases():
        r.aviso('El usuario de PostgreSQL no puede crear bases (CREATEDB): no se probaron en una copia. '
                'La actualización real los aplicaría sin ensayo previo.')
        return
    copia = 'orbith_ensayo_%s' % datetime.now().strftime('%Y%m%d%H%M%S')
    volcado = trabajo() / (copia + '.dump')
    con = ['-U', base['USER']] + (['-h', base['HOST']] if base.get('HOST') else []) \
        + (['-p', str(base['PORT'])] if base.get('PORT') else [])
    entorno_pg = dict(os.environ, PGPASSWORD=base.get('PASSWORD') or '')
    creada = False
    try:
        codigo, salida = ejecutar([shutil.which('pg_dump') or 'pg_dump', '-Fc', *con, '-d', base['NAME'],
                                   '-f', str(volcado)], timeout=1800, entorno=entorno_pg)
        if codigo:
            r.mal('No se pudo copiar la base.', salida)
            return
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE "%s"' % copia)
        creada = True
        codigo, salida = ejecutar([shutil.which('pg_restore') or 'pg_restore', '--no-owner', '--no-privileges',
                                   *con, '-d', copia, str(volcado)], timeout=1800, entorno=entorno_pg)
        if codigo:
            r.mal('No se pudo restaurar la copia.', salida)
            return
        r.bien('Copia de la base creada: %s (%s).' % (copia, _mb(volcado.stat().st_size)))
        entorno_copia = dict(entorno, DATABASE_NAME=copia)
        codigo, salida = ejecutar([python, 'manage.py', 'migrate', '--noinput'], timeout=3600,
                                  entorno=entorno_copia, cwd=nueva)
        if codigo:
            r.mal('Los cambios de la base FALLAN en la copia. La actualización real fallaría igual.', salida)
            return
        r.bien('Los cambios de la base se aplican bien en la copia.')
        codigo, salida = ejecutar([python, 'manage.py', 'reparar_tipos_historico'], timeout=1800,
                                  entorno=entorno_copia, cwd=nueva)
        if codigo:
            r.aviso('El arreglo del histórico falló en la copia: %s' % salida.strip()[-500:])
        else:
            r.bien('Arreglo del histórico (simulado): ' + ' · '.join(
                l.strip() for l in salida.splitlines() if l.strip() and not l.strip().startswith(('·', '-')))[:600])
    finally:
        if creada:
            try:
                with connection.cursor() as cursor:
                    cursor.execute('DROP DATABASE IF EXISTS "%s"' % copia)
                r.bien('Copia de la base borrada.')
            except Exception as exc:
                r.aviso('No se pudo borrar la copia %s: bórrela a mano (%s).' % (copia, exc))
        volcado.unlink(missing_ok=True)


def ensayar(paquete, nombre_registro):
    """El ensayo completo. No toca el Orbith en uso ni su base. Escribe el registro."""
    from django.conf import settings

    from core.changelog import ORBITH_VERSION

    r = Registro(nombre_registro)
    carpeta_ensayo = trabajo() / nombre_registro.replace('.log', '')
    try:
        r.escribir('ENSAYO DE ACTUALIZACIÓN · Orbith %s en uso · %s'
                   % (ORBITH_VERSION, datetime.now().strftime('%d/%m/%Y %H:%M:%S')))
        r.escribir('Paquete: %s (%s, huella %s)' % (Path(paquete).name, _mb(Path(paquete).stat().st_size),
                                                  huella(paquete)))
        r.escribir('El ensayo NO toca el Orbith en uso ni su base de datos.')

        r.paso('Diagnóstico del servidor')
        r.escribir(diagnostico())

        r.paso('Abrir el paquete')
        carpeta_ensayo.mkdir(parents=True, exist_ok=True)
        try:
            nueva = _extraer(paquete, carpeta_ensayo)
        except (ErrorDeActualizacion, tarfile.TarError, OSError, EOFError) as exc:
            r.mal('No se pudo abrir el paquete: %s' % exc)
            return
        version = _version_de(nueva)
        r.bien('Versión del paquete: %s (en uso: %s).' % (version or 'desconocida', ORBITH_VERSION))
        if version == ORBITH_VERSION:
            r.aviso('Es la misma versión que la que está en uso.')

        r.paso('Comprobar que el paquete está entero (lista de huellas)')
        problemas = comprobar_manifiesto(nueva)
        if problemas:
            r.mal('El paquete no está entero:', '\n'.join(problemas[:30]))
            return
        r.bien('Todos los archivos coinciden con su huella.')

        r.paso('Configuración: copiar core/.env de la versión en uso')
        shutil.copy2(Path(settings.BASE_DIR) / 'core' / '.env', nueva / 'core' / '.env')
        r.bien('Copiado (no se muestra su contenido).')

        r.paso('Entorno de Python e instalación de paquetes SIN internet')
        python_base = _python_base()
        codigo, salida = ejecutar([python_base, '-m', 'venv', str(nueva / 'venv')], timeout=600)
        if codigo:
            r.mal('No se pudo crear el entorno de Python con %s.' % python_base, salida)
            return
        python = str(_bin(nueva / 'venv') / ('python.exe' if os.name == 'nt' else 'python'))
        codigo, salida = ejecutar([python, '-m', 'pip', 'install', '--no-index',
                                   '--find-links=%s' % (nueva / 'despliegue' / 'paquetes'),
                                   '-r', str(nueva / 'requirements.txt')], timeout=1800)
        if codigo:
            r.mal('No se pudieron instalar los paquetes de Python.', salida)
            return
        r.bien('Paquetes instalados: ' + (salida.strip().splitlines() or [''])[-1][:300])

        entorno = {k: v for k, v in os.environ.items() if not k.startswith('DJANGO_')}
        entorno['PYTHONIOENCODING'] = 'utf-8'
        r.paso('Comprobar la versión nueva (manage.py check)')
        codigo, salida = ejecutar([python, 'manage.py', 'check'], timeout=600, entorno=entorno, cwd=nueva)
        if codigo:
            r.mal('La versión nueva no pasa la comprobación.', salida)
            return
        r.bien(salida.strip().splitlines()[-1] if salida.strip() else 'Sin problemas.')

        r.paso('Archivos estáticos (en la carpeta del ensayo)')
        codigo, salida = ejecutar([python, 'manage.py', 'collectstatic', '--noinput'], timeout=900,
                                  entorno=entorno, cwd=nueva)
        if codigo:
            r.mal('Falló collectstatic.', salida)
        else:
            r.bien(salida.strip().splitlines()[-1] if salida.strip() else 'Hecho.')

        _probar_base(nueva, python, entorno, r)
    except Exception as exc:   # cualquier fallo inesperado queda en el registro
        import traceback
        r.mal('Fallo inesperado del ensayo: %s' % exc, traceback.format_exc())
    finally:
        try:
            shutil.rmtree(carpeta_ensayo, ignore_errors=True)
            r.paso('Limpieza')
            r.bien('Carpeta del ensayo borrada (con la copia de core/.env).')
        finally:
            r.escribir('')
            r.escribir('=' * 100)
            r.escribir('RESULTADO: %s · %d errores · %d avisos'
                       % ('ENSAYO CORRECTO' if not r.errores else 'ENSAYO CON ERRORES', r.errores, r.avisos))
            _en_curso().unlink(missing_ok=True)
