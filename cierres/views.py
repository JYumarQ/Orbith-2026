"""Capa HTTP del módulo Cierres. Solo HTTP.

Ninguna vista de aquí escribe estado: declarar, reabrir y procesar pasan siempre
por `servicios.py`. Lo único que hacen estas funciones es traducir la petición,
capturar `ErrorDeCierre` y devolver la respuesta que toque.

Reparto de responsabilidades entre pantallas:

* **Declarar y reabrir viven en el Gestor de Plantilla**, integradas en la
  toolbar de Unidades Organizativas: es donde el moderador está trabajando
  cuando termina de cuadrar su plantilla, y por tanto donde tiene sentido
  declararla al día. Por eso estas dos vistas responden `JsonResponse` con la
  forma `{status, message}`, que es la que ya consume `procesarRespuestaEliminar`
  en `gestor_plantilla.html`. No se inventa un mecanismo nuevo.
* **Esta app es la pantalla de consulta**: estados, historial, fotografías y el
  procesamiento manual. No declara nada.
"""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import filtros, servicios
from .constantes import DIA_FIN_VENTANA, DIA_INICIO_VENTANA
from .models import CierreUnidad, EstadoUnidad
from .periodos import en_ventana, periodo_de
from .permisos import acceso_cierres, es_administrador, solo_admin


def _ok(mensaje, **extra):
    return JsonResponse({'status': 'ok', 'message': mensaje, **extra})


def _error(mensaje, codigo=400):
    return JsonResponse({'status': 'error', 'message': mensaje}, status=codigo)


# --------------------------------------------------------------------------
# Acciones invocadas desde el Gestor de Plantilla
# --------------------------------------------------------------------------

@login_required
@acceso_cierres
@require_POST
def declarar(request, unidad_id):
    """Declara la unidad actualizada y congela su fotografía.

    El alcance se aplica en el queryset (`unidades_visibles`), no en un `if`: un
    moderador que fuerce la URL de una unidad ajena recibe 404, no un 200 con el
    trabajo hecho.
    """
    unidad = get_object_or_404(filtros.unidades_visibles(request.user), pk=unidad_id)
    try:
        cierre = servicios.declarar_actualizada(unidad, request.user)
    except servicios.ErrorDeCierre as error:
        return _error(str(error))

    from django.contrib import messages

    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primer_cierre_declarado')
    if cierre.en_plazo:
        from ranking.models import Actividad
        from ranking.servicios import registrar_actividad
        registrar_actividad(request.user, Actividad.CIERRE_EN_PLAZO, detalle=unidad.descripcion)

    return _ok(
        f'«{unidad.descripcion}» declarada actualizada para el cierre de '
        f'{cierre.periodo.etiqueta} ({cierre.estado_plazo.lower()}).',
        periodo=cierre.periodo.etiqueta,
        en_plazo=cierre.en_plazo)


@login_required
@acceso_cierres
@require_POST
def reabrir(request, unidad_id):
    """Devuelve la unidad a Pendiente para corregir datos y volver a declarar."""
    unidad = get_object_or_404(filtros.unidades_visibles(request.user), pk=unidad_id)
    try:
        servicios.reabrir(unidad, request.user)
    except servicios.ErrorDeCierre as error:
        return _error(str(error))

    return _ok(
        f'«{unidad.descripcion}» vuelve a Pendiente. Corrija la información y '
        'vuelva a declarar antes de que termine el plazo.')


# --------------------------------------------------------------------------
# Pantalla de consulta
# --------------------------------------------------------------------------

def _resumen_de(filas):
    """Las cuatro cifras que encabezan la pantalla.

    Se cuentan sobre `filas`, que ya está en memoria y ya viene filtrada: así el
    resumen dice siempre lo mismo que la tabla de debajo. Contarlo con consultas
    aparte habría dado, con un filtro puesto, unas cifras que no cuadran con lo
    que se ve.

    «Nunca declarada» no es un estado más: una unidad sin primera declaración no
    incumple nada, porque no se le puede reclamar ningún mes anterior. Por eso va
    en su propia cifra y no suma en las desactualizadas.
    """
    resumen = {'total': len(filas), 'actualizadas': 0,
               'desactualizadas': 0, 'nunca': 0}

    for fila in filas:
        estado = fila['estado']
        if not estado or estado.nunca_declarada:
            resumen['nunca'] += 1
        elif estado.estado == EstadoUnidad.ACTUALIZADA:
            resumen['actualizadas'] += 1
        elif estado.estado == EstadoUnidad.DESACTUALIZADA:
            resumen['desactualizadas'] += 1

    return resumen


def _contexto_lista(request, hoy=None):
    hoy = hoy or date.today()
    unidades, contexto = filtros.filtrar_unidades(request)

    filas = []
    for unidad in unidades:
        estado = getattr(unidad, 'estado_cierre', None)
        filas.append({
            'unidad': unidad,
            'estado': estado,
            'ultimo_cierre': estado.ultimo_cierre if estado else None,
        })

    contexto.update({
        'filas': filas,
        'resumen': _resumen_de(filas),
        'hoy': hoy,
        'ventana_abierta': en_ventana(hoy),
        'dia_inicio': DIA_INICIO_VENTANA,
        'dia_fin': DIA_FIN_VENTANA,
        'periodo_actual': periodo_de(hoy),
        'es_admin': es_administrador(request.user),
    })
    return contexto


@login_required
@acceso_cierres
def index(request):
    return render(request, 'pages/cierres/list_cierres.html', _contexto_lista(request))


@login_required
@acceso_cierres
def buscar(request):
    """Fragmento HTMX del listado, para la búsqueda y los filtros."""
    return render(request, 'pages/cierres/partials/lista_unidades.html',
                  _contexto_lista(request))


@login_required
@acceso_cierres
def historial(request, unidad_id):
    """Historial de cierres de una unidad. Fragmento para modal."""
    unidad = get_object_or_404(filtros.unidades_visibles(request.user), pk=unidad_id)
    return render(request, 'pages/cierres/partials/historial.html', {
        'unidad': unidad,
        'cierres': filtros.historial_visible(request.user, unidad),
    })


@login_required
@acceso_cierres
def detalle(request, cierre_id):
    """Contenido de una fotografía concreta, agrupado por departamento."""
    cierre = get_object_or_404(
        filtros.historial_visible(request.user), pk=cierre_id)

    por_departamento = {}
    for fila in cierre.cargos.all():
        clave = fila.departamento_descripcion or 'Sin departamento'
        por_departamento.setdefault(clave, []).append(fila)

    return render(request, 'pages/cierres/partials/detalle_cierre.html', {
        'cierre': cierre,
        'departamentos': sorted(por_departamento.items()),
        'total_contratos': cierre.contratos.count(),
    })


# --------------------------------------------------------------------------
# Procesamiento manual
# --------------------------------------------------------------------------

@login_required
@solo_admin
@require_POST
def procesar(request):
    """Recalcula estados y emite los avisos del día. Acción manual, solo Admin.

    Es deliberadamente manual: nadie quiere que un servidor decida por su cuenta
    marcar unidades como desactualizadas. El Administrador lo lanza cuando
    corresponde, y puede repetirlo sin efectos: el barrido es idempotente.
    """
    resumen = servicios.procesar_barrido(usuario=request.user)
    estados = resumen['estados']
    av = resumen['avisos']

    partes = [
        f"{estados['actualizadas']} actualizada(s), "
        f"{estados['pendientes']} pendiente(s), "
        f"{estados['desactualizadas']} desactualizada(s)."
    ]
    emitidos = av['plazo'] + av['ultimo_dia'] + av['desactualizadas']
    partes.append(f'{emitidos} aviso(s) emitido(s).' if emitidos
                  else 'Sin avisos que emitir hoy.')
    if av['sin_destinatario']:
        partes.append(
            f"{av['sin_destinatario']} unidad(es) sin moderador ni administradores "
            f"activos a los que avisar.")

    return _ok(' '.join(partes))
