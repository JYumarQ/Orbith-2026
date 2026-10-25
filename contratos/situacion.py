"""La «situación» de un trabajador en el histórico (25-10-2026): unidad,
departamento, cargo y salario.

Cada cambio externo guarda cómo quedó el contrato después (`CambioExterno.situacion`)
y el histórico la enseña debajo del cambio con la etiqueta «Actualizado por cambio
externo». Si se ocultan los cambios externos, el último movimiento antes de ellos
enseña directamente la situación final.

* `situacion_de_contrato(contrato)` lee la situación vigente del contrato. Es la que
  usa `registrar_cambio()`, que se llama DESPUÉS de guardar el cambio.
* `aplicar_cambio(situacion, cambio)` deduce la situación tras un cambio a partir de
  la anterior y de lo que el propio cambio anota. Solo se usa para los cambios
  externos anteriores a este campo (la migración 0029 los rellena).
"""

import re

CLAVES = ('unidad', 'departamento', 'cargo', 'salario')
SIN_DATO = '---'


def _texto(valor):
    return (str(valor).strip() if valor is not None else '') or SIN_DATO


def _salario(valor):
    try:
        return '%.2f' % float(valor)
    except (TypeError, ValueError):
        return SIN_DATO


def situacion_de_contrato(contrato):
    """Situación vigente de un `CAlta` (con `cargo__ncargo` y
    `cargo__departamento__unidad_organizativa` ya cargados, si se puede)."""
    cargo = getattr(contrato, 'cargo', None)
    departamento = getattr(cargo, 'departamento', None) if cargo else None
    unidad = getattr(departamento, 'unidad_organizativa', None) if departamento else None
    return {
        'unidad': _texto(getattr(unidad, 'descripcion', None)),
        'departamento': _texto(getattr(departamento, 'descripcion', None)),
        'cargo': _texto(getattr(getattr(cargo, 'ncargo', None), 'descripcion', None)),
        'salario': _salario(getattr(contrato, 'salario_actual', None)),
    }


def situaciones_de_contratos(pks):
    """`{pk: situación}` leído de la base en una sola consulta."""
    from .models import CAlta

    contratos = (CAlta.objects.filter(pk__in=pks)
                 .select_related('cargo__ncargo', 'cargo__departamento__unidad_organizativa'))
    return {c.pk: situacion_de_contrato(c) for c in contratos}


# Textos que escriben `strorganizativa`, `nomencladores` y `cambios_externos`.
_NOMENCLADOR = re.compile(r'cambió de nomenclador: .+? \(grupo [^)]*\) a (?P<cargo>.+?) \(grupo [^)]*\)')
_DE_DEPARTAMENTO = re.compile(
    r'pasó del departamento .+? \(.+?\) al departamento (?P<departamento>.+?) \((?P<unidad>.+?)\)')
_RENOMBRE_CARGO = re.compile(r'pasó a llamarse «(?P<cargo>.+?)»')
_SALARIO = re.compile(r'Salario\s+(?P<valor>-?[\d.,]+)')


def aplicar_cambio(situacion, origen, descripcion, valor_nuevo):
    """Situación tras un cambio externo, deducida de la anterior y del cambio."""
    nueva = dict(situacion)
    descripcion = descripcion or ''
    valor_nuevo = (valor_nuevo or '').strip()
    if origen == 'UNI' and valor_nuevo:
        nueva['unidad'] = valor_nuevo
    elif origen == 'DEP' and valor_nuevo:
        if 'pasó de la unidad' in descripcion:
            nueva['unidad'] = valor_nuevo
        else:
            nueva['departamento'] = valor_nuevo
    elif origen == 'CAR':
        encontrado = _NOMENCLADOR.search(descripcion)
        if encontrado:
            nueva['cargo'] = encontrado.group('cargo')
        encontrado = _DE_DEPARTAMENTO.search(descripcion)
        if encontrado:
            nueva['departamento'] = encontrado.group('departamento')
            nueva['unidad'] = encontrado.group('unidad')
    elif origen == 'NCA':
        encontrado = _RENOMBRE_CARGO.search(descripcion)
        if encontrado:
            nueva['cargo'] = encontrado.group('cargo')
    if origen in ('CAR', 'NCA', 'ESC'):
        encontrado = _SALARIO.search(valor_nuevo)
        if encontrado:
            nueva['salario'] = _salario(encontrado.group('valor').replace(',', '.'))
    return nueva
