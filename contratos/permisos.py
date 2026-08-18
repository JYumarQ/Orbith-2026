"""Control de alcance del módulo de Contratos.

Mismo reparto que `cierres/permisos.py` y `subsanacion/permisos.py`: el
Administrador ve toda la empresa; el Moderador solo los contratos de las
Unidades Organizativas que tiene asignadas en `CustomUser.unidades`. A
diferencia de Subsanación, aquí el Observador se trata como el Dashboard
general: ve todo igual que el Administrador, porque el listado de Contratos
es informativo (no expone acciones de edición) y así lo pidió RRHH.

`CustomUser.save()` fuerza `is_superuser=True`/`es_admin` en los
administradores, así que `es_moderador()` los excluye explícitamente para que
un admin no pase por los dos roles a la vez (mismo detalle documentado en
`cierres/permisos.py`).
"""


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def es_moderador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)
