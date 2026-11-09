"""Regla ÚNICA de alcance por Unidad Organizativa.

Responde a una sola pregunta: **¿este usuario ve toda la empresa, o solo unas
Unidades Organizativas concretas?** Vive aquí y no repetida en cada módulo
porque hasta ahora la respuesta estaba escrita a mano en seis sitios
(`dashboard/filtros.py`, `informes/fuentes.py`, `informe_inteligente/motor.py`,
`strorganizativa/permisos.py`, `contratos/filtros.py`, `informes_anexo/views.py`)
y cambiarla obligaba a acertar en los seis a la vez.

EL REPARTO
----------
* **Administrador**: toda la empresa, siempre. Su alcance es su rol, no una
  relación en la base de datos.
* **Observador con «Todas las unidades»** (3.9.0): toda la empresa, también las
  unidades que se creen después.
* **Observador con unidades concretas**: solo esas unidades.
* **Observador sin nada** (3.9.0, decisión de RRHH del 09-11-2026): no ve nada.
  Antes veía toda la empresa; la migración `usuarios.0012` marcó «Todas» a los que
  no tenían unidades, así que nadie perdió lo que veía.
* **Moderador**: solo sus unidades asignadas, tenga las que tenga. Un moderador
  sin ninguna no ve nada — nunca la empresa entera.
* **Sin rol reconocido**: no ve nada.

POR QUÉ «SIN UNIDADES = TODA LA EMPRESA» SOLO VALE PARA EL OBSERVADOR
--------------------------------------------------------------------
Porque para el Moderador la lista vacía ya significaba «nada» en todo el
proyecto, y cambiarlo abriría de golpe la empresa entera a cualquier moderador
recién creado. Para el Observador, en cambio, la lista vacía nunca significó
nada: hasta hoy sus unidades no se consultaban en ninguna decisión de alcance.

LO QUE ESTE MÓDULO NO DECIDE
----------------------------
Qué se puede TOCAR. Toda escritura sigue pasando por
`usuarios.mixins.RequiereEdicionMixin` / `usuarios.decorators.write_required`,
que niegan al Observador con independencia de cuántas unidades tenga. Esto es
visibilidad, no permisos de edición.
"""


def es_administrador(usuario):
    """Administrador de la aplicación (o superusuario de Django)."""
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def es_observador(usuario):
    """Observador «puro»: excluye al Administrador.

    `CustomUser.save()` fuerza `is_superuser=True` en los administradores, así
    que sin esta exclusión un admin podría contar como dos roles a la vez
    (mismo detalle ya documentado en `cierres/permisos.py`).
    """
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_observador', False)) and not es_administrador(usuario)


def es_moderador(usuario):
    """Moderador «puro»: excluye al Administrador, por el mismo motivo."""
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(getattr(usuario, 'es_moderador', False)) and not es_administrador(usuario)


def _sin_unidades(usuario):
    """¿Este usuario no tiene ninguna unidad asignada?

    El resultado se guarda en el propio objeto de usuario porque durante una
    misma petición esta pregunta se hace varias veces (el Dashboard llama a
    `unidades_visibles()` una vez por componente) y no hace falta ir a la base
    de datos en cada una. `request.user` vive solo lo que dura la petición, así
    que la caché no puede quedarse obsoleta entre peticiones.
    """
    guardado = getattr(usuario, '_orbith_sin_unidades', None)
    if guardado is None:
        guardado = not usuario.unidades.exists()
        usuario._orbith_sin_unidades = guardado
    return guardado


def es_observador_global(usuario):
    """Observador con «Todas las unidades»: el que ve la empresa entera (3.9.0)."""
    return es_observador(usuario) and bool(getattr(usuario, 'todas_las_unidades', False))


def es_observador_acotado(usuario):
    """Observador sin «Todas»: solo ve sus unidades (ninguna, si no tiene)."""
    return es_observador(usuario) and not es_observador_global(usuario)


def ve_toda_la_empresa(usuario):
    """La pregunta que hacen los seis módulos: ¿sin restricción de unidad?"""
    return es_administrador(usuario) or es_observador_global(usuario)


def tiene_alcance_acotado(usuario):
    """¿Su visibilidad se limita a `CustomUser.unidades`?

    Cierto para el Moderador (siempre) y para el Observador acotado. Los dos se
    filtran exactamente igual, así que los módulos pueden tratarlos con una
    sola rama en vez de duplicarla.
    """
    return es_moderador(usuario) or es_observador_acotado(usuario)
