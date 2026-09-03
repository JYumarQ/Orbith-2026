"""Alcance del Gestor de Plantilla.

`unidades_visibles()` es el **único punto** donde se decide qué Unidades
Organizativas puede consultar cada usuario en este módulo, mismo patrón que
`cierres/filtros.py::unidades_visibles()` y `dashboard/filtros.py`.

El reparto es el mismo que en el Dashboard y en el listado de Contratos: el
Administrador y el **Observador** ven toda la empresa; el Moderador, solo su
parcela.

Antes esta decisión estaba escrita a mano en cada vista como
`if request.user.is_superuser: todas else: request.user.unidades`. Esa condición
dejaba fuera al Observador —que no es superusuario— y le mostraba el Gestor de
Plantilla vacío, aunque su rol es precisamente el de consultar toda la empresa.

QUÉ CUENTA COMO «SU PARCELA» PARA UN MODERADOR
----------------------------------------------
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

from .models import UnidadOrganizativa


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def ve_toda_la_empresa(usuario):
    """Administrador u Observador: sin restricción de Unidad Organizativa."""
    return es_administrador(usuario) or bool(getattr(usuario, 'es_observador', False))


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
