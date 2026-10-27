"""Orden inicial de los nomencladores arrastrables (decisión del 27-10-2026).

A-Z sin distinguir mayúsculas ni acentos, dentro de su lista (los municipios dentro
de su provincia, las familias dentro de su tipo, Instructor y CNCI por separado).
Los roles empiezan con el orden oficial de la escala salarial: Decisorio,
Fundamental y Apoyo; cualquier otro rol va detrás, A-Z.

Solo numera la columna `orden`: no cambia ningún otro dato.
"""
import unicodedata
from itertools import groupby

from django.db import migrations

ROLES_OFICIALES = ('decisorio', 'fundamental', 'apoyo')

#: modelo → (campo por el que se ordena, campo que separa las listas o None)
LISTAS = {
    'NTipoUnidadOrganizativa': ('descripcion', None),
    'NTipoFamilia': ('nombre', None),
    'NFamiliaCargo': ('nombre', 'tipo_familia_id'),
    'NNocturnidad': ('codigo', None),
    'NCondicionLaboralAnormal': ('nombre', None),
    'NProvincia': ('nombre', None),
    'NMunicipio': ('nombre', 'provincia_id'),
    'NCausaAltaBaja': ('descripcion', None),
    'NEspecialidad': ('nombre', None),
    'NNivelPreparacion': ('nombre', None),
    'NTipoContrato': ('descripcion', None),
    'NMotivoContrato': ('descripcion', None),
    'NPagoAdicional': ('descripcion', 'tipo'),
}


def _clave(texto):
    descompuesto = unicodedata.normalize('NFKD', ' '.join(str(texto or '').split()).lower())
    return ''.join(c for c in descompuesto if not unicodedata.combining(c))


def _numerar(registros, campo):
    for posicion, registro in enumerate(sorted(registros, key=lambda r: _clave(getattr(r, campo))), start=1):
        if registro.orden != posicion:
            registro.orden = posicion
            registro.save(update_fields=['orden'])


def ordenar(apps, schema_editor):
    for nombre, (campo, separador) in LISTAS.items():
        Modelo = apps.get_model('nomencladores', nombre)
        todos = list(Modelo.objects.all())
        if separador:
            todos.sort(key=lambda r: str(getattr(r, separador)))
            for _, grupo in groupby(todos, key=lambda r: getattr(r, separador)):
                _numerar(list(grupo), campo)
        else:
            _numerar(todos, campo)

    NRol = apps.get_model('nomencladores', 'NRol')
    roles = sorted(NRol.objects.all(), key=lambda r: (
        ROLES_OFICIALES.index(_clave(r.tipo)) if _clave(r.tipo) in ROLES_OFICIALES else len(ROLES_OFICIALES),
        _clave(r.tipo)))
    for posicion, rol in enumerate(roles, start=1):
        rol.orden = posicion
        rol.save(update_fields=['orden'])


class Migration(migrations.Migration):

    dependencies = [
        ('nomencladores', '0014_nomencladores_orden_y_proteccion'),
    ]

    operations = [
        migrations.RunPython(ordenar, migrations.RunPython.noop),
    ]
