"""Alcance y validación del filtro global del Dashboard (Unidad Organizativa).

`unidades_visibles()` es el único punto donde se decide qué Unidades
Organizativas puede ver cada usuario, mismo patrón que
`cierres/filtros.py::unidades_visibles()`. Un Administrador y un Observador ven
todas las UO; un Moderador solo las que tiene asignadas en
`CustomUser.unidades`.

`resolver_filtros()` es el único punto que valida lo que llega por querystring:
nunca confía en los ids que pida el cliente, siempre los intersecta contra el
alcance real del usuario. Esto es lo que impide que un Moderador vea datos
ajenos aunque edite la URL a mano.

No existe selección manual de Departamento: seleccionar una UO selecciona
automáticamente todos sus Departamentos. `_filtrar_por_uo()` es el único punto
de filtrado por alcance, reutilizado por todos los componentes del Dashboard
(activos, altas, bajas, pirámide, plazas, recordatorios, advertencias, etc.).
"""

from strorganizativa.jerarquia import expandir, ordenar_con_jerarquia
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
    """Lee `?uo=` de la querystring y lo valida contra el alcance real del
    usuario. Devuelve `(uo_ids, contexto)`.

    Reglas:
    - Los ids de UO pedidos se intersectan contra `unidades_visibles()`. Un
      Moderador que pida (por URL o manipulando el `<select>`) una UO que no
      tiene asignada, simplemente no la obtiene: no hay error, no hay aviso,
      el resultado es idéntico a no haberla pedido.
    - Si el usuario es Moderador y, tras la intersección, no queda ninguna UO
      seleccionada (no pidió ninguna, o solo pidió ids ajenos/inválidos), el
      alcance por defecto es TODAS sus UO asignadas — nunca el universo
      completo ni un conjunto vacío.
    - `uo_count`/`depto_count` reflejan el alcance EFECTIVO (con o sin
      selección explícita): sin selección, la cantidad total permitida para el
      usuario; con selección, la cantidad de UO elegidas y la de Departamentos
      que cuelgan de ellas.
    """
    usuario = request.user
    unidades_qs = unidades_visibles(usuario)
    unidades_ids_visibles = set(unidades_qs.values_list('pk', flat=True))

    uo_pedidos = request.GET.getlist('uo')
    # Elegir una Unidad Principal significa también sus subunidades. Antes se
    # comparaba el id exacto, y como una principal no tiene cargos propios —todo
    # cuelga de sus hijas—, filtrar por ella dejaba el Dashboard entero en cero.
    # La expansión se hace ANTES de cruzar con el alcance, para que un Moderador
    # no reciba subunidades que no le corresponden.
    uo_ids = set(expandir([v for v in uo_pedidos if v.isdigit()]))
    uo_ids &= unidades_ids_visibles

    es_moderador_puro = (
        not es_administrador(usuario)
        and not getattr(usuario, 'es_observador', False)
        and getattr(usuario, 'es_moderador', False)
    )
    if not uo_ids and es_moderador_puro:
        uo_ids = set(unidades_ids_visibles)

    uo_ids_efectivas = uo_ids if uo_ids else unidades_ids_visibles
    depto_count = Departamento.objects.filter(
        unidad_organizativa_id__in=uo_ids_efectivas
    ).count()

    contexto = {
        # Ordenadas padre → hijas y con `nivel`, para que el desplegable pueda
        # indentar las subunidades en vez de listarlas como si fueran hermanas.
        'filtro_uo_opciones': ordenar_con_jerarquia(unidades_qs.select_related('padre')),
        'filtro_uo_seleccionadas': uo_ids,
        # Los MISMOS ids en texto: la plantilla los compara con `in` contra el
        # `pk|stringformat:"s"` de cada opción, y ahí 5 y '5' no son lo mismo.
        # Solo se marcan los que el usuario pidió de verdad, no los que se
        # añadieron al expandir: si no, elegir una principal dejaría marcadas
        # también todas sus hijas y no habría forma de distinguir una cosa de
        # la otra al volver a abrir el desplegable.
        'filtro_uo_seleccionadas_txt': [
            v for v in uo_pedidos if v.isdigit() and int(v) in unidades_ids_visibles],
        'uo_count': len(uo_ids_efectivas),
        'depto_count': depto_count,
    }
    return uo_ids, contexto


def _filtrar_por_uo(qs, campo_departamento, uo_ids):
    """`campo_departamento` es la ruta ORM hasta Departamento (p.ej.
    'cargo__departamento') a partir de la cual se cuelga
    `__unidad_organizativa_id`. Único punto de filtrado por alcance,
    reutilizado por todos los componentes del Dashboard."""
    if uo_ids:
        return qs.filter(**{f"{campo_departamento}__unidad_organizativa_id__in": uo_ids})
    return qs
