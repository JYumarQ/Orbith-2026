from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from usuarios.decorators import admin_required

from . import estadisticas
from .servicios import datos_ventana


@login_required
@never_cache
def panel_ranking(request):
    """Contenido de la ventana "Ranking Mensual Orbith", cargado al abrirla
    (como la Guía): no se calcula en cada página. `never_cache` por lo mismo
    que en `progreso.views.panel_guia`: es contenido de cada usuario."""
    return render(request, 'pages/ranking/partials/panel_ranking.html',
                  {'datos': datos_ventana(request.user)})


# ----------------------------------------------------------------------
# "Estadísticas de uso" (Administración)
# ----------------------------------------------------------------------


@admin_required
@never_cache
def estadisticas_uso(request):
    """Página del Administrador: ranking (XP) y uso de cada rol en un mes."""
    mes = estadisticas.mes_elegido(request.GET.get('mes'))
    contexto = estadisticas.datos_pagina(mes['anno'], mes['mes'])
    contexto.update({'mes': mes, 'meses': estadisticas.meses_disponibles()})
    return render(request, 'pages/ranking/estadisticas_uso.html', contexto)


@admin_required
@never_cache
def detalle_usuario(request, pk):
    """Contenido del panel lateral de un usuario (lo pide la página con HTMX)."""
    usuario = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    mes = estadisticas.mes_elegido(request.GET.get('mes'))
    return render(request, 'pages/ranking/partials/detalle_usuario.html',
                  {'d': estadisticas.detalle_usuario(usuario, mes['anno'], mes['mes'])})


@admin_required
@require_POST
def recordar_cierre(request, unidad_id):
    """"Enviar recordatorio" a una unidad que sigue sin declarar el cierre del
    mes elegido. Reutiliza el aviso de Cierres ("Unidad desactualizada"): le
    llega a su moderador y a los administradores."""
    from cierres.avisos import CODIGO_DESACTUALIZADA, avisar_desactualizada
    from cierres.models import CierreUnidad
    from cierres.periodos import Periodo
    from notificaciones.models import Notificacion
    from strorganizativa.models import UnidadOrganizativa

    mes = estadisticas.mes_elegido(request.POST.get('mes'))
    volver = f"{reverse('ranking_estadisticas')}?mes={mes['clave']}"
    unidad = get_object_or_404(UnidadOrganizativa, pk=unidad_id)
    if CierreUnidad.objects.filter(unidad=unidad, anno=mes['anno'], mes=mes['mes']).exists():
        messages.info(request, f'«{unidad.descripcion}» ya declaró el cierre de {mes["etiqueta"]}.')
        return redirect(volver)

    periodo = Periodo(mes['anno'], mes['mes'])
    estado = getattr(unidad, 'estado_cierre', None)
    enviados = avisar_desactualizada(unidad, periodo, getattr(estado, 'meses_pendientes', 1) or 1)
    if not enviados:
        messages.warning(request, f'«{unidad.descripcion}» no tiene a nadie a quien avisar.')
        return redirect(volver)
    # El aviso de Cierres se actualiza en vez de duplicarse: se vuelve a marcar
    # como no leído para que reaparezca en la campana de quien ya lo había visto.
    Notificacion.objects.filter(content_type=ContentType.objects.get_for_model(UnidadOrganizativa),
                                object_id=str(unidad.pk), codigo_regla=CODIGO_DESACTUALIZADA,
                                clave_extra=periodo.clave).update(leido=False)
    messages.success(request, f'Recordatorio enviado a «{unidad.descripcion}» ({enviados} persona(s)).')
    return redirect(volver)
