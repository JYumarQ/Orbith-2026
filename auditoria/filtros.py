"""Filtros del listado de Auditoría.

Espejo de `solicitudes/filtros.py`: mismo helper para parámetros repetidos en la URL,
mismo criterio de descartar en silencio los valores no reconocidos. A diferencia de
Solicitudes no hay pestañas (no hay estados que agrupar). Desde que existe el
registro automático (`registro_automatico.py`) los eventos vienen de varios módulos,
así que se puede filtrar por `modulo`.
"""

from django.db.models import Q

from .models import AccionAuditoria, EventoAuditoria
from .registro_automatico import NOMBRES_DE_MODULO


def _lista_de(request, parametro, validos=None, convertir=None):
    """Lee un parámetro repetido de la URL y descarta los valores no reconocidos."""
    valores = []
    for crudo in request.GET.getlist(parametro):
        crudo = (crudo or '').strip()
        if not crudo:
            continue
        if convertir is not None:
            try:
                crudo = convertir(crudo)
            except (TypeError, ValueError):
                continue
        if validos is not None and crudo not in validos:
            continue
        valores.append(crudo)
    return valores


def eventos_visibles():
    """Solo Administrador accede a este módulo (ver `auditoria/urls.py`), así que no
    hay alcance por usuario que resolver aquí, a diferencia de Solicitudes."""
    return EventoAuditoria.objects.select_related(
        'usuario', 'unidad', 'content_type', 'solicitud')


def nombre_de_modulo(clave):
    return NOMBRES_DE_MODULO.get(clave) or (clave[:1].upper() + clave[1:])


def opciones_de_filtro():
    """Opciones de los desplegables, derivadas de los eventos que existen de verdad."""
    base = eventos_visibles()
    from strorganizativa.models import UnidadOrganizativa
    from usuarios.models import CustomUser

    usuarios_presentes = base.exclude(usuario__isnull=True).values_list(
        'usuario', flat=True).distinct()
    unidades_presentes = base.exclude(unidad__isnull=True).values_list(
        'unidad', flat=True).distinct()

    modulos_presentes = (base.exclude(modulo='').order_by()
                         .values_list('modulo', flat=True).distinct())
    return {
        'modulos': sorted(
            ((clave, nombre_de_modulo(clave)) for clave in modulos_presentes),
            key=lambda par: par[1]),
        'usuarios': [
            (persona.pk, persona.get_full_name() or persona.username) for persona in
            CustomUser.objects.filter(pk__in=usuarios_presentes).order_by('username')
        ],
        'acciones': AccionAuditoria.choices,
        'unidades': [
            (unidad.pk, unidad.descripcion) for unidad in
            UnidadOrganizativa.objects.filter(pk__in=unidades_presentes).order_by('descripcion')
        ],
    }


def filtrar_eventos(request):
    """Devuelve `(queryset, contexto_de_filtros)` según los filtros de la URL."""
    busqueda = (request.GET.get('q') or '').strip()
    usuarios = _lista_de(request, 'usuario', convertir=int)
    acciones = _lista_de(request, 'accion', validos=AccionAuditoria.values)
    unidades = _lista_de(request, 'unidad', convertir=int)
    modulos = _lista_de(request, 'modulo')
    desde = (request.GET.get('desde') or '').strip()
    hasta = (request.GET.get('hasta') or '').strip()

    consulta = eventos_visibles()

    if busqueda:
        # `descriptor` y `usuario_nombre` están congelados justo para que esto
        # funcione incluso cuando el registro afectado o el usuario ya no existan.
        consulta = consulta.filter(
            Q(descriptor__icontains=busqueda) | Q(usuario_nombre__icontains=busqueda))
    if usuarios:
        consulta = consulta.filter(usuario_id__in=usuarios)
    if acciones:
        consulta = consulta.filter(accion__in=acciones)
    if unidades:
        consulta = consulta.filter(unidad_id__in=unidades)
    if modulos:
        consulta = consulta.filter(modulo__in=modulos)
    if desde:
        try:
            consulta = consulta.filter(fecha__date__gte=desde)
        except (ValueError, TypeError):
            desde = ''
    if hasta:
        try:
            consulta = consulta.filter(fecha__date__lte=hasta)
        except (ValueError, TypeError):
            hasta = ''

    contexto = {
        'q': busqueda,
        'usuarios_actuales': usuarios,
        'acciones_actuales': acciones,
        'unidades_actuales': unidades,
        'modulos_actuales': modulos,
        'desde': desde,
        'hasta': hasta,
        'opciones_filtro': opciones_de_filtro(),
        'hay_filtros': bool(busqueda or usuarios or acciones or unidades or modulos
                            or desde or hasta),
    }
    return consulta, contexto
