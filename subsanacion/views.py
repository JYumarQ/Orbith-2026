"""Vistas del Centro de Diagnóstico de Integridad de Datos.

Todas las vistas exigen `admin_required`. El barrido lee toda la empresa (ver el
docstring de `servicios`), así que no puede lanzarlo un moderador: si lo hiciera con
alcance parcial, la reconciliación daría por corregidos los hallazgos de las unidades
que no leyó.

`LoginRequiredMiddleware` ya está activo en todo el proyecto, así que
`@login_required` sería redundante; se mantiene `@admin_required` porque el permiso
tiene que leerse en el propio archivo.

Estilo: vistas basadas en función con fragmentos HTMX, igual que
`informe_inteligente` y `soporte`.
"""

import logging

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from usuarios.decorators import admin_required

from . import servicios
from .constantes import (
    CLAVES_MODULOS,
    COLOR_POR_CRITICIDAD,
    CRITICIDADES,
    DIAS_RESULTADO_ANTIGUO,
    ETIQUETA_MODULO,
    ICONO_POR_CRITICIDAD,
    MODULOS,
    color_de_indice,
)
from .contexto import ContextoAnalisis
from .enlaces import enlace_de_hallazgo
from .exportar import exportar_a_excel, exportar_a_pdf
from .filtros import (
    filtrar_hallazgos,
    querystring_completa,
    querystring_sin_pagina,
)
from .models import EjecucionAnalisis, Hallazgo
from .reglas import obtener_regla, total_reglas
from .servicios import AnalisisEnCurso

logger = logging.getLogger(__name__)

HALLAZGOS_POR_PAGINA = 25
REVISIONES_POR_PAGINA = 40

PLANTILLA_ERROR = 'pages/subsanacion/partials/error.html'


# ---------------------------------------------------------------------------
# Contextos compartidos
# ---------------------------------------------------------------------------

def _contexto_dashboard():
    """Todo lo que pinta el dashboard. Solo lecturas: NUNCA lanza un análisis."""
    ejecucion = servicios.ultima_ejecucion_terminada()
    por_criticidad = servicios.resumen_por_criticidad()

    tarjetas_criticidad = [{
        'valor': valor,
        'etiqueta': etiqueta,
        'total': por_criticidad.get(valor, 0),
        'color': COLOR_POR_CRITICIDAD.get(valor, 'gris'),
        'icono': ICONO_POR_CRITICIDAD.get(valor, 'bi-dash-circle'),
    } for valor, etiqueta in CRITICIDADES]

    antiguo = False
    if ejecucion is not None:
        antiguo = (timezone.now() - ejecucion.iniciada_en).days >= DIAS_RESULTADO_ANTIGUO

    return {
        'ejecucion': ejecucion,
        'color_indice': color_de_indice(ejecucion.indice_salud if ejecucion else None),
        'tarjetas_criticidad': tarjetas_criticidad,
        'modulos': servicios.resumen_por_modulo(ejecucion),
        'total_reglas': total_reglas(),
        'resultado_antiguo': antiguo,
        'dias_antiguo': DIAS_RESULTADO_ANTIGUO,
        'ejecucion_en_curso': servicios.obtener_ejecucion_en_curso(),
        'total_vigentes': Hallazgo.objects.filter(
            vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS).count(),
    }


def _contexto_listado(request):
    consulta, filtros = filtrar_hallazgos(request)
    paginador = Paginator(consulta, HALLAZGOS_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get('pagina'))

    return {
        'pagina': pagina,
        'hallazgos': pagina.object_list,
        'total_resultados': paginador.count,
        'filtros': filtros,
        'querystring': querystring_sin_pagina(request),
        'querystring_completa': querystring_completa(request),
        'criticidades': CRITICIDADES,
        'modulos_disponibles': MODULOS,
        'estados_disponibles': Hallazgo.ESTADOS,
        'color_por_criticidad': COLOR_POR_CRITICIDAD,
    }


def _error(request, mensaje, estado=400):
    """Fragmento de error en español, nunca un 500 opaco.

    Mismo patrón que `informe_inteligente`: el error viaja como partial con su código
    de estado, así el mismo swap de HTMX que iba a mostrar el resultado muestra el
    mensaje.
    """
    return render(request, PLANTILLA_ERROR, {'mensaje': mensaje}, status=estado)


# ---------------------------------------------------------------------------
# Pantalla principal y paneles
# ---------------------------------------------------------------------------

@admin_required
def index(request):
    """Página completa. El dashboard se pinta ya renderizado, sin una segunda petición."""
    contexto = _contexto_dashboard()
    contexto['claves_modulos'] = CLAVES_MODULOS
    return render(request, 'pages/subsanacion/index.html', contexto)


@admin_required
def panel_dashboard(request):
    return render(request, 'pages/subsanacion/partials/panel_dashboard.html',
                  _contexto_dashboard())


@admin_required
def panel_hallazgos(request):
    """Listado con filtros, búsqueda y paginación."""
    return render(request, 'pages/subsanacion/partials/panel_hallazgos.html',
                  _contexto_listado(request))


@admin_required
def panel_revisiones(request):
    """Historial de revisiones: quién revisó qué, cuándo y con qué observación.

    Es el historial propio del módulo, no la Auditoría del sistema. Aquí solo se
    registra lo que ocurre con los hallazgos; los cambios en datos de negocio no pasan
    por aquí, porque Subsanación no los hace.
    """
    consulta = servicios.historial_revisiones()
    paginador = Paginator(consulta, REVISIONES_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get('pagina'))

    return render(request, 'pages/subsanacion/partials/panel_revisiones.html', {
        'pagina': pagina,
        'revisiones': pagina.object_list,
        'total_resultados': paginador.count,
    })


@admin_required
def panel_estadisticas(request):
    """Distribución por categoría, gravedad y regla, más la tendencia del índice."""
    ejecucion = servicios.ultima_ejecucion_terminada()
    tendencia = servicios.tendencia_indice()

    return render(request, 'pages/subsanacion/partials/panel_estadisticas.html', {
        'ejecucion': ejecucion,
        'modulos': servicios.resumen_por_modulo(ejecucion),
        'por_regla': servicios.estadisticas_por_regla(),
        'por_estado': servicios.estadisticas_por_estado(),
        'tendencia': tendencia,
        # Con una sola medición no hay tendencia que dibujar; se dice en pantalla en
        # lugar de mostrar una gráfica de un punto.
        'hay_tendencia': len(tendencia) > 1,
        'color_por_criticidad': COLOR_POR_CRITICIDAD,
    })


# ---------------------------------------------------------------------------
# Exportaciones
# ---------------------------------------------------------------------------

@admin_required
def exportar_excel(request):
    """Excel de lo que hay en pantalla, con los mismos filtros y la misma búsqueda."""
    return exportar_a_excel(request)


@admin_required
def exportar_pdf(request):
    """PDF de lo que hay en pantalla, con los mismos filtros y la misma búsqueda."""
    return exportar_a_pdf(request)


@admin_required
def panel_analisis(request):
    """Panel de «Ejecutar nuevo análisis»: el botón, o el aviso de que ya hay uno."""
    return render(request, 'pages/subsanacion/partials/panel_analisis.html', {
        'ejecucion_en_curso': servicios.obtener_ejecucion_en_curso(),
        'ultima': servicios.ultima_ejecucion_terminada(),
        'modulos': MODULOS,
        'total_reglas': total_reglas(),
    })


@admin_required
def detalle_hallazgo(request, pk):
    """Detalle: qué encontró, por qué es un problema, cómo se corrige y a dónde ir."""
    hallazgo = get_object_or_404(
        Hallazgo.objects.select_related('content_type', 'revisado_por', 'ejecucion'), pk=pk)

    # La regla puede haber desaparecido del código (se retiró en una versión
    # posterior). El hallazgo histórico sigue siendo válido y se muestra sin la guía.
    regla = obtener_regla(hallazgo.codigo_regla)

    return render(request, 'pages/subsanacion/partials/detalle_hallazgo.html', {
        'hallazgo': hallazgo,
        'regla': regla,
        'enlace': enlace_de_hallazgo(
            hallazgo, forzar_url=regla.enlace_url if regla else None,
            # `detalle_hallazgo` se abre vía HTMX dentro de un modal sobre el panel de
            # hallazgos: `request.get_full_path()` sería la URL de este propio
            # fragmento, no la página real que ve el usuario (con sus filtros). HTMX
            # manda `HX-Current-URL` con la URL de la página en el navegador en el
            # momento de la petición — es la que hay que usar para volver ahí.
            next_url=request.headers.get('HX-Current-URL'), origen_label='Subsanación'),
        'revisiones': hallazgo.revisiones.select_related('usuario')[:20],
        'estados_disponibles': Hallazgo.ESTADOS,
        'color': COLOR_POR_CRITICIDAD.get(hallazgo.criticidad, 'gris'),
    })


# ---------------------------------------------------------------------------
# Cambio de estado: la única escritura que origina el usuario
# ---------------------------------------------------------------------------

@admin_required
@require_POST
def cambiar_estado(request, pk):
    """Marca un hallazgo como revisado, ignorado o falso positivo.

    Solo escribe en tablas de Subsanación. No existe —ni existirá— una vista que
    modifique un dato de negocio: la corrección la hace el usuario desde el
    formulario correspondiente.
    """
    hallazgo = get_object_or_404(Hallazgo.objects.select_related('content_type'), pk=pk)
    nuevo_estado = (request.POST.get('estado') or '').strip()
    nota = (request.POST.get('nota') or '').strip()

    if nuevo_estado not in dict(Hallazgo.ESTADOS):
        return _error(request, 'El estado indicado no es válido.')

    try:
        servicios.cambiar_estado_hallazgo(
            hallazgo, nuevo_estado, usuario=request.user, nota=nota)
    except ValueError as exc:
        return _error(request, str(exc))

    # Se devuelve el detalle recargado para que el usuario vea el estado nuevo y su
    # historial actualizado sin recargar la página entera.
    return detalle_hallazgo(request, pk)


# ---------------------------------------------------------------------------
# Cadena de análisis
# ---------------------------------------------------------------------------

def _siguiente_modulo(ejecucion, clave_actual):
    """La siguiente categoría pendiente, o None si ya se recorrieron todas."""
    solicitados = list(ejecucion.modulos_solicitados or CLAVES_MODULOS)
    try:
        posicion = solicitados.index(clave_actual)
    except ValueError:
        return None
    for clave in solicitados[posicion + 1:]:
        return clave
    return None


@admin_required
@require_POST
def iniciar_analisis(request):
    """Crea la ejecución y devuelve el primer paso de la cadena."""
    try:
        ejecucion = servicios.iniciar_ejecucion(
            usuario=request.user, origen=EjecucionAnalisis.MANUAL)
    except AnalisisEnCurso as exc:
        minutos = 0
        if exc.ejecucion is not None:
            minutos = int(
                (timezone.now() - exc.ejecucion.iniciada_en).total_seconds() // 60)
        return _error(
            request,
            f'Ya hay un análisis en curso, iniciado hace {minutos} minuto(s). '
            f'Espere a que termine antes de lanzar otro.',
            estado=409)

    if total_reglas() == 0:
        servicios.finalizar_ejecucion(ejecucion)
        return _error(
            request, 'No hay ninguna regla de diagnóstico activa, así que no hay nada '
                     'que analizar.')

    solicitados = list(ejecucion.modulos_solicitados or CLAVES_MODULOS)
    return render(request, 'pages/subsanacion/partials/progreso_analisis.html', {
        'ejecucion': ejecucion,
        'modulos': MODULOS,
        'primer_modulo': solicitados[0] if solicitados else None,
        'etiqueta_primero': ETIQUETA_MODULO.get(solicitados[0]) if solicitados else '',
    })


@admin_required
@require_POST
def ejecutar_modulo(request, pk, clave):
    """Ejecuta una categoría y devuelve su resultado más el disparador de la siguiente.

    Cada categoría es una petición HTTP independiente: es lo que mantiene cada
    petición muy por debajo del límite de tiempo de Gunicorn (30 s por defecto) sin
    necesidad de workers de fondo, que este proyecto no tiene.
    """
    ejecucion = get_object_or_404(EjecucionAnalisis, pk=pk)
    if ejecucion.estado != EjecucionAnalisis.EN_CURSO:
        return _error(
            request, 'Este análisis ya había terminado, así que no se continuó.', estado=409)
    if clave not in CLAVES_MODULOS:
        raise Http404('Categoría desconocida.')

    # El contexto se crea por petición: su memo comparte cálculos caros entre las
    # reglas de esta categoría, que es donde tiene sentido compartirlos.
    resumen = servicios.ejecutar_modulo(ejecucion, clave, contexto=ContextoAnalisis(ejecucion))
    siguiente = _siguiente_modulo(ejecucion, clave)

    return render(request, 'pages/subsanacion/partials/paso_modulo.html', {
        'ejecucion': ejecucion,
        'resumen': resumen,
        'siguiente': siguiente,
        'etiqueta_siguiente': ETIQUETA_MODULO.get(siguiente, ''),
    })


@admin_required
@require_POST
def finalizar_analisis(request, pk):
    """Cierra la ejecución, calcula el índice de salud y devuelve el resumen final."""
    ejecucion = get_object_or_404(EjecucionAnalisis, pk=pk)
    if ejecucion.estado == EjecucionAnalisis.EN_CURSO:
        servicios.finalizar_ejecucion(ejecucion)

    return render(request, 'pages/subsanacion/partials/resultado_analisis.html', {
        'ejecucion': ejecucion,
        'modulos': servicios.resumen_por_modulo(ejecucion),
    })
