"""Diagnóstico del servidor (24-10-2026), visible en el admin de Django.

Nace del problema del logo y los avatares que desaparecen tras cada
actualización: en el servidor no hay forma de ver qué pasa, así que Orbith lo
cuenta desde dentro. Solo LEE, salvo un fichero de prueba diminuto
(`FICHERO_PRUEBA`) que escribe en la carpeta de ficheros subidos para que el
navegador compruebe quién sirve `/media/` y desde qué carpeta.
"""

import os
from pathlib import Path

from django.conf import settings
from django.utils import timezone

FICHERO_PRUEBA = '_diagnostico_orbith.txt'


def _carpeta(ruta):
    ruta = Path(ruta)
    datos = {'ruta': str(ruta), 'existe': ruta.is_dir(), 'escribible': False, 'ficheros': 0}
    if datos['existe']:
        datos['escribible'] = os.access(ruta, os.W_OK)
        try:
            datos['ficheros'] = sum(1 for f in ruta.rglob('*') if f.is_file())
        except OSError:
            pass
    return datos


def _fichero(campo):
    """`{'nombre', 'existe'}` de un ImageField, o None si está vacío."""
    if not campo:
        return None
    try:
        return {'nombre': campo.name, 'existe': os.path.isfile(campo.path)}
    except (ValueError, OSError):
        return {'nombre': campo.name, 'existe': False}


def escribir_fichero_de_prueba():
    """Deja en MEDIA_ROOT un texto con la hora. Devuelve su URL o None."""
    try:
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        ruta = Path(settings.MEDIA_ROOT) / FICHERO_PRUEBA
        ruta.write_text('Orbith %s' % timezone.localtime().isoformat(), encoding='utf-8')
        return settings.MEDIA_URL.rstrip('/') + '/' + FICHERO_PRUEBA
    except OSError:
        return None


def datos():
    from configuracion.models import Configuracion
    from usuarios.models import CustomUser

    base = Path(settings.BASE_DIR)
    hermanas = []
    try:
        for carpeta in sorted(p for p in base.parent.iterdir() if p.is_dir()):
            media = carpeta / 'media'
            hermanas.append({
                'nombre': carpeta.name,
                'actual': carpeta == base,
                'media_ficheros': (sum(1 for f in media.rglob('*') if f.is_file())
                                   if media.is_dir() else None),
            })
    except OSError:
        pass

    config = Configuracion.objects.first()
    con_avatar = CustomUser.objects.exclude(avatar='').exclude(avatar__isnull=True)
    avatares_faltan = [u.username for u in con_avatar
                       if not (_fichero(u.avatar) or {}).get('existe')]

    return {
        'base_dir': str(base),
        'carpeta_superior': str(base.parent),
        'hermanas': hermanas,
        'media': _carpeta(settings.MEDIA_ROOT),
        'media_url': settings.MEDIA_URL,
        'media_desde_env': bool(os.environ.get('MEDIA_DIR')) or _media_en_env(),
        'debug': settings.DEBUG,
        'logo': _fichero(config.logo) if config else None,
        'avatares_total': con_avatar.count(),
        'avatares_faltan': avatares_faltan,
    }


def _media_en_env():
    """¿Hay una línea MEDIA_DIR en core/.env? (sin mostrar su valor aquí)."""
    try:
        texto = (Path(settings.BASE_DIR) / 'core' / '.env').read_text(encoding='utf-8')
    except OSError:
        return False
    return any(linea.strip().startswith('MEDIA_DIR') for linea in texto.splitlines())
