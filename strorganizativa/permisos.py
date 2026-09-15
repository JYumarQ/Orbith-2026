"""Alcance del Gestor de Plantilla.

`unidades_visibles()` es el **único punto** donde se decide qué Unidades
Organizativas puede consultar cada usuario en este módulo, mismo patrón que
`cierres/filtros.py::unidades_visibles()` y `dashboard/filtros.py`.

El reparto es el mismo que en el Dashboard y en el listado de Contratos, y lo
decide `usuarios.alcance`: el Administrador ve toda la empresa; el Moderador,
solo su parcela; y el **Observador** ve toda la empresa mientras no tenga
unidades asignadas — si el Administrador le asignó alguna, ve exactamente esa
parcela, con las mismas reglas que un Moderador.

Antes esta decisión estaba escrita a mano en cada vista como
`if request.user.is_superuser: todas else: request.user.unidades`. Esa condición
dejaba fuera al Observador —que no es superusuario— y le mostraba el Gestor de
Plantilla vacío, aunque su rol es precisamente el de consultar toda la empresa.

QUÉ CUENTA COMO «SU PARCELA»
----------------------------
Sus unidades asignadas (`CustomUser.unidades`) **y las subunidades que cuelgan
de ellas**. Esto no amplía lo que ya veía: es exactamente lo que el Gestor le
pinta hoy. `gestor_plantilla_view` lista arriba solo las unidades raíz y cuelga
las hijas de cada una en un desplegable, y ese desplegable nunca estuvo acotado
por rol. Si aquí se contaran únicamente las asignadas, al Moderador se le
seguirían pintando subunidades en las que ya no podría entrar: la pantalla
mostraría filas muertas.

La jerarquía tiene exactamente dos niveles, no una profundidad cualquiera: el
modelo obliga a que el padre de una subunidad sea una Unidad Principal y a que
una principal no tenga padre (ver `UnidadOrganizativa.clean()`). Por eso basta
mirar un salto de `padre` y no hace falta recorrer el árbol.

Ojo con la asimetría, que es deliberada: CONSULTAR una subunidad no implica
poder ACTUAR sobre ella. Declarar un cierre sigue exigiendo tenerla asignada de
forma explícita (`cierres.permisos.puede_declarar`), y toda escritura de este
módulo pasa por `usuarios.mixins.RequiereEdicionMixin`. Este fichero decide QUÉ
SE VE, nunca QUÉ SE PUEDE TOCAR.
"""

from django.db.models import Q

from usuarios.alcance import es_administrador, ve_toda_la_empresa  # noqa: F401

from .models import UnidadOrganizativa

# `es_administrador` y `ve_toda_la_empresa` se reexportan a propósito: vivían
# aquí y las importan las vistas y las pruebas de este módulo. Ahora la regla es
# única y vive en `usuarios.alcance`; este módulo solo la aplica.


def unidades_visibles(usuario):
    """Unidades Organizativas que este usuario puede consultar en el Gestor.

    Devuelve siempre un queryset (nunca una lista), para que quien llame pueda
    seguir encadenando filtros o usarlo como subconsulta en un `__in`.
    """
    if ve_toda_la_empresa(usuario):
        return UnidadOrganizativa.objects.all()

    if not getattr(usuario, 'is_authenticated', False):
        return UnidadOrganizativa.objects.none()

    asignadas = usuario.unidades.values_list('pk', flat=True)
    return UnidadOrganizativa.objects.filter(
        Q(pk__in=asignadas) | Q(padre_id__in=asignadas))


def departamentos_visibles(usuario):
    """Departamentos que cuelgan de las unidades visibles para `usuario`."""
    from .models import Departamento

    return Departamento.objects.filter(
        unidad_organizativa__in=unidades_visibles(usuario))


def cargos_visibles(usuario):
    """Cargos de plantilla que cuelgan de los departamentos visibles."""
    from .models import CargoPlantilla

    return CargoPlantilla.objects.filter(
        departamento__unidad_organizativa__in=unidades_visibles(usuario))
