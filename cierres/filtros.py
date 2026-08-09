"""Alcance y filtros del listado de cierres.

`unidades_visibles()` es el **único punto** donde se decide qué unidades ve cada
usuario, igual que `solicitudes/filtros.py::solicitudes_visibles()`. Si mañana
cambia la regla de alcance, se cambia aquí y en ningún otro sitio.
"""

from django.db.models import Q

from strorganizativa.models import UnidadOrganizativa

from .models import CierreUnidad, EstadoUnidad
from .permisos import es_administrador, es_moderador

ESTADOS_VALIDOS = {e.value for e in EstadoUnidad}


def unidades_visibles(usuario):
    """Unidades que el usuario puede ver en el panel de cierres.

    `select_related('estado_cierre')` evita una consulta por fila al pintar el
    badge: sin él, un listado de 40 unidades lanzaba 40 consultas sueltas.
    """
    base = (UnidadOrganizativa.objects
            .select_related('tipo', 'padre', 'estado_cierre',
                            'estado_cierre__ultimo_cierre'))
    if es_administrador(usuario):
        return base
    if es_moderador(usuario):
        return base.filter(pk__in=usuario.unidades.values_list('pk', flat=True))
    return base.none()


def filtrar_unidades(request):
    """Devuelve `(queryset, contexto)`, mismo contrato que el resto del proyecto."""
    unidades = unidades_visibles(request.user)

    q = (request.GET.get('q') or '').strip()
    if q:
        unidades = unidades.filter(descripcion__icontains=q)

    estado = (request.GET.get('estado') or '').strip()
    if estado in ESTADOS_VALIDOS:
        unidades = unidades.filter(estado_cierre__estado=estado)
    elif estado == 'SIN':
        # Nunca declaró: no tiene fila de estado o no tiene primer cierre.
        unidades = unidades.filter(
            Q(estado_cierre__isnull=True) | Q(estado_cierre__primer_cierre__isnull=True))

    contexto = {
        'q': q,
        'estado_actual': estado,
        'opciones_estado': list(EstadoUnidad.choices),
        'hay_filtros': bool(q or estado),
    }
    return unidades.order_by('orden_informe', 'descripcion'), contexto


def historial_visible(usuario, unidad=None):
    """Cierres que el usuario puede consultar, del más reciente al más antiguo."""
    cierres = (CierreUnidad.objects
               .select_related('unidad', 'declarado_por')
               .order_by('-anno', '-mes'))
    if not es_administrador(usuario):
        if not es_moderador(usuario):
            return cierres.none()
        cierres = cierres.filter(unidad__in=usuario.unidades.values_list('pk', flat=True))
    if unidad is not None:
        cierres = cierres.filter(unidad=unidad)
    return cierres
