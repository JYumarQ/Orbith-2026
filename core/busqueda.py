"""Búsqueda con prefijos, común a Subsanación, Contratos, Aspirantes y Bajas.

El buscador de esas pantallas acepta, además del texto libre de siempre, prefijos
para afinar la búsqueda cuando hay demasiadas coincidencias:

    E:8855          expediente
    N:Juan Pérez    nombre y/o apellidos
    CI:85010112345  carnet de identidad (vale el principio: CI:8501)
    CA:ayudante     cargo
    U:flor          unidad organizativa (vale parte del nombre: «Florida»)
    COD:CTR-011     código de regla de Subsanación (vale el principio: COD:CTR)

Reglas de escritura (son las que explica la ayuda «?» de cada buscador):

* Mayúsculas o minúsculas, da igual (`e:8855` = `E:8855`).
* Un prefijo abarca todo lo que viene detrás hasta el siguiente prefijo, así que
  `N:Juan Pérez U:Florida` busca el nombre «Juan Pérez» en la unidad «Florida».
* Lo escrito ANTES del primer prefijo es texto libre y se busca como siempre.
* Todo lo escrito tiene que cumplirse a la vez.
* Los acentos no importan: «Perez» encuentra «Pérez».

Cada pantalla decide qué prefijos entiende. Los que no entiende NO filtran nada
(la búsqueda sigue con el resto) y el navegador avisa en pequeño debajo del
buscador (`static/js/busqueda_prefijos.js`).

Sin acentos sin tocar el servidor: en vez de la extensión `unaccent` de
PostgreSQL —que habría que instalar en el servidor de la empresa— se usa
`translate()`, que PostgreSQL trae de serie. El coste es despreciable: estas
búsquedas ya recorren la tabla con `icontains`.
"""

import re
import unicodedata

from django.db.models import Func, TextField, Value
from django.db.models.functions import Lower

#: Prefijos que existen, con su explicación. El orden es el de la ayuda.
PREFIJOS = {
    'E': ('Expediente', 'E:8855'),
    'N': ('Nombre y/o apellidos', 'N:Juan Pérez'),
    'CI': ('Carnet de identidad (vale el principio)', 'CI:85010112345'),
    'CA': ('Cargo', 'CA:ayudante'),
    'U': ('Unidad organizativa (vale parte del nombre)', 'U:flor'),
    'COD': ('Código de regla de Subsanación (vale el principio)', 'COD:CTR-011'),
}

# Más largos primero para que «CA:» no se lea como «C» + «A:».
_PATRON_PREFIJO = re.compile(
    r'(?<!\S)(%s):' % '|'.join(sorted(PREFIJOS, key=len, reverse=True)),
    re.IGNORECASE)

# Vocales acentuadas y eñe, en minúscula (se aplica después de `lower()`).
_CON_ACENTO = 'áàâäéèêëíìîïóòôöúùûüñç'
_SIN_ACENTO = 'aaaaeeeeiiiioooouuuunc'


class Busqueda:
    """Lo que escribió el usuario, separado en texto libre y prefijos."""

    def __init__(self, libre='', prefijos=None):
        self.libre = libre
        #: `{'N': ['Juan Pérez'], 'E': ['8855']}`. Lista porque un prefijo puede
        #: repetirse; cada valor tiene que cumplirse.
        self.prefijos = prefijos or {}

    def __bool__(self):
        return bool(self.libre or self.prefijos)

    def valores(self, prefijo):
        return self.prefijos.get(prefijo, [])


def interpretar(texto):
    """`'García N:Juan E:8855'` → libre `'García'`, prefijos N y E."""
    texto = (texto or '').strip()
    coincidencias = list(_PATRON_PREFIJO.finditer(texto))
    if not coincidencias:
        return Busqueda(libre=texto)

    libre = texto[:coincidencias[0].start()].strip()
    prefijos = {}
    for indice, coincidencia in enumerate(coincidencias):
        fin = (coincidencias[indice + 1].start() if indice + 1 < len(coincidencias)
               else len(texto))
        valor = texto[coincidencia.end():fin].strip()
        if valor:
            prefijos.setdefault(coincidencia.group(1).upper(), []).append(valor)
    return Busqueda(libre=libre, prefijos=prefijos)


def normalizar(texto):
    """Minúsculas y sin acentos, en Python, para comparar con `sin_acentos()`."""
    descompuesto = unicodedata.normalize('NFKD', (texto or '').lower())
    return ''.join(c for c in descompuesto if not unicodedata.combining(c))


def sin_acentos(expresion):
    """La misma normalización que `normalizar()`, hecha por PostgreSQL."""
    return Func(Lower(expresion), Value(_CON_ACENTO), Value(_SIN_ACENTO),
                function='translate', output_field=TextField())


def solo_digitos_sin_ceros(valor):
    """`'00158'` → `'158'`. Un expediente se escribe con o sin ceros delante."""
    valor = valor.strip()
    if valor.isdigit():
        return valor.lstrip('0') or '0'
    return None
