"""Vistas del Centro de Diagnóstico de Integridad de Datos.

Todas las vistas exigen `permisos.acceso_subsanacion` (Administrador o Moderador) o
`permisos.solo_admin_subsanacion` (solo Administrador) — ver `subsanacion/permisos.py`
para el reparto completo. El barrido completo lee toda la empresa (ver el docstring
de `servicios`), así que no puede lanzarlo un moderador: si lo hiciera con alcance
parcial, la reconciliación daría por corregidos los hallazgos de las unidades que no
leyó. Por eso Dashboard, Estadísticas, Historial y la cadena de análisis son solo de
Administrador, mientras que el listado de Hallazgos sí lo puede ver un Moderador,
acotado a sus propias Unidades Organizativas.

`LoginRequiredMiddleware` ya está activo en todo el proyecto, así que
`@login_required` sería redundante; se mantienen los decoradores de `permisos.py`
porque el permiso tiene que leerse en el propio archivo.

Estilo: vistas basadas en función con fragmentos HTMX, igual que
`informe_inteligente` y `soporte`.
"""

import logging

from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import permisos, servicios
from .constantes import (
    CLAVES_MODULOS,
    COLOR_POR_CRITICIDAD,
    CRITICIDADES,
    DIAS_RESULTADO_ANTIGUO,
    ETIQUETA_MODULO,
    ICONO_POR_CRITICIDAD,
    MODULO_EXTRAS,
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
from .reglas import obtener_regla, obtener_reglas, total_reglas
from .servicios import AnalisisEnCurso

logger = logging.getLogger(__name__)

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
        # Excluye Extras, igual que `filtros.filtrar_hallazgos()` con «Todas»: el
        # badge de la pestaña Hallazgos tiene que coincidir con lo que esa pestaña
        # muestra por defecto, o parecería que faltan filas.
        'total_vigentes': Hallazgo.objects.filter(
            vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
            .exclude(modulo=MODULO_EXTRAS).count(),
    }


def _contexto_listado(request):
    consulta, filtros = filtrar_hallazgos(request)
    # Filas por página del usuario, comunes a todas las tablas (core/paginacion.py).
    from core.paginacion import filas_por_pagina
    paginador = Paginator(consulta, filas_por_pagina(request))
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


def _es_peticion_fragmento(request):
    """Igual criterio que `core.mixins.ModalOPaginaCompletaMixin`: jQuery añade
    `X-Requested-With` en toda petición `.load()`/`.ajax()` y HTMX añade `HX-Request`.
    Cualquier otra petición (navegación directa por URL) es «página completa»."""
    return (request.headers.get('x-requested-with') == 'XMLHttpRequest'
            or request.headers.get('HX-Request') == 'true')


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

@permisos.acceso_subsanacion
def index(request):
    """Página completa.

    Administrador: el dashboard se pinta ya renderizado, sin una segunda petición
    (como siempre). Moderador: no ve Dashboard/Estadísticas/Historial/Análisis (son
    del barrido completo, ver `permisos.py`) — entra directo a Hallazgos, ya acotado
    a sus propias Unidades Organizativas, con el mismo mecanismo de página completa
    que usa `panel_hallazgos()` para «volver aquí» tras corregir un registro.
    """
    if permisos.es_administrador(request.user):
        contexto = _contexto_dashboard()
        contexto['claves_modulos'] = CLAVES_MODULOS
        return render(request, 'pages/subsanacion/index.html', contexto)

    contexto = _contexto_listado(request)
    contexto['total_reglas'] = total_reglas()
    contexto['total_vigentes'] = contexto['total_resultados']
    contexto['tab_activo'] = 'hallazgos'
    return render(request, 'pages/subsanacion/index.html', contexto)


@permisos.solo_admin_subsanacion
def panel_dashboard(request):
    return render(request, 'pages/subsanacion/partials/panel_dashboard.html',
                  _contexto_dashboard())


@permisos.acceso_subsanacion
def panel_hallazgos(request):
    """Listado con filtros, búsqueda y paginación.

    Fuera de HTMX (navegación completa por esta URL, no un swap de pestaña) se
    devuelve la página completa de Subsanación con la pestaña de Hallazgos ya activa
    y estos mismos filtros ya aplicados, en vez del fragmento crudo sin el resto de
    la interfaz. Es el caso de `next` (`core.mixins.VolverAlOrigenMixin`): al
    guardar un registro corregido desde el enlace de un hallazgo, el usuario vuelve
    aquí con el mismo `?q=...` que tenía puesto — el filtro se conserva porque
    `hx-push-url="true"` en el formulario de filtros (ver `panel_hallazgos.html`)
    mantiene la barra de direcciones sincronizada con lo que hay en pantalla.
    """
    contexto = _contexto_listado(request)

    if _es_peticion_fragmento(request):
        return render(request, 'pages/subsanacion/partials/panel_hallazgos.html', contexto)

    if permisos.es_administrador(request.user):
        contexto.update(_contexto_dashboard())
        contexto['claves_modulos'] = CLAVES_MODULOS
    else:
        # Mismo recorte que `index()`: un Moderador no tiene Dashboard que mostrar.
        contexto['total_reglas'] = total_reglas()
        contexto['total_vigentes'] = contexto['total_resultados']
    contexto['tab_activo'] = 'hallazgos'
    return render(request, 'pages/subsanacion/index.html', contexto)


@permisos.acceso_subsanacion
def panel_reglas(request):
    """Índice de Reglas: qué comprueba cada código, por qué falla y cómo se corrige.

    Los textos salen de las propias reglas (`subsanacion/reglas/`), así que el
    índice no se puede desactualizar. Lo único que se consulta es cuántos hallazgos
    abiertos tiene cada regla —una sola consulta agrupada—, con el mismo alcance que
    el listado: un Moderador solo cuenta los de sus Unidades Organizativas.
    Incluye la ayuda de la búsqueda con prefijos (`core/busqueda.py`).
    """
    from core.busqueda import PREFIJOS

    abiertos = Hallazgo.objects.filter(
        vigente=True, estado__in=Hallazgo.ESTADOS_ABIERTOS)
    if not permisos.es_administrador(request.user):
        abiertos = abiertos.filter(
            unidad_organizativa_id__in=permisos.unidades_visibles(request.user)
            .values_list('pk', flat=True))
    conteo = dict(abiertos.order_by().values_list('codigo_regla')
                  .annotate(n=Count('id')).values_list('codigo_regla', 'n'))

    por_modulo = {clave: [] for clave, _, _ in MODULOS}
    for regla in obtener_reglas():
        por_modulo.setdefault(regla.modulo, []).append({
            'codigo': regla.codigo,
            'nombre': regla.nombre,
            'criticidad': dict(CRITICIDADES).get(regla.criticidad, ''),
            'color': COLOR_POR_CRITICIDAD.get(regla.criticidad, 'gris'),
            'icono_criticidad': ICONO_POR_CRITICIDAD.get(regla.criticidad, ''),
            'descripcion': regla.descripcion,
            'causa_probable': regla.causa_probable,
            'impacto': regla.impacto,
            'solucion': regla.solucion,
            'abiertos': conteo.get(regla.codigo, 0),
            # Extras no sale en «Todas» del listado: hay que pedir su categoría.
            'es_extra': regla.modulo == MODULO_EXTRAS,
        })
    categorias = [
        {'clave': clave, 'etiqueta': etiqueta, 'icono': icono,
         'reglas': sorted(por_modulo[clave], key=lambda r: r['codigo'])}
        for clave, etiqueta, icono in MODULOS if por_modulo.get(clave)
    ]
    return render(request, 'pages/subsanacion/partials/panel_reglas.html', {
        'categorias': categorias,
        'total': sum(len(c['reglas']) for c in categorias),
        'prefijos': [(clave, texto, ejemplo) for clave, (texto, ejemplo) in PREFIJOS.items()],
        'modulo_extras': MODULO_EXTRAS,
    })


@permisos.solo_admin_subsanacion
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


@permisos.solo_admin_subsanacion
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

@permisos.acceso_subsanacion
def exportar_excel(request):
    """Excel de lo que hay en pantalla, con los mismos filtros y la misma búsqueda.

    `exportar_a_excel()` llama a `filtros.filtrar_hallazgos(request)`, que ya acota
    por Unidad Organizativa para un Moderador — no hace falta repetir el alcance aquí.
    """
    return exportar_a_excel(request)


@permisos.acceso_subsanacion
def exportar_pdf(request):
    """PDF de lo que hay en pantalla, con los mismos filtros y la misma búsqueda.

    Mismo alcance que `exportar_excel()`: lo hereda de `filtrar_hallazgos(request)`.
    """
    return exportar_a_pdf(request)


@permisos.solo_admin_subsanacion
def panel_analisis(request):
    """Panel de «Ejecutar nuevo análisis»: el botón, o el aviso de que ya hay uno."""
    return render(request, 'pages/subsanacion/partials/panel_analisis.html', {
        'ejecucion_en_curso': servicios.obtener_ejecucion_en_curso(),
        'ultima': servicios.ultima_ejecucion_terminada(),
        'modulos': MODULOS,
        'total_reglas': total_reglas(),
    })


def _hallazgos_visibles(usuario):
    """Mismo alcance que `filtros.filtrar_hallazgos()`, para lookups por `pk`
    (detalle, cambio de estado): un Moderador no puede alcanzar el hallazgo de otra
    Unidad Organizativa ni manipulando la URL a mano — `get_object_or_404` sobre este
    queryset devuelve 404 en vez de filtrar datos ajenos.
    """
    consulta = Hallazgo.objects.select_related('content_type', 'revisado_por', 'ejecucion')
    if not permisos.es_administrador(usuario):
        uo_ids_visibles = permisos.unidades_visibles(usuario).values_list('pk', flat=True)
        consulta = consulta.filter(unidad_organizativa_id__in=uo_ids_visibles)
    return consulta


@permisos.acceso_subsanacion
def detalle_hallazgo(request, pk):
    """Detalle: qué encontró, por qué es un problema, cómo se corrige y a dónde ir."""
    hallazgo = get_object_or_404(_hallazgos_visibles(request.user), pk=pk)

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
            next_url=request.headers.get('HX-Current-URL'), origen_label='Subsanación',
            usuario=request.user),
        'revisiones': hallazgo.revisiones.select_related('usuario')[:20],
        'estados_disponibles': Hallazgo.ESTADOS,
        'color': COLOR_POR_CRITICIDAD.get(hallazgo.criticidad, 'gris'),
    })


# ---------------------------------------------------------------------------
# Cambio de estado: la única escritura que origina el usuario
# ---------------------------------------------------------------------------

@permisos.acceso_subsanacion
@require_POST
def cambiar_estado(request, pk):
    """Marca un hallazgo como revisado, ignorado o falso positivo.

    Solo escribe en tablas de Subsanación. No existe —ni existirá— una vista que
    modifique un dato de negocio: la corrección la hace el usuario desde el
    formulario correspondiente. Un Moderador solo puede hacerlo sobre hallazgos de
    sus propias Unidades Organizativas (`_hallazgos_visibles()`, arriba).
    """
    hallazgo = get_object_or_404(_hallazgos_visibles(request.user), pk=pk)
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


@permisos.solo_admin_subsanacion
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


@permisos.solo_admin_subsanacion
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


@permisos.solo_admin_subsanacion
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
