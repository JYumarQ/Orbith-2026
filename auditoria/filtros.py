"""Filtros del listado de Auditoría.

Espejo de `solicitudes/filtros.py`: mismo helper para parámetros repetidos en la URL,
mismo criterio de descartar en silencio los valores no reconocidos. A diferencia de
Solicitudes no hay pestañas (no hay estados que agrupar) ni filtro de módulo/tipo de
registro todavía: en esta entrega todo evento es `modulo='solicitudes'`.
"""

from django.db.models import Q

from .models import AccionAuditoria, EventoAuditoria


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


def opciones_de_filtro():
    """Opciones de los desplegables, derivadas de los eventos que existen de verdad."""
    base = eventos_visibles()
    from strorganizativa.models import UnidadOrganizativa
    from usuarios.models import CustomUser

    usuarios_presentes = base.exclude(usuario__isnull=True).values_list(
        'usuario', flat=True).distinct()
    unidades_presentes = base.exclude(unidad__isnull=True).values_list(
        'unidad', flat=True).distinct()

    return {
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
        'desde': desde,
        'hasta': hasta,
        'opciones_filtro': opciones_de_filtro(),
        'hay_filtros': bool(busqueda or usuarios or acciones or unidades or desde or hasta),
    }
    return consulta, contexto
