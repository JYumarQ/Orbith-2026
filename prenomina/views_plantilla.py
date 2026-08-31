"""Vistas de Pre-Nómina → Mis Plantillas.

Mismo protocolo HTMX del resto del proyecto: éxito → `204` con `HX-Trigger`;
error → se repinta el fragmento con el mensaje dentro, sin perder lo tecleado.

El alcance es personal: todo arranca de `request.user.plantillas_reporte`, así
que forzar la URL de una plantilla ajena devuelve 404 —no 403— para no confirmar
siquiera que ese identificador existe.

Las tres operaciones que abren el modal (crear, editar y duplicar) comparten
vista y plantilla: son el mismo formulario con distinto modo. Separarlas
habría significado mantener tres marcados casi iguales que se desincronizan a la
primera.
"""

import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import servicios_plantilla as sp
from .models import NClaveAusencia, NPagoHoras, NPagoImporte, PlantillaReporte
from .permisos import acceso_prenomina, requiere_escritura
from .servicios import ErrorDePreNomina

PLANTILLA = 'pages/prenomina/plantillas.html'
PARCIAL_LISTA = 'pages/prenomina/partials/lista_plantillas.html'
PARCIAL_MODAL = 'pages/prenomina/partials/modal_plantilla.html'
PARCIAL_AVISO = 'pages/prenomina/partials/aviso_plantilla.html'
PARCIAL_PREVIA = 'pages/prenomina/partials/previa_plantilla.html'


def _respuesta(mensaje, *, icono='success', extra=None):
    disparadores = {'closeModal': True,
                    'showMessage': {'message': mensaje, 'icon': icono}}
    disparadores.update(extra or {})
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps(disparadores)
    return respuesta


def _mis_plantillas(request):
    return (PlantillaReporte.objects.filter(usuario=request.user)
            .prefetch_related('claves_ausencia', 'pagos_horas', 'pagos_importe')
            .annotate())


def _contexto_lista(request):
    plantillas = list(_mis_plantillas(request))
    # `eliminable` se resuelve aquí y no en la plantilla para no disparar una
    # consulta por fila desde el `{% if %}`.
    usadas = set(PlantillaReporte.objects
                 .filter(usuario=request.user, reportes__isnull=False)
                 .values_list('pk', flat=True))
    for plantilla in plantillas:
        plantilla.esta_usada = plantilla.pk in usadas
    return {'plantillas': plantillas}


def _catalogo(marcadas_ausencia, marcadas_horas, marcadas_importe):
    """Catálogo completo de conceptos con lo que hay marcado.

    Es el mismo contenido que arma `views._contexto_conceptos()` para el
    reporte; se repite aquí porque aquélla necesita un reporte del que leer la
    selección y ésta trabaja sobre listas sueltas.
    """
    automaticos = set(NPagoImporte.objects
                      .filter(relacionado_con__codigo__in=marcadas_horas)
                      .values_list('codigo', flat=True))
    return {
        'claves_ausencia': NClaveAusencia.objects.select_related('relacionado_con'),
        'pagos_horas': NPagoHoras.objects.all(),
        'pagos_importe': NPagoImporte.objects.select_related('relacionado_con'),
        'marcadas_ausencia': marcadas_ausencia,
        'marcadas_horas': marcadas_horas,
        'marcadas_importe': marcadas_importe,
        'automaticos': automaticos,
    }


def _seleccion_del_post(datos):
    return (
        {int(c) for c in datos.getlist('ausencias') if str(c).isdigit()},
        {int(c) for c in datos.getlist('horas') if str(c).isdigit()},
        {int(c) for c in datos.getlist('importes') if str(c).isdigit()},
    )


# --------------------------------------------------------------------------- #
# Pantalla y listado
# --------------------------------------------------------------------------- #

@acceso_prenomina
def plantillas(request):
    """Pantalla «Plantillas para Reporte de Pago»."""
    return render(request, PLANTILLA, _contexto_lista(request))


@acceso_prenomina
def lista_plantillas(request):
    return render(request, PARCIAL_LISTA, _contexto_lista(request))


@acceso_prenomina
def previa_plantilla(request, pk):
    """La plantilla vista como estructura de reporte, sin trabajadores.

    Reutiliza `rejilla.html` con las mismas piezas que el reporte real, pero con
    los conceptos de la plantilla en vez de los congelados y **sin filas**: el
    usuario ve exactamente las columnas que tendrá el reporte que genere.

    Los conceptos se pasan tal cual son —objetos de nomenclador—, no copias:
    `rejilla.html` solo les pide `etiqueta`, `resta_horas_mes` y `es_derivado`,
    y los nomencladores tienen las tres. Lo que evita duplicar el marcado.
    """
    plantilla = get_object_or_404(_mis_plantillas(request), pk=pk)

    ausencias = list(plantilla.claves_ausencia.select_related('relacionado_con'))
    horas = list(plantilla.pagos_horas.all())
    codigos_horas = {p.codigo for p in horas}

    # Los importes automáticos entran solos al aplicarla: la vista previa tiene
    # que enseñarlos, o el usuario vería menos columnas de las que tendrá.
    automaticos = list(NPagoImporte.objects
                       .filter(relacionado_con__codigo__in=codigos_horas)
                       .select_related('relacionado_con'))
    manuales = list(plantilla.pagos_importe.exclude(
        codigo__in=[p.codigo for p in automaticos]))
    importes = sorted(automaticos + manuales, key=lambda p: p.codigo)

    # `es_derivado` no existe en el nomenclador: se calcula aquí igual que lo
    # haría el reporte, marcando los conceptos por horas a los que apunta alguna
    # ausencia seleccionada.
    derivados = {c.relacionado_con.codigo for c in ausencias if c.relacionado_con}
    for pago in horas:
        pago.es_derivado = pago.codigo in derivados

    return render(request, PARCIAL_PREVIA, {
        'plantilla': plantilla,
        'conceptos_ausencia': ausencias,
        'conceptos_horas': horas,
        'conceptos_importe': importes,
        'filas': [],
        'previa': True,
        'total_columnas': (5 + len(ausencias) + (1 if ausencias else 0)
                           + 1 + len(horas) + len(importes)),
    })


# --------------------------------------------------------------------------- #
# Alta, edición y duplicado
# --------------------------------------------------------------------------- #

@acceso_prenomina
@requiere_escritura
def guardar_plantilla(request, pk=None, modo='crear'):
    """Las tres operaciones del formulario, con el mismo marcado.

    `modo` viene de la URL y decide qué reglas se aplican al guardar:
    `crear` y `editar` solo exigen descripción y al menos un concepto;
    `duplicar` exige además que algo haya cambiado respecto del original.
    """
    original = None
    plantilla = None
    if pk is not None:
        objetivo = get_object_or_404(_mis_plantillas(request), pk=pk)
        if modo == 'duplicar':
            original = objetivo
        else:
            plantilla = objetivo

    if request.method == 'POST':
        descripcion = request.POST.get('descripcion', '')
        ausencias, horas, importes = _seleccion_del_post(request.POST)
        try:
            if modo == 'duplicar':
                sp.duplicar_plantilla(
                    original, request.user, descripcion=descripcion,
                    codigos_ausencia=ausencias, codigos_horas=horas,
                    codigos_importe=importes)
                mensaje = 'Plantilla duplicada.'
            elif plantilla is not None:
                sp.editar_plantilla(
                    plantilla, request.user, descripcion=descripcion,
                    codigos_ausencia=ausencias, codigos_horas=horas,
                    codigos_importe=importes)
                mensaje = 'Plantilla actualizada.'
            else:
                sp.crear_plantilla(
                    request.user, descripcion=descripcion,
                    codigos_ausencia=ausencias, codigos_horas=horas,
                    codigos_importe=importes)
                mensaje = 'Plantilla creada.'
        except ErrorDePreNomina as error:
            return render(request, PARCIAL_MODAL, {
                **_catalogo(ausencias, horas, importes),
                'modo': modo,
                'plantilla': plantilla,
                'original': original,
                'descripcion': descripcion,
                'error': str(error),
            })
        return _respuesta(mensaje, extra={'recargarPlantillas': True})

    # GET: se parte de la selección de la plantilla que se edita o duplica.
    fuente = plantilla or original
    if fuente is not None:
        ausencias, horas, importes = fuente.codigos()
        descripcion = fuente.descripcion if modo != 'duplicar' else ''
    else:
        ausencias, horas, importes = set(), set(), set()
        descripcion = ''

    return render(request, PARCIAL_MODAL, {
        **_catalogo(ausencias, horas, importes),
        'modo': modo,
        'plantilla': plantilla,
        'original': original,
        'descripcion': descripcion,
    })


@acceso_prenomina
@requiere_escritura
def validar_plantilla(request):
    """Validación en vivo del formulario, en cada cambio del usuario.

    Devuelve el bloque de aviso, que además lleva el `<button>` de guardar con su
    estado. Se manda el botón desde el servidor —en vez de habilitarlo con
    JavaScript— para que la pantalla no pueda decir una cosa distinta de lo que
    el backend va a aceptar: la misma función (`comprobar_duplicado`) decide en
    los dos sitios.
    """
    modo = request.GET.get('modo', 'crear')
    descripcion = request.GET.get('descripcion', '')
    seleccion = _seleccion_del_post(request.GET)

    aviso = None
    if modo == 'duplicar':
        original = get_object_or_404(
            _mis_plantillas(request), pk=request.GET.get('original'))
        aviso = sp.comprobar_duplicado(original, descripcion, seleccion)
    elif not any(seleccion):
        aviso = sp.MENSAJE_SIN_CONCEPTOS

    return render(request, PARCIAL_AVISO, {'aviso': aviso})


@acceso_prenomina
@requiere_escritura
def cambiar_plantilla(request, pk):
    """Sustituye la plantilla de un reporte en Borrador.

    Es lo que queda del antiguo «Conceptos del reporte»: ya no se marcan
    casillas sueltas —eso vive ahora solo en Mis Plantillas—, se elige otra
    plantilla y sus conceptos se vuelven a congelar.

    `servicios.configurar_conceptos()` hace el trabajo y ya rechaza los reportes
    que no estén en Borrador, así que no hay una segunda comprobación aquí que
    pueda quedar desincronizada de aquélla.
    """
    from .filtros import reportes_visibles
    from .models import ReportePago

    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    plantillas = list(_mis_plantillas(request))

    if request.method == 'POST':
        elegida = next((p for p in plantillas
                        if str(p.pk) == request.POST.get('plantilla')), None)
        if elegida is None:
            return render(request, 'pages/prenomina/partials/modal_cambiar_plantilla.html',
                          {'reporte': reporte, 'plantillas': plantillas,
                           'error': 'Seleccione una de sus plantillas.'})
        try:
            sp.aplicar_a_reporte(reporte, elegida, request.user)
        except ErrorDePreNomina as error:
            return render(request, 'pages/prenomina/partials/modal_cambiar_plantilla.html',
                          {'reporte': reporte, 'plantillas': plantillas,
                           'error': str(error)})
        return _respuesta(
            f'Reporte configurado con la plantilla «{elegida.descripcion}».',
            extra={'recargarReporte': True})

    return render(request, 'pages/prenomina/partials/modal_cambiar_plantilla.html',
                  {'reporte': reporte, 'plantillas': plantillas})


@acceso_prenomina
@requiere_escritura
@require_POST
def eliminar_plantilla(request, pk):
    plantilla = get_object_or_404(_mis_plantillas(request), pk=pk)
    try:
        sp.eliminar_plantilla(plantilla, request.user)
    except ErrorDePreNomina as error:
        return _respuesta(str(error), icono='error')
    return _respuesta('Plantilla eliminada.', extra={'recargarPlantillas': True})
