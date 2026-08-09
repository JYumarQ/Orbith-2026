"""Vistas de solo lectura del listado de Auditoría. Todo el módulo es exclusivo del
Administrador: `admin_required` en cada vista, igual que el resto de la sección
Administración."""

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from usuarios.decorators import admin_required

from .filtros import filtrar_eventos
from .models import EventoAuditoria

POR_PAGINA_POR_DEFECTO = 25


def _por_pagina(request):
    try:
        valor = int(request.GET.get('per_page', POR_PAGINA_POR_DEFECTO))
    except (TypeError, ValueError):
        return POR_PAGINA_POR_DEFECTO
    return valor if valor in (10, 25, 50) else POR_PAGINA_POR_DEFECTO


def _paginar(request, consulta):
    paginador = Paginator(consulta, _por_pagina(request))
    return paginador.get_page(request.GET.get('page'))


@admin_required
def index(request):
    consulta, contexto = filtrar_eventos(request)
    pagina = _paginar(request, consulta)
    contexto.update({
        'eventos': pagina,
        'page_obj': pagina,
        'current_page_size': str(_por_pagina(request)),
    })
    return render(request, 'pages/auditoria/list_auditoria.html', contexto)


@admin_required
def buscar_eventos(request):
    """Cuerpo de la tabla para las peticiones HTMX de búsqueda, filtro y paginación."""
    consulta, contexto = filtrar_eventos(request)
    pagina = _paginar(request, consulta)
    contexto.update({'eventos': pagina, 'page_obj': pagina})
    return render(
        request, 'pages/auditoria/partials/filter_auditoria_list.html', contexto)


@admin_required
def detalle_evento(request, pk):
    """Fragmento HTMX para el modal de detalle, con la comparación antes/después.

    Los datos ya están congelados y serializados (ver `solicitudes/serializacion.py`),
    así que la comparación es una lista simple campo/antes/después: no hace falta
    reconstruir ningún ModelForm, a diferencia de la pantalla de revisión de
    Solicitudes, donde la propuesta todavía es editable.
    """
    evento = get_object_or_404(
        EventoAuditoria.objects.select_related(
            'usuario', 'unidad', 'content_type', 'solicitud'),
        pk=pk)
    claves = sorted(set(evento.datos_antes) | set(evento.datos_despues))
    filas = [{
        'campo': clave,
        'antes': evento.datos_antes.get(clave, '—'),
        'despues': evento.datos_despues.get(clave, '—'),
        'cambio': evento.datos_antes.get(clave) != evento.datos_despues.get(clave),
    } for clave in claves]
    return render(request, 'pages/auditoria/partials/detalle_evento.html',
                  {'evento': evento, 'filas': filas})
