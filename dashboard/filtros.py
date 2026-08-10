"""Alcance y validación de los filtros globales del Dashboard (UO / Departamento).

`unidades_visibles()` es el único punto donde se decide qué Unidades
Organizativas puede ver cada usuario, mismo patrón que
`cierres/filtros.py::unidades_visibles()`. Un Administrador y un Observador ven
todas las UO; un Moderador solo las que tiene asignadas en
`CustomUser.unidades`.

`resolver_filtros()` es el único punto que valida lo que llega por querystring:
nunca confía en los ids que pida el cliente, siempre los intersecta contra el
alcance real del usuario. Esto es lo que impide que un Moderador vea datos
ajenos aunque edite la URL a mano.
"""

from strorganizativa.models import Departamento, UnidadOrganizativa


def es_administrador(usuario):
    if not getattr(usuario, 'is_authenticated', False):
        return False
    return bool(usuario.is_superuser or getattr(usuario, 'es_admin', False))


def unidades_visibles(usuario):
    """Unidades Organizativas que el usuario puede ver/filtrar en el Dashboard."""
    if es_administrador(usuario) or getattr(usuario, 'es_observador', False):
        return UnidadOrganizativa.objects.all()
    if getattr(usuario, 'es_moderador', False):
        return usuario.unidades.all()
    return UnidadOrganizativa.objects.none()


def departamentos_visibles(usuario, unidades_qs=None):
    """Departamentos que cuelgan de las UO visibles para el usuario.

    Si se pasa `unidades_qs` (p.ej. las UO ya seleccionadas por el filtro), se
    acota a esas — siempre que a su vez estén dentro del alcance del usuario.
    """
    base_uo = unidades_visibles(usuario)
    if unidades_qs is not None:
        base_uo = base_uo.filter(pk__in=unidades_qs.values_list('pk', flat=True))
    return Departamento.objects.filter(
        unidad_organizativa_id__in=base_uo.values_list('pk', flat=True)
    ).select_related('unidad_organizativa')


def resolver_filtros(request):
    """Lee `?uo=` y `?depto=` de la querystring y los valida contra el alcance
    real del usuario. Devuelve `(uo_ids, depto_ids, contexto)`.

    Reglas:
    - Los ids de UO pedidos se intersectan contra `unidades_visibles()`. Un
      Moderador que pida (por URL o manipulando el `<select>`) una UO que no
      tiene asignada, simplemente no la obtiene: no hay error, no hay aviso,
      el resultado es idéntico a no haberla pedido.
    - Si el usuario es Moderador y, tras la intersección, no queda ninguna UO
      seleccionada (no pidió ninguna, o solo pidió ids ajenos/inválidos), el
      alcance por defecto es TODAS sus UO asignadas — nunca el universo
      completo ni un conjunto vacío.
    - Los ids de Departamento se validan en un segundo paso, ya acotados por
      las UO resultantes del paso anterior: un Departamento que no cuelgue de
      ninguna UO visible/seleccionada queda descartado igual que una UO ajena.
    """
    usuario = request.user
    unidades_qs = unidades_visibles(usuario)
    unidades_ids_visibles = set(unidades_qs.values_list('pk', flat=True))

    uo_pedidos = request.GET.getlist('uo')
    uo_ids = {int(v) for v in uo_pedidos if v.isdigit()}
    uo_ids &= unidades_ids_visibles

    es_moderador_puro = (
        not es_administrador(usuario)
        and not getattr(usuario, 'es_observador', False)
        and getattr(usuario, 'es_moderador', False)
    )
    if not uo_ids and es_moderador_puro:
        uo_ids = set(unidades_ids_visibles)

    if uo_ids:
        uo_ids_para_deptos = uo_ids
    else:
        uo_ids_para_deptos = unidades_ids_visibles

    deptos_validos_qs = Departamento.objects.filter(
        unidad_organizativa_id__in=uo_ids_para_deptos
    ).select_related('unidad_organizativa')
    deptos_ids_validos = set(deptos_validos_qs.values_list('pk', flat=True))

    depto_pedidos = request.GET.getlist('depto')
    depto_ids = {int(v) for v in depto_pedidos if v.isdigit()}
    depto_ids &= deptos_ids_validos

    contexto = {
        'filtro_uo_opciones': unidades_qs.order_by('descripcion'),
        'filtro_uo_seleccionadas': uo_ids,
        'filtro_depto_opciones': deptos_validos_qs.order_by('descripcion'),
        'filtro_depto_seleccionadas': depto_ids,
    }
    return uo_ids, depto_ids, contexto
