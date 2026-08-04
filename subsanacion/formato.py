"""Ayudas para redactar los títulos de los hallazgos.

Estas funciones existen por un motivo concreto de diseño: el listado de hallazgos NO
resuelve la GenericForeignKey (por eso no dispara consultas por fila y sobrevive a que
el registro apuntado se borre). En consecuencia **la búsqueda no puede hacer JOIN al
registro original**, y la única forma de que un hallazgo se pueda encontrar por el
nombre de la persona o por su carnet es que la propia regla los escriba en el título.

Un título como «Contrato sin cargo» es imposible de encontrar buscando. El correcto es
«Pérez Gómez, Juan (85010112345) · Contrato 00158».
"""


def nombre_completo(nombre, papellido, sapellido=''):
    """«Pérez Gómez, Juan» — apellidos primero, que es como se busca a la gente."""
    apellidos = ' '.join(parte for parte in (papellido, sapellido) if parte)
    nombre = (nombre or '').strip()
    apellidos = apellidos.strip()
    if apellidos and nombre:
        return f'{apellidos}, {nombre}'
    return apellidos or nombre or 'Sin nombre'


def referencia_trabajador(nombre, papellido, sapellido='', doc_identidad=''):
    """«Pérez Gómez, Juan (85010112345)»."""
    base = nombre_completo(nombre, papellido, sapellido)
    if doc_identidad:
        return f'{base} ({doc_identidad})'
    return base


def referencia_contrato(nombre, papellido, sapellido='', doc_identidad='', no_expediente=''):
    """«Pérez Gómez, Juan (85010112345) · Expediente 00158»."""
    base = referencia_trabajador(nombre, papellido, sapellido, doc_identidad)
    if no_expediente:
        return f'{base} · Expediente {no_expediente}'
    return base
