"""Vistas de solo lectura del listado de Auditoría. Todo el módulo es exclusivo del
Administrador: `admin_required` en cada vista, igual que el resto de la sección
Administración."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, render

from core.paginacion import paginar as _paginar
from usuarios.decorators import admin_required

from .filtros import filtrar_eventos, nombre_de_modulo
from .limpieza import borrar_auditoria_antigua
from .models import EventoAuditoria


@admin_required
def index(request):
    # Conservación configurada en Parámetros Generales: lo que supera el plazo se
    # borra aquí, sin tareas programadas. Con «Nunca» no hace nada.
    borrados = borrar_auditoria_antigua()
    if borrados:
        messages.info(request, 'Se eliminaron %d eventos de auditoría que superaban '
                               'el plazo de conservación.' % borrados)
    consulta, contexto = filtrar_eventos(request)
    pagina = _paginar(request, consulta)
    contexto.update({'eventos': pagina, 'page_obj': pagina})
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
                  {'evento': evento, 'filas': filas,
                   'modulo': nombre_de_modulo(evento.modulo) if evento.modulo else '—'})
