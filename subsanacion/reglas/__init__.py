"""Registro y autodescubrimiento de reglas.

`autodescubrir_reglas()` importa todos los módulos de este paquete. Las clases se
registran solas al heredar de `ReglaBase`, así que **añadir una regla es crear un
archivo con una clase**: no hay ninguna lista que mantener aquí.
"""

import importlib
import pkgutil

from ..constantes import CLAVES_MODULOS
from .base import HallazgoDetectado, ReglaBase, _REGISTRO, registrar  # noqa: F401

# Módulos de este paquete que no contienen reglas.
_MODULOS_EXCLUIDOS = {'base'}

_descubiertas = False


def autodescubrir_reglas():
    """Importa los módulos de reglas. Idempotente: se puede llamar varias veces.

    La llama `SubsanacionConfig.ready()`. Importar un módulo de reglas no toca la
    base de datos: las reglas solo declaran atributos y resuelven su modelo con
    `apps.get_model()` dentro de `ejecutar()`.
    """
    global _descubiertas
    if _descubiertas:
        return

    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith('_') or info.name in _MODULOS_EXCLUIDOS:
            continue
        importlib.import_module(f'{__name__}.{info.name}')

    _descubiertas = True


def obtener_reglas(modulo=None, solo_activas=True):
    """Devuelve instancias de reglas, en orden de declaración.

    Se instancian en cada llamada a propósito: las reglas son sin estado, y una
    instancia nueva por análisis evita que una regla arrastre datos de un barrido al
    siguiente.
    """
    autodescubrir_reglas()
    reglas = []
    for clase in _REGISTRO.values():
        if solo_activas and not clase.activa:
            continue
        if modulo is not None and clase.modulo != modulo:
            continue
        reglas.append(clase())
    return reglas


def obtener_regla(codigo):
    """Devuelve una instancia de la regla, o None si el código no existe."""
    autodescubrir_reglas()
    clase = _REGISTRO.get(codigo)
    return clase() if clase is not None else None


def reglas_por_modulo(solo_activas=True):
    """{clave_modulo: [reglas]} para todas las categorías, incluidas las vacías.

    Devolver también las categorías sin reglas es deliberado: el análisis recorre
    todas y el dashboard las muestra todas, así que una categoría en la que aún no
    hay reglas debe aparecer como analizada y sin hallazgos, no desaparecer.
    """
    autodescubrir_reglas()
    agrupadas = {clave: [] for clave in CLAVES_MODULOS}
    for regla in obtener_reglas(solo_activas=solo_activas):
        agrupadas[regla.modulo].append(regla)
    return agrupadas


def total_reglas(solo_activas=True):
    return len(obtener_reglas(solo_activas=solo_activas))
