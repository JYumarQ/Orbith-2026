"""Vistas de Pre-Nómina.

De momento contiene la configuración (los cuatro nomencladores). Las pantallas
del reporte se añaden en las fases siguientes.

Las cuatro tarjetas de configuración viven dentro de Parámetros Generales →
Nomencladores → Tiempo de Trabajo, pero **se cargan solas por HTMX**. Eso es lo
que permite que la huella sobre esa pantalla sea una única línea de `{% include %}`:
no dependen de ninguna variable de contexto, así que `ParametrosGeneralesView` no
hay que tocarla.

Protocolo, el mismo del resto del proyecto (`solicitudes/views.py`):
* éxito → `204` + `HX-Trigger` con `closeModal`, el evento de refresco de la
  tarjeta y `showMessage`;
* error → se vuelve a pintar el fragmento del modal con los errores del
  formulario dentro.
"""

import json
import logging
from datetime import date
from itertools import groupby

from django.db.models import ProtectedError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from cierres.periodos import Periodo

from . import captura, exportar, formulas, importar, permisos, servicios
from .filtros import filtrar_reportes, reportes_visibles, unidades_gestionables
from .forms import (NClaveAusenciaForm, NEscalaAnnosServicioForm,
                    NPagoHorasForm, NPagoImporteForm, ReportePagoForm)
from .models import (NClaveAusencia, NEscalaAnnosServicio, NPagoHoras,
                     NPagoImporte)
from .permisos import acceso_prenomina, requiere_escritura, solo_admin

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Registro de nomencladores
#
# Un solo juego de vistas atiende a los cuatro, despachando por esta tabla. La
# alternativa —dieciséis vistas casi idénticas— es justo lo que hace ilegible a
# `nomencladores/views.py`.
# --------------------------------------------------------------------------- #

NOMENCLADORES = {
    'pagos-horas': {
        'modelo': NPagoHoras,
        'formulario': NPagoHorasForm,
        'tarjeta': 'pages/prenomina/partials/tarjeta_pagos_horas.html',
        'evento': 'prenominaPagosHorasActualizado',
        'contexto': 'pagos_horas',
        'singular': 'Pago asociado por horas',
    },
    'pagos-importe': {
        'modelo': NPagoImporte,
        'formulario': NPagoImporteForm,
        'tarjeta': 'pages/prenomina/partials/tarjeta_pagos_importe.html',
        'evento': 'prenominaPagosImporteActualizado',
        'contexto': 'pagos_importe',
        'singular': 'Pago asociado por importe',
    },
    'claves-ausencia': {
        'modelo': NClaveAusencia,
        'formulario': NClaveAusenciaForm,
        'tarjeta': 'pages/prenomina/partials/tarjeta_claves_ausencia.html',
        'evento': 'prenominaClavesAusenciaActualizado',
        'contexto': 'claves_ausencia',
        'singular': 'Clave de ausencia',
    },
    'escala-annos': {
        'modelo': NEscalaAnnosServicio,
        'formulario': NEscalaAnnosServicioForm,
        'tarjeta': 'pages/prenomina/partials/tarjeta_escala_annos.html',
        'evento': 'prenominaEscalaAnnosActualizado',
        'contexto': 'escala_annos',
        'singular': 'Tramo de la escala de años de servicio',
    },
}


def _configuracion(tipo):
    """Devuelve la ficha del nomenclador, o 404 si el slug no existe.

    Se valida contra el diccionario y no contra la base de datos: un slug
    inventado en la URL nunca llega a tocar un modelo.
    """
    from django.http import Http404
    try:
        return NOMENCLADORES[tipo]
    except KeyError:
        raise Http404('Nomenclador desconocido.')


def _respuesta_htmx(mensaje, evento, icono='success'):
    """204 + `HX-Trigger`: el patrón que ya usan Solicitudes, Contratos y Estructura.

    204 sin cuerpo porque quien refresca la tarjeta es el evento, no la
    respuesta: así el modal se cierra y la tabla se recarga sin que la vista
    tenga que saber cómo estaba pintada.
    """
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps({
        'closeModal': True,
        evento: True,
        'showMessage': {'icon': icono, 'text': mensaje},
    })
    return respuesta


# --------------------------------------------------------------------------- #
# Tarjetas
# --------------------------------------------------------------------------- #

@solo_admin
def tarjeta(request, tipo):
    """Contenido de una tarjeta de configuración.

    Se pide con `hx-trigger="revealed"`, no con `load`: así no se lanza ninguna
    consulta mientras el acordeón «Tiempo de Trabajo» siga colapsado, y la
    pantalla de Parámetros no paga nada por quien no usa Pre-Nómina.
    """
    ficha = _configuracion(tipo)
    consulta = ficha['modelo'].objects.all()
    if tipo in ('pagos-importe', 'claves-ausencia'):
        consulta = consulta.select_related('relacionado_con')

    return render(request, ficha['tarjeta'], {
        ficha['contexto']: consulta,
        'tipo': tipo,
    })


# --------------------------------------------------------------------------- #
# Alta y edición
# --------------------------------------------------------------------------- #

@solo_admin
def guardar(request, tipo, pk=None):
    """Modal de alta/edición de cualquiera de los cuatro nomencladores.

    `GET` devuelve el formulario; `POST` lo valida. En el `POST` inválido se
    vuelve a pintar el mismo fragmento con los errores dentro, que es como el
    usuario ve el mensaje en español junto al campo.
    """
    ficha = _configuracion(tipo)
    instancia = get_object_or_404(ficha['modelo'], pk=pk) if pk else None

    if request.method == 'POST':
        formulario = ficha['formulario'](request.POST, instance=instancia)
        if formulario.is_valid():
            objeto = formulario.save()
            verbo = 'actualizado' if pk else 'creado'
            return _respuesta_htmx(
                f'{ficha["singular"]} «{objeto}» {verbo}.', ficha['evento'])
    else:
        formulario = ficha['formulario'](instance=instancia)

    return render(request, 'pages/prenomina/partials/modal_nomenclador.html', {
        'form': formulario,
        'tipo': tipo,
        'objeto': instancia,
        'titulo': ficha['singular'],
        # Solo los pagos por importe llevan fórmula, así que solo ahí se pinta el
        # comprobador en vivo.
        'con_formula': tipo == 'pagos-importe',
        'variables': formulas.VARIABLES,
    })


@solo_admin
@require_POST
def eliminar(request, tipo, pk):
    """Baja de un concepto.

    `PROTECT` impide borrar un concepto por horas del que cuelgue una fórmula o
    una clave de ausencia. Ese `ProtectedError` se traduce a un mensaje que dice
    **qué** lo está usando: un «no se puede eliminar» a secas obliga al
    Administrador a adivinar.
    """
    ficha = _configuracion(tipo)
    objeto = get_object_or_404(ficha['modelo'], pk=pk)
    etiqueta = str(objeto)

    try:
        objeto.delete()
    except ProtectedError as error:
        dependientes = ', '.join(sorted({str(o) for o in error.protected_objects})[:5])
        return _respuesta_htmx(
            f'No se puede eliminar «{etiqueta}»: lo utilizan {dependientes}. '
            f'Quite primero esa relación.',
            ficha['evento'], icono='error')

    return _respuesta_htmx(f'{ficha["singular"]} «{etiqueta}» eliminado.',
                           ficha['evento'])


# --------------------------------------------------------------------------- #
# Comprobación de fórmulas en vivo
# --------------------------------------------------------------------------- #

@solo_admin
@require_POST
def validar_formula(request):
    """Comprueba una fórmula mientras se escribe.

    Llama a la **misma** `formulas.validar()` que usa `NPagoImporte.clean()`: no
    hay una segunda implementación en JavaScript que pueda desalinearse. Esto es
    ayuda de escritura, no la validación real — la de verdad ocurre al guardar.
    """
    expresion = (request.POST.get('formula') or '').strip()
    if not expresion:
        return render(request, 'pages/prenomina/partials/formula_feedback.html',
                      {'vacia': True})

    try:
        formulas.validar(expresion)
    except formulas.ErrorDeFormula as error:
        return render(request, 'pages/prenomina/partials/formula_feedback.html',
                      {'error': str(error)})

    usadas = formulas.variables_usadas(expresion)
    contexto = {
        'valida': True,
        # El recordatorio solo si falta el concepto: el modal manda también
        # «Relacionado con» y repite la comprobación cuando cambia.
        'usa_horas': 'horas' in usadas and not request.POST.get('relacionado_con'),
        'variables_usadas': sorted(usadas),
    }
    # Vista previa con valores ficticios. `validar()` ya pasó con los valores
    # del ensayo, pero los de ejemplo son otros: si con ellos la fórmula falla o
    # da negativo, se dice en vez de enseñar un número.
    try:
        resultado, valores = formulas.ejemplo(expresion)
    except formulas.ErrorDeFormula:
        pass
    else:
        contexto.update({
            'ejemplo_valores': [(nombre, formulas.formatear(valor))
                                for nombre, valor in valores.items()],
            'ejemplo_resultado': formulas.formatear(resultado),
            'ejemplo_negativo': resultado < 0,
        })
    return render(request, 'pages/prenomina/partials/formula_feedback.html',
                  contexto)


# =========================================================================== #
# Reportes de pago
# =========================================================================== #

def _respuesta_reporte(mensaje, icono='success', extra=None):
    """204 + `HX-Trigger` para las acciones sobre un reporte."""
    disparadores = {
        'closeModal': True,
        'actualizarListaReportes': True,
        'showMessage': {'icon': icono, 'text': mensaje},
    }
    disparadores.update(extra or {})
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps(disparadores)
    return respuesta


def _con_avisos(mensaje, avisos, maximo=3):
    """Añade al mensaje los avisos de importes que se registraron como 0.

    Devuelve `(mensaje, icono)`: con avisos, el icono pasa a `warning` para que
    el usuario no lo tome por un guardado limpio. Se enseñan unos pocos; el
    resto se resume, porque una importación de 500 filas podría dar cientos.
    """
    if not avisos:
        return mensaje, 'success'
    partes = [mensaje, *avisos[:maximo]]
    if len(avisos) > maximo:
        partes.append(f'… y {len(avisos) - maximo} avisos más del mismo tipo.')
    return ' '.join(partes), 'warning'


def _paginar(request, consulta, por_pagina=15):
    from django.core.paginator import Paginator
    return Paginator(consulta, por_pagina).get_page(request.GET.get('page'))


@acceso_prenomina
def lista_reportes(request):
    """Pantalla «Gestión de Reportes de Pagos».

    Es la que abre el enlace «Pre-Nómina» de la barra lateral.
    """
    consulta, contexto = filtrar_reportes(request)
    contexto['pagina'] = _paginar(request, consulta)
    contexto['puede_crear'] = unidades_gestionables(request.user).exists()
    return render(request, 'pages/prenomina/lista_reportes.html', contexto)


@acceso_prenomina
def buscar_reportes(request):
    """Cuerpo de la tabla para las peticiones HTMX de búsqueda y filtro.

    `puede_crear` viaja también en el fragmento porque el estado vacío ofrece
    crear el primer reporte: sin él, ese botón desaparecería en cuanto el
    usuario tocara un filtro.
    """
    consulta, contexto = filtrar_reportes(request)
    contexto['pagina'] = _paginar(request, consulta)
    contexto['puede_crear'] = unidades_gestionables(request.user).exists()
    return render(request, 'pages/prenomina/partials/tabla_reportes.html', contexto)


@acceso_prenomina
@requiere_escritura
def nuevo_reporte(request):
    """Modal de alta de un reporte.

    El formulario solo ofrece las unidades que el usuario puede gestionar, y
    `servicios.crear_reporte()` lo vuelve a comprobar: el desplegable es
    comodidad, no seguridad.

    Sin plantillas no se puede empezar: los conceptos del reporte salen de una,
    así que en vez de un desplegable vacío se explica qué falta y se ofrece el
    enlace para crearla.
    """
    from .models import PlantillaReporte

    if not PlantillaReporte.objects.filter(usuario=request.user).exists():
        return render(request, 'pages/prenomina/partials/modal_sin_plantillas.html')

    formulario = ReportePagoForm(request.POST or None, usuario=request.user)

    if request.method == 'POST' and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            reporte = servicios.crear_reporte(
                datos['unidad'], Periodo(datos['anno'], datos['mes']),
                request.user,
                fecha_desde=datos['fecha_desde'],
                fecha_hasta=datos['fecha_hasta'],
                hecho_por=datos['hecho_por'],
                revisado_por=datos['revisado_por'],
                aprobado_por=datos['aprobado_por'],
                plantilla=datos['plantilla'])
        except servicios.ErrorDePreNomina as error:
            # El mensaje del servicio ya está redactado para el usuario: se
            # cuelga del formulario en vez de inventar otro texto en la vista.
            formulario.add_error(None, str(error))
        else:
            # Las tres firmas se recuerdan SOLO cuando el reporte se creó de
            # verdad. Guardarlas antes dejaría memorizado lo que el usuario
            # escribió en un intento que acabó en error.
            _recordar_firmas(request.user, reporte)
            return _respuesta_reporte(
                f'Reporte de {reporte.unidad_descripcion} — '
                f'{reporte.etiqueta_periodo} creado con '
                f'{reporte.total_trabajadores} trabajadores.')

    # El bloque del período va incrustado en el modal la primera vez y se
    # recarga solo después (`periodo_reporte`), así que necesita aquí el mismo
    # contexto que le pasa aquella vista.
    from .models import Quincena
    quincenal = servicios.es_pago_quincenal()
    quincena_inicial = Quincena.PRIMERA if quincenal else Quincena.MES_COMPLETO
    return render(request, 'pages/prenomina/partials/modal_reporte.html', {
        'form': formulario,
        'quincenal': quincenal,
        'quincena_texto': Quincena(quincena_inicial).label,
        'periodo_completo': False,
    })


def _recordar_firmas(usuario, reporte):
    """Deja en las preferencias del usuario los tres nombres que acaba de usar.

    Es una comodidad, no un dato del reporte: si falla, el reporte ya está
    creado y no hay nada que deshacer, así que no se propaga el error.
    """
    try:
        preferencias = usuario.obtener_preferencias()
        preferencias.reporte_hecho_por = reporte.hecho_por
        preferencias.reporte_revisado_por = reporte.revisado_por
        preferencias.reporte_aprobado_por = reporte.aprobado_por
        preferencias.save(update_fields=['reporte_hecho_por',
                                         'reporte_revisado_por',
                                         'reporte_aprobado_por',
                                         'fecha_actualizado'])
    except Exception:
        logger.exception('No se pudieron recordar las firmas del usuario %s.',
                         getattr(usuario, 'pk', None))


@acceso_prenomina
@requiere_escritura
def periodo_reporte(request):
    """Bloque del período del modal de alta, recalculado al vuelo.

    Lo pide el modal cada vez que cambian la unidad, el año o el mes. Devuelve
    el período de pago de la entidad, qué reporte tocaría crear (mes completo,
    1ra o 2da quincena) y las fechas «desde/hasta» que le corresponden.

    Es INFORMATIVO: la quincena de verdad la asigna `servicios.crear_reporte()`
    con la unidad bloqueada. Aquí se consulta sin bloqueo porque solo se está
    pintando una previsión, y si entre medias otro usuario crea ese reporte, el
    alta fallará con su mensaje correspondiente.
    """
    from .models import Quincena

    anno = (request.GET.get('anno') or '').strip()
    mes = (request.GET.get('mes') or '').strip()
    unidad = (request.GET.get('unidad') or '').strip()

    hoy = date.today()
    anno = int(anno) if anno.isdigit() and 2000 <= int(anno) <= 2100 else hoy.year
    mes = int(mes) if mes.isdigit() and 1 <= int(mes) <= 12 else hoy.month

    quincenal = servicios.es_pago_quincenal()
    completo = False

    if unidad.isdigit() and unidades_gestionables(request.user).filter(
            pk=int(unidad)).exists():
        quincena = servicios.siguiente_quincena(int(unidad), anno, mes)
        if quincena is None:
            # Ese mes ya está cubierto. Se avisa aquí para que el usuario lo vea
            # antes de rellenar el resto, aunque el alta lo volvería a rechazar.
            completo = True
            quincena = Quincena.SEGUNDA if quincenal else Quincena.MES_COMPLETO
    else:
        quincena = Quincena.PRIMERA if quincenal else Quincena.MES_COMPLETO

    formulario = ReportePagoForm(
        usuario=request.user, quincena=quincena,
        initial={'anno': anno, 'mes': mes})

    return render(request, 'pages/prenomina/partials/_periodo_reporte.html', {
        'form': formulario,
        'quincenal': quincenal,
        'quincena_texto': Quincena(quincena).label,
        'periodo_completo': completo,
    })


@acceso_prenomina
@require_POST
@requiere_escritura
def cerrar_reporte(request, pk):
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    try:
        servicios.cerrar_reporte(reporte, request.user)
    except servicios.ErrorDePreNomina as error:
        return _respuesta_reporte(str(error), icono='error')
    return _respuesta_reporte(
        f'Reporte de {reporte.etiqueta_periodo} cerrado.')


@acceso_prenomina
@require_POST
@requiere_escritura
def cerrar_mes(request):
    """Cierra de una vez todos los reportes en Borrador del período elegido.

    El resumen se compone aquí y no en el servicio porque es texto de interfaz:
    el servicio devuelve qué se cerró y qué no, y esta vista decide cómo
    contarlo. Si algo quedó fuera se avisa con icono de advertencia, no de
    éxito, aunque parte del trabajo sí se haya hecho.
    """
    anno = (request.POST.get('anno') or '').strip()
    mes = (request.POST.get('mes') or '').strip()
    if not (anno.isdigit() and mes.isdigit() and 1 <= int(mes) <= 12):
        return _respuesta_reporte(
            'Seleccione un año y un mes antes de cerrar el mes.', icono='error')

    try:
        cerrados, fallos = servicios.cerrar_mes(request.user, int(anno), int(mes))
    except servicios.ErrorDePreNomina as error:
        return _respuesta_reporte(str(error), icono='error')

    periodo = Periodo(int(anno), int(mes))
    if not fallos:
        return _respuesta_reporte(
            f'{periodo.etiqueta} cerrado: {len(cerrados)} '
            f'reporte{"s" if len(cerrados) != 1 else ""}.')

    detalle = '; '.join(f'{reporte.unidad_descripcion}: {motivo}'
                        for reporte, motivo in fallos[:3])
    if len(fallos) > 3:
        detalle += f' y {len(fallos) - 3} más'
    return _respuesta_reporte(
        f'Se cerraron {len(cerrados)} de {len(cerrados) + len(fallos)} reportes '
        f'de {periodo.etiqueta}. Quedaron abiertos — {detalle}',
        icono='warning')


@acceso_prenomina
@require_POST
@requiere_escritura
def reabrir_reporte(request, pk):
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    try:
        servicios.reabrir_reporte(reporte, request.user)
    except servicios.ErrorDePreNomina as error:
        return _respuesta_reporte(str(error), icono='error')
    return _respuesta_reporte(
        f'Reporte de {reporte.etiqueta_periodo} reabierto.')


# --------------------------------------------------------------------------- #
# Detalle del reporte: la rejilla
# --------------------------------------------------------------------------- #

def _agrupar_filas(reporte, filas):
    """Filas → Sub Unidad → Departamento, apoyándose en el orden de captura.

    `captura.contratos_de()` ya ordena primero por la subunidad y luego por el
    departamento (`unidad_organizativa__orden_informe`, `departamento__orden_informe`),
    y ese orden es el que congela `ReporteTrabajador.orden`. Por eso basta con
    `groupby` sobre `filas` tal cual llega: NO hace falta reordenarla aquí, y
    reordenarla rompería el criterio de captura.

    El nivel de Sub Unidad se omite cuando el reporte no es de una Unidad
    Principal: todas las filas comparten entonces la misma (única) unidad, y
    repetirla como «Sub Unidad» sería un encabezado redundante con la cabecera
    del reporte.
    """
    hay_subunidades = reporte.unidad.tipo.es_principal
    grupos = []
    for id_sub, filas_sub in groupby(
            filas, key=lambda f: f['trabajador'].unidad_sub_id_original):
        filas_sub = list(filas_sub)
        descripcion_sub = (filas_sub[0]['trabajador'].unidad_sub_descripcion
                            if hay_subunidades else '')
        departamentos = []
        for id_depto, (_, filas_depto) in enumerate(groupby(
                filas_sub, key=lambda f: f['trabajador'].departamento_descripcion)):
            filas_depto = list(filas_depto)
            departamentos.append({
                'id_dom': f'pn-depto-{id_sub or 0}-{id_depto}',
                'descripcion': filas_depto[0]['trabajador'].departamento_descripcion,
                'filas': filas_depto,
            })
        grupos.append({'descripcion': descripcion_sub, 'departamentos': departamentos})
    return grupos


def _rejilla(reporte):
    """Datos de la rejilla, pivotados en Python a partir de tres consultas.

    Se hace aquí y no en la plantilla porque una tabla de N trabajadores × ~30
    conceptos necesita que cada fila traiga sus celdas **en el orden de las
    columnas**; resolverlo con `{% for %}` anidados dispararía una consulta por
    celda.
    """
    conceptos_ausencia = list(reporte.conceptos_ausencia.all())
    conceptos_horas = list(reporte.conceptos_horas.all())
    conceptos_importe = list(reporte.conceptos_importe.all())

    trabajadores = list(
        reporte.trabajadores.prefetch_related(
            'valores_ausencia', 'valores_horas', 'valores_importe'))

    filas = []
    for trabajador in trabajadores:
        ausencias = {v.concepto_id: v.horas for v in trabajador.valores_ausencia.all()}
        horas = {v.concepto_id: v.horas for v in trabajador.valores_horas.all()}
        importes = {v.concepto_id: v.importe for v in trabajador.valores_importe.all()}
        filas.append({
            'trabajador': trabajador,
            'ausencias': [ausencias.get(c.pk) for c in conceptos_ausencia],
            'horas': [horas.get(c.pk) for c in conceptos_horas],
            'importes': [importes.get(c.pk) for c in conceptos_importe],
        })

    # Columnas fijas (Expediente, Nombres, Cat., Salario Escala) + Jornada +
    # Horas trabajadas, más una por cada concepto configurado (y el «Total a
    # descontar» de ausencias, si hay alguna). Es el ancho que deben abarcar
    # las filas de encabezado de Sub Unidad y Departamento con `colspan`.
    total_columnas = (5 + len(conceptos_ausencia) + (1 if conceptos_ausencia else 0)
                      + 1 + len(conceptos_horas) + len(conceptos_importe))

    return {
        'reporte': reporte,
        'conceptos_ausencia': conceptos_ausencia,
        'conceptos_horas': conceptos_horas,
        'conceptos_importe': conceptos_importe,
        'filas': filas,
        'grupos': _agrupar_filas(reporte, filas),
        'total_columnas': total_columnas,
        'configurado': bool(conceptos_ausencia or conceptos_horas
                            or conceptos_importe),
    }


@acceso_prenomina
def detalle_reporte(request, pk):
    """La rejilla, con la misma organización visual que el Excel de RRHH."""
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    contexto = _rejilla(reporte)
    contexto['puede_editar'] = permisos.puede_editar(request.user, reporte)
    contexto['puede_reabrir'] = permisos.puede_reabrir(request.user, reporte)
    return render(request, 'pages/prenomina/detalle_reporte.html', contexto)


@acceso_prenomina
def fila_trabajador(request, pk, trabajador_pk):
    """Una sola fila de la rejilla.

    Es lo que devuelve el modal al guardar: se reemplaza ese `<tr>` con
    `hx-swap="outerHTML"` y no se recarga la tabla entera.
    """
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    datos = _rejilla(reporte)
    fila = next((f for f in datos['filas']
                 if f['trabajador'].pk == trabajador_pk), None)
    if fila is None:
        raise Http404('Ese trabajador no pertenece al reporte.')

    return render(request, 'pages/prenomina/partials/fila_trabajador.html', {
        'fila': fila,
        'reporte': reporte,
        'puede_editar': permisos.puede_editar(request.user, reporte),
    })


# --------------------------------------------------------------------------- #
# Configuración de conceptos del reporte
# --------------------------------------------------------------------------- #

# La vista `configurar_conceptos` y su `_contexto_conceptos` se eliminaron: el
# marcado de conceptos uno a uno vive ahora solo en Mis Plantillas
# (`views_plantilla.guardar_plantilla`), y el reporte se limita a aplicar una
# plantilla (`views_plantilla.cambiar_plantilla`). No quedan dos formas de
# configurar los conceptos de un reporte.
#
# El SERVICIO `servicios.configurar_conceptos()` sigue existiendo y es quien
# congela los conceptos en el reporte: es el motor, no la pantalla. Lo llama
# ahora `servicios_plantilla.aplicar_a_reporte()`.


# --------------------------------------------------------------------------- #
# Captura de valores de una fila
# --------------------------------------------------------------------------- #

@acceso_prenomina
@requiere_escritura
def valores_trabajador(request, pk, trabajador_pk):
    """Modal de captura: ausencias y pagos por horas de un trabajador.

    Al guardar no se recarga la tabla: se devuelve el `<tr>` recalculado y htmx
    lo intercambia en su sitio.
    """
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    trabajador = get_object_or_404(reporte.trabajadores, pk=trabajador_pk)

    if request.method == 'POST':
        try:
            guardado = servicios.guardar_valores(
                trabajador.pk, request.user,
                ausencias=_horas_del_post(request.POST, 'ausencia'),
                horas=_horas_del_post(request.POST, 'horas'))
        except servicios.ErrorDePreNomina as error:
            return render(
                request, 'pages/prenomina/partials/modal_valores.html',
                {**_contexto_valores(reporte, trabajador, request.POST),
                 'error': str(error)})

        mensaje, icono = _con_avisos(
            f'Valores de {trabajador.nombre_completo} guardados.',
            guardado.avisos_importe)
        return _respuesta_reporte(mensaje, icono=icono,
                                  extra={'filaActualizada': trabajador.pk})

    return render(request, 'pages/prenomina/partials/modal_valores.html',
                  _contexto_valores(reporte, trabajador))


def _horas_del_post(datos, prefijo):
    """Extrae `{codigo: valor}` de los campos `<prefijo>_<codigo>`.

    Los campos de conceptos derivados van `disabled` en el formulario, así que
    el navegador ni los envía; si alguien forjara el POST, `guardar_valores()`
    los rechaza igualmente.
    """
    valores = {}
    for clave, valor in datos.items():
        if not clave.startswith(prefijo + '_'):
            continue
        sufijo = clave[len(prefijo) + 1:]
        if sufijo.isdigit():
            valores[int(sufijo)] = valor or 0
    return valores


def _contexto_valores(reporte, trabajador, datos=None):
    """Conceptos del reporte con el valor actual de este trabajador."""
    ausencias = []
    for valor in trabajador.valores_ausencia.select_related('concepto'):
        ausencias.append({'concepto': valor.concepto, 'valor': valor.horas})

    horas = []
    for valor in trabajador.valores_horas.select_related('concepto'):
        # Un concepto derivado se enseña, pero bloqueado: su valor es la suma de
        # las ausencias que lo alimentan y permitir que diverjan metería en el
        # documento una contradicción que él mismo no puede explicar.
        alimentado_por = [
            c.etiqueta for c in reporte.conceptos_ausencia.all()
            if c.relacionado_con_codigo == valor.concepto.codigo]
        horas.append({'concepto': valor.concepto, 'valor': valor.horas,
                      'alimentado_por': alimentado_por})

    ausencias.sort(key=lambda f: (f['concepto'].orden, f['concepto'].codigo))
    horas.sort(key=lambda f: (f['concepto'].orden, f['concepto'].codigo))

    return {
        'reporte': reporte,
        'trabajador': trabajador,
        'ausencias': ausencias,
        'horas': horas,
    }


# --------------------------------------------------------------------------- #
# Trabajadores del reporte
# --------------------------------------------------------------------------- #

@acceso_prenomina
@require_POST
@requiere_escritura
def quitar_trabajador(request, pk, trabajador_pk):
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    try:
        servicios.quitar_trabajador(reporte, trabajador_pk, request.user)
    except servicios.ErrorDePreNomina as error:
        return _respuesta_reporte(str(error), icono='error')
    return _respuesta_reporte('Trabajador retirado del reporte.',
                              extra={'recargarReporte': True})


@acceso_prenomina
@requiere_escritura
def agregar_trabajador(request, pk):
    """Modal para volver a añadir un trabajador que se había quitado.

    Solo ofrece a los que faltan: añadir exige releer su `CAlta` viva, así que
    quien no tenga contrato activo en la unidad no puede entrar.
    """
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)

    if request.method == 'POST':
        try:
            servicios.agregar_trabajador(
                reporte, request.POST.get('no_expediente', ''), request.user)
        except servicios.ErrorDePreNomina as error:
            return render(
                request, 'pages/prenomina/partials/modal_agregar_trabajador.html',
                {**_contexto_ausentes(reporte), 'error': str(error)})
        return _respuesta_reporte('Trabajador añadido al reporte.',
                                  extra={'recargarReporte': True})

    return render(request, 'pages/prenomina/partials/modal_agregar_trabajador.html',
                  _contexto_ausentes(reporte))


def _contexto_ausentes(reporte):
    presentes = set(reporte.trabajadores.values_list('no_expediente', flat=True))
    candidatos = [c for c in captura.contratos_de(reporte.unidad)
                  if c.no_expediente not in presentes]
    return {'reporte': reporte, 'candidatos': candidatos}


# --------------------------------------------------------------------------- #
# Exportación
# --------------------------------------------------------------------------- #

@acceso_prenomina
def exportar_reporte(request, pk):
    """Descarga el reporte en Excel.

    Es una lectura, así que la puede hacer cualquiera que vea el reporte,
    incluido el Observador: consultar es la razón de ser de ese rol. Importar es
    otra cosa y está cerrada a los roles de escritura.
    """
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)
    return exportar.exportar(reporte)


# --------------------------------------------------------------------------- #
# Importación
# --------------------------------------------------------------------------- #

@acceso_prenomina
@requiere_escritura
def importar_reporte(request, pk):
    """Modal de importación, con advertencia y confirmación obligatoria.

    Una sola petición: se analiza y, solo si no hay ni un error, se escribe. Sin
    estado en sesión ni ficheros temporales. Una previsualización en dos pasos
    sería deseable, pero exige guardar el archivo entre peticiones y no aporta
    nada a la atomicidad, que es lo que el requisito exige.
    """
    reporte = get_object_or_404(reportes_visibles(request.user), pk=pk)

    if request.method != 'POST':
        return render(request, 'pages/prenomina/partials/modal_importar.html',
                      {'reporte': reporte})

    archivo = request.FILES.get('archivo')
    if archivo is None:
        return render(request, 'pages/prenomina/partials/modal_importar.html',
                      {'reporte': reporte, 'error': 'Seleccione un archivo.'})

    resultado = importar.analizar(archivo, reporte, request.user)
    if not resultado.valido:
        return render(request, 'pages/prenomina/partials/modal_importar.html',
                      {'reporte': reporte, 'resultado': resultado})

    try:
        resumen = servicios.importar_valores(reporte, resultado.filas, request.user)
    except servicios.ErrorDePreNomina as error:
        return render(request, 'pages/prenomina/partials/modal_importar.html',
                      {'reporte': reporte, 'error': str(error)})

    mensaje, icono = _con_avisos(
        f'Importadas {resumen["filas"]} filas. Los importes se recalcularon.',
        resumen['avisos'])
    return _respuesta_reporte(mensaje, icono=icono,
                              extra={'recargarReporte': True})
