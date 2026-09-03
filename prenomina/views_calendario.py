"""Vistas de Pre-Nómina → Calendario.

Mismo protocolo HTMX que el resto del proyecto (`solicitudes/views.py`,
`prenomina/views.py`):

* éxito → `204` con `HX-Trigger` (`closeModal`, el evento de refresco de la
  tarjeta afectada y `showMessage`);
* error → se vuelve a pintar el fragmento con el mensaje dentro, para que el
  usuario no pierda lo que había escrito.

Las tres tarjetas se refrescan por separado (`recargarCalendarios`,
`recargarPeriodo`, `recargarTrabajadores`): una edición de horas no tiene por
qué repintar la lista de trabajadores.

El alcance es **personal**: todas las consultas arrancan de
`request.user.calendarios` / `.calendarios_pago`, así que un usuario no puede
alcanzar los de otro ni forzando la URL — recibe un 404, no un 403, para no
confirmarle que ese identificador existe.
"""

import json

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from cierres.constantes import MESES

from . import servicios_calendario as sc
from .filtros import unidades_gestionables
from .models import Calendario, CalendarioPago, CalendarioPagoDetalle
from .permisos import acceso_prenomina
from .servicios import ErrorDePreNomina

PLANTILLA = 'pages/prenomina/calendario.html'
PLANTILLA_TRABAJADORES = 'pages/prenomina/asignacion_trabajadores.html'
PARCIAL_CALENDARIOS = 'pages/prenomina/partials/tarjeta_calendarios.html'
PARCIAL_PERIODO = 'pages/prenomina/partials/tarjeta_periodo.html'
PARCIAL_TRABAJADORES = 'pages/prenomina/partials/tarjeta_trabajadores.html'
PARCIAL_MODAL_CAL = 'pages/prenomina/partials/modal_calendario.html'
PARCIAL_MODAL_SEL = 'pages/prenomina/partials/modal_seleccionar_calendario.html'
PARCIAL_MODAL_PERIODO = 'pages/prenomina/partials/modal_periodo.html'
PARCIAL_MODAL_ASIGNAR = 'pages/prenomina/partials/modal_asignar_calendario.html'


# --------------------------------------------------------------------------- #
# Utilidades compartidas
# --------------------------------------------------------------------------- #

def _respuesta(mensaje, *, icono='success', extra=None):
    """204 + HX-Trigger. Es el «guardado correcto» de todo el proyecto."""
    disparadores = {'closeModal': True,
                    'showMessage': {'message': mensaje, 'icon': icono}}
    disparadores.update(extra or {})
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps(disparadores)
    return respuesta


ANNOS_ATRAS = 3
ANNOS_ADELANTE = 5


def _annos_disponibles(usuario):
    """Años que ofrece el select de período.

    Es una **ventana móvil alrededor del año en curso**, no una lista fija: con
    un rango cerrado, el sistema se quedaría sin años que ofrecer en cuanto
    pasara el tiempo, que es justo lo que hay que evitar en un módulo que se usa
    mes a mes durante años.

    Hacia atrás se dejan unos pocos años para poder registrar períodos antiguos
    la primera vez que se usa el módulo; hacia adelante, margen de sobra para
    planificar. Se añaden además los años que ya tengan período, por si alguno
    cayera fuera de la ventana.
    """
    from datetime import date

    hoy = date.today().year
    annos = set(range(hoy - ANNOS_ATRAS, hoy + ANNOS_ADELANTE + 1))
    annos.update(CalendarioPago.objects.filter(usuario=usuario)
                 .values_list('anno', flat=True))
    ultimo = sc.ultimo_periodo(usuario)
    if ultimo:
        # Si el último período va por delante de la ventana, el siguiente tiene
        # que poder crearse igualmente.
        annos.update(range(ultimo.anno, ultimo.anno + ANNOS_ADELANTE + 1))
    return sorted(annos, reverse=True)


def _periodos_existentes(usuario):
    """Claves «AAAA-MM» de los Calendarios de Pago que ya tiene el usuario.

    Es lo que necesita la rejilla de meses del selector de período para resaltar
    los meses que existen y apagar los que no proceden. Devuelve claves de texto
    —y no objetos— porque es exactamente lo que compara el JavaScript.
    """
    return [f'{anno}-{mes:02d}' for anno, mes in
            CalendarioPago.objects.filter(usuario=usuario)
            .order_by('-anno', '-mes').values_list('anno', 'mes')]


def _clave_del_ultimo(usuario):
    """Clave «AAAA-MM» del último Calendario de Pago, o cadena vacía si no hay.

    El modal de alta la usa como mínimo de la rejilla, para que la regla «solo se
    admiten fechas posteriores al último período» —que impone
    `servicios_calendario.crear_periodo()`— se vea en pantalla en vez de descubrirse
    al recibir el error.
    """
    ultimo = sc.ultimo_periodo(usuario)
    return f'{ultimo.anno}-{ultimo.mes:02d}' if ultimo else ''


def _periodo_seleccionado(request):
    """El período que muestra la tarjeta 2, según los selects de Año y Mes.

    Si no se ha elegido nada todavía, se muestra el último período del usuario:
    es el que va a querer ver al entrar. Devuelve `(periodo | None, anno, mes)`.
    """
    anno = (request.GET.get('anno') or '').strip()
    mes = (request.GET.get('mes') or '').strip()

    if anno.isdigit() and mes.isdigit():
        periodo = (CalendarioPago.objects
                   .filter(usuario=request.user, anno=int(anno), mes=int(mes))
                   .first())
        return periodo, int(anno), int(mes)

    ultimo = sc.ultimo_periodo(request.user)
    if ultimo:
        return ultimo, ultimo.anno, ultimo.mes

    from datetime import date
    hoy = date.today()
    return None, hoy.year, hoy.month


def _contexto_calendarios(request):
    return {
        'calendarios': list(Calendario.objects.filter(usuario=request.user)),
    }


def _contexto_periodo(request):
    periodo, anno, mes = _periodo_seleccionado(request)
    detalles = []
    if periodo:
        detalles = list(periodo.detalles.select_related('calendario'))
    return {
        'periodo': periodo,
        'anno_actual': anno,
        'mes_actual': mes,
        'detalles': detalles,
        'annos_disponibles': _annos_disponibles(request.user),
        'meses': list(enumerate(MESES, start=1)),
        'periodos_existentes': _periodos_existentes(request.user),
    }


def _contexto_trabajadores(request):
    """Trabajadores del alcance del usuario, para la tarjeta de asignación.

    Se filtran por la unidad elegida en el select. Sin unidad elegida no se
    lista nada: una empresa entera son cientos de filas y ninguna decisión
    útil que tomar sobre ellas a la vez.
    """
    from contratos.models import CAlta

    unidades = unidades_gestionables(request.user)
    unidad = (request.GET.get('unidad') or '').strip()

    trabajadores = []
    if unidad.isdigit() and unidades.filter(pk=int(unidad)).exists():
        trabajadores = list(
            CAlta.objects
            .filter(cargo__departamento__unidad_organizativa_id=int(unidad),
                    aspirante__estado='ACTIVO')
            .select_related('aspirante', 'cargo', 'cargo__departamento',
                            'cargo__ncargo', 'asignacion_calendario',
                            'asignacion_calendario__calendario')
            .order_by('cargo__departamento__orden_informe',
                      'aspirante__papellido', 'aspirante__nombre'))

    return {
        'unidades': unidades,
        'unidad_actual': unidad,
        'trabajadores': trabajadores,
        'calendarios_activos': list(
            Calendario.objects.filter(usuario=request.user, activo=True)),
    }


# --------------------------------------------------------------------------- #
# Pantalla
# --------------------------------------------------------------------------- #

@acceso_prenomina
def calendario(request):
    """Pantalla «Pre-Nómina → Calendario»: catálogo de jornadas y período."""
    contexto = {}
    contexto.update(_contexto_calendarios(request))
    contexto.update(_contexto_periodo(request))
    return render(request, PLANTILLA, contexto)


@acceso_prenomina
def asignacion_trabajadores(request):
    """Pantalla «Pre-Nómina → Asignación de Trabajadores».

    Vive en su propia entrada del menú y no como tercera tarjeta del calendario:
    es una tabla de plantilla entera —decenas o cientos de filas— y compartir
    pantalla con los calendarios obligaba a desplazarse mucho para llegar a
    ella. Los calendarios que ofrece siguen siendo los del usuario.
    """
    return render(request, PLANTILLA_TRABAJADORES,
                  _contexto_trabajadores(request))


@acceso_prenomina
def tarjeta_calendarios(request):
    return render(request, PARCIAL_CALENDARIOS, _contexto_calendarios(request))


@acceso_prenomina
def tarjeta_periodo(request):
    return render(request, PARCIAL_PERIODO, _contexto_periodo(request))


@acceso_prenomina
def tarjeta_trabajadores(request):
    return render(request, PARCIAL_TRABAJADORES, _contexto_trabajadores(request))


# --------------------------------------------------------------------------- #
# Tarjeta 1: calendarios
# --------------------------------------------------------------------------- #

def _mis_calendarios(request):
    return Calendario.objects.filter(usuario=request.user)


@acceso_prenomina
def guardar_calendario(request, pk=None):
    """Alta y edición, en la misma vista porque comparten formulario.

    Al editar la descripción de un calendario ya usado, el modal manda además
    `actualizar_historico`. Si no viene esa decisión y hacía falta tomarla, se
    devuelve el modal de decisión en vez de guardar a ciegas.
    """
    calendario_obj = None
    if pk is not None:
        calendario_obj = get_object_or_404(_mis_calendarios(request), pk=pk)

    if request.method == 'POST':
        codigo = request.POST.get('codigo', '')
        descripcion = request.POST.get('descripcion', '')
        activo = request.POST.get('activo') == '1'
        decision = request.POST.get('actualizar_historico')

        try:
            if calendario_obj is None:
                sc.crear_calendario(request.user, codigo=codigo,
                                    descripcion=descripcion, activo=activo)
                mensaje = 'Calendario creado.'
            else:
                # Si cambia el nombre de un calendario ya usado y todavía no se
                # ha decidido qué hacer con el histórico, se pregunta antes.
                nueva = sc.normalizar_descripcion(descripcion)
                cambia = nueva != calendario_obj.descripcion
                usado = calendario_obj.detalles.exists()
                if cambia and usado and decision is None:
                    return render(request, PARCIAL_MODAL_CAL, {
                        'calendario': calendario_obj,
                        'decidir_historico': True,
                        'descripcion_nueva': nueva,
                        'codigo_nuevo': codigo,
                        'activo_nuevo': activo,
                        'periodos_afectados': list(
                            calendario_obj.periodos_donde_se_usa),
                    })

                sc.editar_calendario(
                    calendario_obj, request.user, codigo=codigo,
                    descripcion=descripcion, activo=activo,
                    actualizar_historico=(decision == '1'))
                mensaje = 'Calendario actualizado.'
        except ErrorDePreNomina as error:
            return render(request, PARCIAL_MODAL_CAL, {
                'calendario': calendario_obj,
                'error': str(error),
                'valores': request.POST,
            })

        return _respuesta(mensaje, extra={'recargarCalendarios': True,
                                          'recargarPeriodo': True,
                                          'recargarTrabajadores': True})

    return render(request, PARCIAL_MODAL_CAL, {'calendario': calendario_obj})


@acceso_prenomina
@require_POST
def eliminar_calendario(request, pk):
    calendario_obj = get_object_or_404(_mis_calendarios(request), pk=pk)
    try:
        sc.eliminar_calendario(calendario_obj, request.user)
    except ErrorDePreNomina as error:
        return _respuesta(str(error), icono='error')
    return _respuesta('Calendario eliminado.',
                      extra={'recargarCalendarios': True,
                             'recargarTrabajadores': True})


@acceso_prenomina
@require_POST
def desactivar_calendario(request, pk):
    """La alternativa que se ofrece cuando no se puede eliminar."""
    calendario_obj = get_object_or_404(_mis_calendarios(request), pk=pk)
    try:
        sc.marcar_inactivo(calendario_obj, request.user)
    except ErrorDePreNomina as error:
        return _respuesta(str(error), icono='error')
    return _respuesta('Calendario marcado como Inactivo.',
                      extra={'recargarCalendarios': True,
                             'recargarTrabajadores': True})


# --------------------------------------------------------------------------- #
# Tarjeta 2: período
# --------------------------------------------------------------------------- #

def _mis_periodos(request):
    return CalendarioPago.objects.filter(usuario=request.user)


@acceso_prenomina
def nuevo_periodo(request):
    if request.method == 'POST':
        try:
            periodo = sc.crear_periodo(request.user,
                                       anno=request.POST.get('anno'),
                                       mes=request.POST.get('mes'))
        except ErrorDePreNomina as error:
            # `ultimo` viaja también en la rama de error: sin él, el aviso del
            # pie del modal decía «es su primer Calendario de Pago» a alguien que
            # acababa de chocar precisamente contra la regla del último período.
            return render(request, PARCIAL_MODAL_PERIODO, {
                'error': str(error),
                'annos_disponibles': _annos_disponibles(request.user),
                'meses': list(enumerate(MESES, start=1)),
                'periodos_existentes': _periodos_existentes(request.user),
                'minimo_periodo': _clave_del_ultimo(request.user),
                # Tras un error, la rejilla vuelve a marcar lo que el usuario
                # había elegido: reabrirla en blanco le haría empezar de cero.
                'anno_inicial': request.POST.get('anno', ''),
                'mes_inicial': request.POST.get('mes', ''),
                'ultimo': sc.ultimo_periodo(request.user),
                'valores': request.POST,
            })
        return _respuesta(
            f'Calendario de Pago de {periodo.etiqueta} creado.',
            extra={'recargarPeriodo': True,
                   'periodoCreado': {'anno': periodo.anno, 'mes': periodo.mes}})

    # El modal arranca en la fecha que el usuario tenga elegida en la tarjeta
    # (llega por `hx-include` de los selects): es la que está mirando, así que es
    # la que espera ver. Si no llega ninguna, se propone el mes siguiente al
    # último período, que es el movimiento habitual.
    ultimo = sc.ultimo_periodo(request.user)
    sugerido = ultimo.periodo.siguiente() if ultimo else None
    anno, mes = request.GET.get('anno', ''), request.GET.get('mes', '')
    if anno.isdigit() and mes.isdigit() and 1 <= int(mes) <= 12:
        from cierres.periodos import Periodo
        sugerido = Periodo(int(anno), int(mes))

    return render(request, PARCIAL_MODAL_PERIODO, {
        'annos_disponibles': _annos_disponibles(request.user),
        'meses': list(enumerate(MESES, start=1)),
        'periodos_existentes': _periodos_existentes(request.user),
        'minimo_periodo': _clave_del_ultimo(request.user),
        'anno_inicial': sugerido.anno if sugerido else '',
        'mes_inicial': sugerido.mes if sugerido else '',
        'ultimo': ultimo,
        'sugerido': sugerido,
    })


@acceso_prenomina
@require_POST
def eliminar_periodo(request, pk):
    periodo = get_object_or_404(_mis_periodos(request), pk=pk)
    try:
        sc.eliminar_periodo(periodo, request.user)
    except ErrorDePreNomina as error:
        return _respuesta(str(error), icono='error')
    return _respuesta('Calendario de Pago eliminado.',
                      extra={'recargarPeriodo': True})


@acceso_prenomina
def seleccionar_calendarios(request, pk):
    """Modal de selección múltiple. Solo ofrece los activos como seleccionables."""
    periodo = get_object_or_404(_mis_periodos(request), pk=pk)

    if request.method == 'POST':
        try:
            sc.seleccionar_calendarios(
                periodo, request.user, request.POST.getlist('calendarios'))
        except ErrorDePreNomina as error:
            return render(request, PARCIAL_MODAL_SEL, {
                'periodo': periodo,
                'calendarios': list(_mis_calendarios(request)),
                'ya_incluidos': set(
                    periodo.detalles.values_list('calendario_id', flat=True)),
                'error': str(error),
            })
        return _respuesta('Calendarios añadidos al período.',
                          extra={'recargarPeriodo': True})

    return render(request, PARCIAL_MODAL_SEL, {
        'periodo': periodo,
        'calendarios': list(_mis_calendarios(request)),
        'ya_incluidos': set(
            periodo.detalles.values_list('calendario_id', flat=True)),
    })


@acceso_prenomina
@require_POST
def guardar_horas(request, pk):
    """Edición en línea de una quincena. Devuelve la fila para intercambiarla.

    No abre modal: el `<td>` se convierte en input con doble clic y al confirmar
    llega aquí. Se responde con la fila entera (no solo la celda) porque
    «Horas Mes» es calculada y tiene que repintarse con el nuevo total.
    """
    detalle = get_object_or_404(
        CalendarioPagoDetalle.objects.select_related('calendario_pago'),
        pk=pk, calendario_pago__usuario=request.user)

    try:
        detalle = sc.guardar_horas(detalle, request.user,
                                   horas_q1=request.POST.get('horas_q1'),
                                   horas_q2=request.POST.get('horas_q2'))
    except ErrorDePreNomina as error:
        respuesta = render(
            request, 'pages/prenomina/partials/fila_periodo.html',
            {'detalle': detalle, 'periodo': detalle.calendario_pago})
        respuesta['HX-Retarget'] = f'#fila-detalle-{detalle.pk}'
        respuesta['HX-Trigger'] = json.dumps(
            {'showMessage': {'message': str(error), 'icon': 'error'}})
        return respuesta

    return render(request, 'pages/prenomina/partials/fila_periodo.html',
                  {'detalle': detalle, 'periodo': detalle.calendario_pago})


@acceso_prenomina
@require_POST
def quitar_detalle(request, pk):
    detalle = get_object_or_404(
        CalendarioPagoDetalle.objects.select_related('calendario_pago'),
        pk=pk, calendario_pago__usuario=request.user)
    try:
        sc.quitar_detalle(detalle, request.user)
    except ErrorDePreNomina as error:
        return _respuesta(str(error), icono='error')
    return _respuesta('Calendario retirado del período.',
                      extra={'recargarPeriodo': True})


# --------------------------------------------------------------------------- #
# Tarjeta 3: asignación a trabajadores
# --------------------------------------------------------------------------- #

@acceso_prenomina
def asignar_calendario(request):
    """Modal de asignación masiva. Recibe los trabajadores marcados."""
    seleccionados = request.POST.getlist('trabajadores') or request.GET.getlist(
        'trabajadores')

    if request.method == 'POST' and request.POST.get('calendario'):
        try:
            calendario_obj = get_object_or_404(
                _mis_calendarios(request), pk=request.POST.get('calendario'))
            cuantos = sc.asignar_calendario(
                seleccionados, calendario_obj, request.user)
        except ErrorDePreNomina as error:
            return render(request, PARCIAL_MODAL_ASIGNAR, {
                'seleccionados': seleccionados,
                'calendarios_activos': list(
                    Calendario.objects.filter(usuario=request.user, activo=True)),
                'error': str(error),
            })
        return _respuesta(
            f'Calendario asignado a {cuantos} trabajador'
            f'{"es" if cuantos != 1 else ""}.',
            extra={'recargarTrabajadores': True})

    if not seleccionados:
        return render(request, PARCIAL_MODAL_ASIGNAR, {
            'error': 'Seleccione al menos un trabajador de la lista.',
            'seleccionados': [],
            'calendarios_activos': [],
        })

    return render(request, PARCIAL_MODAL_ASIGNAR, {
        'seleccionados': seleccionados,
        'calendarios_activos': list(
            Calendario.objects.filter(usuario=request.user, activo=True)),
    })


@acceso_prenomina
@require_POST
def quitar_asignacion(request):
    cuantos = sc.quitar_asignacion(
        request.POST.getlist('trabajadores'), request.user)
    if not cuantos:
        return _respuesta('No había asignaciones que retirar.', icono='info')
    return _respuesta(
        f'Retirada la asignación de {cuantos} trabajador'
        f'{"es" if cuantos != 1 else ""}.',
        extra={'recargarTrabajadores': True})
