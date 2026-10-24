"""Vistas del módulo Solicitudes.

Reparto de responsabilidades: estas vistas resuelven HTTP (qué se pinta, qué se
devuelve, cómo se repinta un formulario con errores) y delegan TODA mutación de estado en
`solicitudes/servicios.py`. Ninguna vista escribe `solicitud.estado` directamente.

La pieza no evidente es `_filas_de_comparacion()`: construye en Python la tabla de la
pantalla de revisión —etiqueta, valor original legible, widget editable y marca de
modificado— recorriendo el ModelForm real de la operación. Se hace aquí y no en la
plantilla porque una sola plantilla tiene que servir para las diez operaciones, y la
lógica de «qué se muestra a la izquierda y qué widget va a la derecha» no cabe en un
`{% for %}` sin volverse ilegible.
"""

import json

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from solicitudes import serializacion, servicios
from solicitudes.filtros import PESTANAS, filtrar_solicitudes, pestanas_con_contadores
from solicitudes.forms import MotivoDecisionForm, SolicitudDesdeTablaForm
from solicitudes.models import AccionSolicitud, EstadoSolicitud, Solicitud
from solicitudes.operaciones import (
    OperacionDesconocida, definicion_de, form_de_aprobacion, form_kwargs_de)
from solicitudes.permisos import (
    AccesoSolicitudesMixin, acceso_solicitudes, es_administrador, solo_admin)



# ----------------------------------------------------------------------
# Utilidades compartidas
# ----------------------------------------------------------------------

def _respuesta_htmx(mensaje, icono='success', extra=None):
    """204 + `HX-Trigger`, el patrón que ya usan Estructura Organizativa y Contratos.

    204 sin cuerpo porque quien refresca la tabla es el evento `updateSolicitudList`,
    no la respuesta: así el modal se cierra y el listado se recarga sin que la vista
    tenga que saber en qué pestaña o con qué filtros estaba el usuario.
    """
    triggers = {
        'closeModal': True,
        'updateSolicitudList': True,
        'showMessage': {'icon': icono, 'text': mensaje},
    }
    triggers.update(extra or {})
    respuesta = HttpResponse(status=204)
    respuesta['HX-Trigger'] = json.dumps(triggers)
    return respuesta


def _es_fragmento(request):
    return (request.headers.get('HX-Request') == 'true'
            or request.headers.get('x-requested-with') == 'XMLHttpRequest')


def _volver_al_listado(request):
    """URL del listado conservando la pestaña desde la que se actuó.

    Sin esto, rechazar una solicitud desde «En Espera» devolvería al usuario a esa misma
    pestaña, donde la solicitud ya no está, dando la impresión de que se perdió.
    """
    pestana = request.POST.get('tab') or request.GET.get('tab')
    url = reverse('list_solicitudes')
    return f'{url}?tab={pestana}' if pestana in PESTANAS else url


def _solicitud_visible(request, pk):
    """Trae la solicitud comprobando que este usuario tiene derecho a verla.

    404 y no 403 cuando no le corresponde: a un Moderador no se le confirma siquiera que
    exista una solicitud de otro Moderador.
    """
    solicitud = get_object_or_404(
        Solicitud.objects.select_related(
            'solicitante', 'revisor', 'decidida_por', 'unidad', 'content_type'),
        pk=pk)
    if not solicitud.es_visible_para(request.user):
        from django.http import Http404
        raise Http404('Solicitud no encontrada.')
    return solicitud


def _filas_de_comparacion(solicitud, usuario, formulario=None):
    """Filas de la tabla «Situación Actual | Cambio propuesto».

    `formulario` es el de la columna derecha. Si no se pasa, se construye no ligado con
    los datos propuestos como `initial`. Si se pasa (POST con errores, o POST del
    Administrador), se respeta para conservar lo que el usuario escribió y sus errores.

    En una ELIMINACIÓN no hay nada editable: `campo` va a None y la plantilla pinta el
    aviso de eliminación en lugar de widgets.
    """
    definicion = definicion_de(solicitud.operacion)
    form_class = definicion['form']
    if form_class is None:
        return [], None
    # `form_de_aprobacion`, no `form_class` a secas: es la misma clase que valida al
    # aprobar (ver `solicitudes/servicios.py::aprobar`), para que el formulario que se
    # pinta aquí y el que de verdad procesa el POST sean siempre el mismo.
    form_class = form_de_aprobacion(definicion)

    form_kwargs = form_kwargs_de(definicion, usuario)
    es_eliminacion = definicion['accion'] == AccionSolicitud.ELIMINAR

    # En una eliminación la referencia son los datos originales: no hay propuesta que
    # mostrar, lo que se propone es que todo esto desaparezca.
    datos_derecha = solicitud.datos_originales if es_eliminacion else solicitud.datos_propuestos

    if formulario is None and not es_eliminacion:
        formulario = serializacion.construir_formulario(
            form_class,
            instancia=solicitud.objeto_afectado,
            initial=datos_derecha,
            form_kwargs=form_kwargs)

    originales = serializacion.para_mostrar(
        form_class, solicitud.datos_originales, form_kwargs=form_kwargs)
    propuestos_texto = serializacion.para_mostrar(
        form_class, datos_derecha, form_kwargs=form_kwargs)
    cambiados = set() if es_eliminacion else serializacion.comparar(
        solicitud.datos_originales, solicitud.datos_propuestos)

    # Campos que no se leen de `datos_originales`/`datos_propuestos` sino que se
    # recalculan a partir del Cargo real de cada columna (ver el bloque «Campos
    # calculados desde el Cargo» en `solicitudes/operaciones.py`). Nunca son editables
    # ni cuentan para `cambiados`: no describen una decisión que nadie tomó, describen
    # una consecuencia del Cargo de esa columna.
    campos_calculados = definicion.get('campos_calculados') or {}
    if campos_calculados:
        from strorganizativa.models import CargoPlantilla

        def _cargo_de(datos):
            pk = (datos or {}).get('cargo')
            return CargoPlantilla.objects.select_related('rol', 'ncargo__grupo_escala').filter(
                pk=pk).first() if pk else None

        def _texto_calculado(valor):
            if valor is None or valor == '':
                return serializacion.VACIO
            if isinstance(valor, bool):
                return 'Sí' if valor else 'No'
            return str(valor)

        cargo_original = _cargo_de(solicitud.datos_originales)
        cargo_propuesto = cargo_original if es_eliminacion else _cargo_de(datos_derecha)

        for nombre, resolver in campos_calculados.items():
            originales[nombre] = _texto_calculado(resolver(cargo_original))
            propuestos_texto[nombre] = _texto_calculado(resolver(cargo_propuesto))
            cambiados.discard(nombre)

        # El widget editable de `funcionario_res`/`designado_res` se deshabilita cuando
        # el Cargo PROPUESTO no exige esa condición: no tiene sentido dejar que el
        # Administrador escriba un número de resolución para un cargo que no es
        # Funcionario/Designado. Se evalúa una sola vez, al cargar la pantalla — el
        # Cargo no tiene un switch que el Administrador pueda tocar aquí mismo, así que
        # a diferencia del bloque de abajo no hace falta JavaScript para esto.
        if formulario is not None:
            _NUMERO_RES_POR_CONDICION = {
                'funcionario': 'funcionario_res',
                'designado': 'designado_res',
                'de_confianza': 'confianza_res',
            }
            for nombre_condicion, nombre_numero in _NUMERO_RES_POR_CONDICION.items():
                if nombre_condicion in campos_calculados and nombre_numero in formulario.fields:
                    if not campos_calculados[nombre_condicion](cargo_propuesto):
                        formulario.fields[nombre_numero].disabled = True

    # Los switches C. Formal / Chofer Profesional / Misión siguen el mismo criterio que
    # `updt_contrato.html` ya usa con el Moderador: su campo de detalle solo se habilita
    # si el switch está activo. Se evalúa aquí contra el valor PROPUESTO para que la
    # pantalla no se abra con «No. Res. C. Formal» habilitado si C. Formal está en «No».
    # `comparacion.html` trae el JavaScript que reacciona en vivo si el Administrador
    # cambia el switch en esta misma pantalla antes de aprobar.
    _CAMPOS_POR_SWITCH = {
        'c_formal': ('c_formal_res',),
        'profesional': ('fecha_vence_lic', 'fecha_vence_recal', 'fecha_vence_seg'),
        'mision': ('pais', 'mision_dias', 'mision_importe'),
    }
    if formulario is not None:
        for switch, detalles in _CAMPOS_POR_SWITCH.items():
            if switch not in formulario.fields:
                continue
            activo = bool(datos_derecha.get(switch))
            for detalle in detalles:
                if detalle in formulario.fields and not activo:
                    formulario.fields[detalle].disabled = True

    # Se recorre un formulario vacío para fijar el orden y las etiquetas incluso cuando
    # no hay formulario editable (eliminaciones).
    referencia = formulario or serializacion.construir_formulario(
        form_class, form_kwargs=form_kwargs)

    filas = []
    for nombre, campo in referencia.fields.items():
        filas.append({
            'nombre': nombre,
            'etiqueta': campo.label or nombre.replace('_', ' ').capitalize(),
            'original': originales.get(nombre, serializacion.VACIO),
            'propuesto_texto': propuestos_texto.get(nombre, serializacion.VACIO),
            'campo': None if (es_eliminacion or nombre in campos_calculados) else referencia[nombre],
            'cambiado': nombre in cambiados,
        })
    return filas, (None if es_eliminacion else formulario)


def _contexto_solicitud(solicitud, usuario, formulario=None, editable=False):
    """Contexto común de las pantallas de revisión y de solo lectura."""
    definicion = definicion_de(solicitud.operacion)
    filas, formulario = _filas_de_comparacion(solicitud, usuario, formulario)
    form_kwargs = form_kwargs_de(definicion, usuario)

    # La fotografía nunca se recaptura, así que puede haber dejado de reflejar el
    # registro real. No es un fallo, pero quien decide tiene que saberlo.
    registro_desincronizado = False
    if definicion['form'] is not None and solicitud.pendiente:
        registro_desincronizado = not serializacion.coincide_con_registro(
            solicitud, definicion['form'], form_kwargs=form_kwargs)

    return {
        'solicitud': solicitud,
        'definicion': definicion,
        'filas': filas,
        'form': formulario,
        'editable': editable,
        'es_eliminacion': definicion['accion'] == AccionSolicitud.ELIMINAR,
        'es_creacion': definicion['accion'] == AccionSolicitud.CREAR,
        'registro_desincronizado': registro_desincronizado,
        'form_rechazo': MotivoDecisionForm(),
    }


# ----------------------------------------------------------------------
# Listado
# ----------------------------------------------------------------------

@acceso_solicitudes
def lista_solicitudes(request):
    """Tabla principal con las tres pestañas."""
    consulta, contexto = filtrar_solicitudes(request, request.user)
    pagina = _paginar(request, consulta)

    contexto.update({
        'solicitudes': pagina,
        'page_obj': pagina,
        'pestanas': pestanas_con_contadores(request.user),
        'es_admin': es_administrador(request.user),
        'form_alta': SolicitudDesdeTablaForm(),
    })
    return render(request, 'pages/solicitudes/list_solicitud.html', contexto)


@acceso_solicitudes
def buscar_solicitudes(request):
    """Cuerpo de la tabla para las peticiones HTMX de búsqueda, filtro y paginación."""
    consulta, contexto = filtrar_solicitudes(request, request.user)
    pagina = _paginar(request, consulta)

    contexto.update({
        'solicitudes': pagina,
        'page_obj': pagina,
        'es_admin': es_administrador(request.user),
    })
    return render(
        request, 'pages/solicitudes/partials/filter_solicitud_list.html', contexto)


def _paginar(request, consulta):
    # Paginación común: las filas por página del usuario (core/paginacion.py).
    from core.paginacion import paginar
    pagina = paginar(request, consulta)
    pagina.object_list = _anotar_permisos(list(pagina.object_list), request.user)
    return pagina


def _anotar_permisos(solicitudes, usuario):
    """Resuelve por fila qué puede hacer este usuario, para que lo lea la plantilla.

    Las plantillas de Django no pueden llamar a un método pasándole el usuario, así que
    o se resuelve aquí o habría que reimplementar las reglas en el HTML —con el riesgo
    de que digan algo distinto que el modelo—. Los flags SOLO deciden qué botones se
    ven: cada acción vuelve a comprobar los permisos en `solicitudes/servicios.py`.
    """
    admin = es_administrador(usuario)
    for solicitud in solicitudes:
        bloqueada_por_otro = solicitud.bloqueada and solicitud.revisor_id != usuario.pk
        solicitud.puede_revisar = solicitud.puede_revisarla(usuario)
        solicitud.puede_editar = solicitud.puede_editarla(usuario)
        solicitud.puede_eliminar = solicitud.puede_eliminarla(usuario)
        solicitud.puede_rechazar = admin and solicitud.pendiente and not bloqueada_por_otro
        solicitud.puede_cancelar = admin and solicitud.estado == EstadoSolicitud.EN_REVISION
        solicitud.puede_devolver = admin and solicitud.estado == EstadoSolicitud.RECHAZADA
    return solicitudes


# ----------------------------------------------------------------------
# Alta desde la tabla (solo NCargo)
# ----------------------------------------------------------------------

def _definicion_o_none(clave):
    if not clave:
        return None
    try:
        return definicion_de(clave)
    except OperacionDesconocida:
        return None


def _contexto_campo_registro(definicion, registro_seleccionado=''):
    """Contexto del selector «Registro a modificar», compartido por las dos vistas que
    lo pintan: la carga inicial del modal y el refresco por HTMX al cambiar de operación.

    Mantenerlo en un solo sitio evita que las dos vistas calculen `necesita_registro` o
    las opciones de forma distinta y acaben mostrando algo inconsistente.
    """
    from solicitudes.operaciones import opciones_de_registro
    return {
        'necesita_registro': definicion is not None and definicion['accion'] != AccionSolicitud.CREAR,
        'opciones_registro': opciones_de_registro(definicion),
        'registro_seleccionado': registro_seleccionado,
    }


@acceso_solicitudes
def campos_solicitud(request):
    """Fragmento HTMX con los campos reales de la operación elegida.

    Devuelve el ModelForm del módulo correspondiente, de modo que el Moderador rellene
    exactamente los mismos campos, con las mismas etiquetas y validaciones, que rellenaría
    un Administrador creando el registro directamente. Además de refrescar los campos,
    esta misma respuesta actualiza — fuera de banda — las opciones del selector «Registro
    a modificar», que dependen de qué operación se acaba de elegir.
    """
    clave = (request.GET.get('operacion') or '').strip()
    pk = (request.GET.get('registro') or '').strip()
    definicion = _definicion_o_none(clave)

    objeto = None
    if definicion is not None and definicion['accion'] != AccionSolicitud.CREAR and pk:
        objeto = definicion['modelo'].objects.filter(pk=pk).first()

    formulario = None
    if definicion is not None and (definicion['accion'] == AccionSolicitud.CREAR or objeto is not None):
        # Solo se construye el formulario cuando hay algo concreto que editar (o se está
        # creando). Si la operación es «Editar» y aún no se eligió registro, mostrar un
        # NCargoForm vacío se confundiría con un alta: la plantilla pinta en su lugar un
        # aviso de «seleccione un registro».
        formulario = serializacion.construir_formulario(
            definicion['form'], instancia=objeto,
            form_kwargs=form_kwargs_de(definicion, request.user))

    contexto = {'form_operacion': formulario, 'definicion': definicion}
    contexto.update(_contexto_campo_registro(definicion, pk))
    return render(
        request, 'pages/solicitudes/partials/respuesta_campos_solicitud.html', contexto)


@acceso_solicitudes
def crear_solicitud(request):
    """Modal de «Añadir Solicitud». Solo cubre las operaciones marcadas `desde_tabla`."""
    if request.method != 'POST':
        contexto = {'form': SolicitudDesdeTablaForm()}
        contexto.update(_contexto_campo_registro(None))
        return render(request, 'pages/solicitudes/add_solicitud.html', contexto)

    cabecera = SolicitudDesdeTablaForm(request.POST)
    formulario_operacion = None
    definicion = _definicion_o_none(request.POST.get('operacion'))

    if cabecera.is_valid():
        objeto = cabecera.objeto_seleccionado
        formulario_operacion = serializacion.construir_formulario(
            definicion['form'], instancia=objeto, datos=request.POST,
            form_kwargs=form_kwargs_de(definicion, request.user))

        if formulario_operacion.is_valid():
            try:
                servicios.crear_solicitud(
                    operacion=cabecera.cleaned_data['operacion'],
                    usuario=request.user,
                    formulario=formulario_operacion,
                    objeto=objeto,
                    motivo=cabecera.cleaned_data['motivo'])
            except servicios.ErrorDeSolicitud as error:
                return _repintar_alta(request, cabecera, formulario_operacion,
                                      definicion, str(error))
            from progreso.servicios import completar_tarea
            completar_tarea(request.user, 'primera_solicitud_enviada')
            return _respuesta_htmx('Solicitud enviada. Un Administrador la revisará.')

    return _repintar_alta(request, cabecera, formulario_operacion, definicion)


def _repintar_alta(request, cabecera, formulario_operacion, definicion, error=None):
    """Devuelve el modal con los errores, conservando lo que el usuario ya escribió."""
    contexto = {
        'form': cabecera,
        'form_operacion': formulario_operacion,
        'definicion': definicion,
        'error_general': error,
    }
    contexto.update(_contexto_campo_registro(definicion, request.POST.get('registro', '')))
    return render(request, 'pages/solicitudes/add_solicitud.html', contexto,
                 status=422 if error is None else 200)


# ----------------------------------------------------------------------
# Edición y retirada por el Moderador
# ----------------------------------------------------------------------

@acceso_solicitudes
def editar_solicitud(request, pk):
    """El Moderador autor rehace su propuesta mientras nadie la esté revisando."""
    solicitud = _solicitud_visible(request, pk)

    if not solicitud.puede_editarla(request.user):
        mensaje = (f'{solicitud.bloqueada_por_nombre} está revisando esta solicitud. '
                   'No puede modificarla en este momento.') if solicitud.bloqueada else (
            'Esta solicitud ya no se puede modificar.')
        if _es_fragmento(request):
            return JsonResponse({'success': False, 'error_popup': mensaje}, status=403)
        messages.error(request, mensaje)
        return redirect('list_solicitudes')

    definicion = definicion_de(solicitud.operacion)
    form_kwargs = form_kwargs_de(definicion, request.user)

    if request.method == 'POST':
        formulario = serializacion.construir_formulario(
            definicion['form'], instancia=solicitud.objeto_afectado,
            datos=request.POST, form_kwargs=form_kwargs)
        if formulario.is_valid():
            try:
                servicios.actualizar_propuesta(
                    solicitud, request.user, formulario,
                    motivo=request.POST.get('motivo', solicitud.motivo))
            except servicios.ErrorDeSolicitud as error:
                # Típicamente: un Administrador empezó a revisarla entre que se cargó
                # esta pantalla y se pulsó Guardar.
                messages.error(request, str(error))
                return redirect('list_solicitudes')
            messages.success(request, 'Su solicitud se actualizó correctamente.')
            return redirect('ver_solicitud', pk=solicitud.pk)
    else:
        formulario = None

    contexto = _contexto_solicitud(solicitud, request.user, formulario, editable=True)
    contexto['modo'] = 'edicion'
    return render(request, 'pages/solicitudes/updt_solicitud.html', contexto)


@require_POST
@acceso_solicitudes
def eliminar_solicitud(request, pk):
    """Borrado físico: el Administrador elimina cualquiera, el Moderador retira la suya."""
    solicitud = _solicitud_visible(request, pk)
    descriptor = solicitud.descriptor
    try:
        servicios.eliminar(solicitud, request.user)
    except servicios.ErrorDeSolicitud as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'Solicitud eliminada: {descriptor}')
    return redirect(_volver_al_listado(request))


# ----------------------------------------------------------------------
# Revisión y decisión (solo Administrador)
# ----------------------------------------------------------------------

@solo_admin
def revisar_solicitud(request, pk):
    """Abre la revisión, bloquea la solicitud y pinta la comparación.

    Es una página completa, no un modal: son dos columnas de campos y necesita el ancho.
    """
    solicitud = _solicitud_visible(request, pk)
    try:
        solicitud = servicios.iniciar_revision(solicitud, request.user)
    except servicios.ErrorDeSolicitud as error:
        messages.error(request, str(error))
        return redirect('list_solicitudes')

    contexto = _contexto_solicitud(solicitud, request.user, editable=True)
    contexto['modo'] = 'revision'
    return render(request, 'pages/solicitudes/revisar.html', contexto)


@require_POST
@solo_admin
def aprobar_solicitud(request, pk):
    """Aplica el cambio con los valores que envía el Administrador.

    La vista no valida ni construye el formulario: eso ocurre dentro de
    `servicios.aprobar()`, porque tiene que pasar DESPUÉS de preparar la base de datos
    (desplazar posiciones de orden) y dentro de la misma transacción. Aquí solo se decide
    qué se le muestra al Administrador según el resultado.
    """
    solicitud = _solicitud_visible(request, pk)

    try:
        servicios.aprobar(solicitud, request.user, request.POST)
    except servicios.PropuestaInvalida as error:
        messages.error(
            request, 'No se pudo aprobar: revise los campos marcados en la propuesta.')
        return _repintar_revision(request, solicitud, error.formulario)
    except Exception as error:
        # Conflictos que solo aparecen al aplicar el cambio: una plaza que se llenó, el
        # registro borrado, una restricción de integridad. La transacción ya se deshizo,
        # así que la solicitud sigue pendiente y el Administrador puede corregir los
        # valores aquí mismo y reintentar.
        messages.error(request, f'No se pudo aprobar la solicitud: {error}')
        return _repintar_revision(request, solicitud)

    messages.success(request, f'Solicitud aprobada: {solicitud.descriptor}')
    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primera_solicitud_decidida')
    from ranking.models import Actividad
    from ranking.servicios import registrar_actividad
    registrar_actividad(request.user, Actividad.SOLICITUD_DECIDIDA, detalle=solicitud.descriptor)
    # Al Moderador que la envió le cuenta como "Solicitud aprobada".
    registrar_actividad(solicitud.solicitante, Actividad.SOLICITUD_APROBADA, detalle=solicitud.descriptor)
    return redirect(_volver_al_listado(request))


def _repintar_revision(request, solicitud, formulario=None, form_rechazo=None):
    """Vuelve a la pantalla de revisión conservando lo que escribió el Administrador."""
    solicitud.refresh_from_db()
    contexto = _contexto_solicitud(solicitud, request.user, formulario, editable=True)
    contexto['modo'] = 'revision'
    if form_rechazo is not None:
        contexto['form_rechazo'] = form_rechazo
    return render(request, 'pages/solicitudes/revisar.html', contexto, status=422)


@require_POST
@solo_admin
def rechazar_solicitud(request, pk):
    solicitud = _solicitud_visible(request, pk)
    formulario = MotivoDecisionForm(request.POST)

    if not formulario.is_valid():
        messages.error(request, 'Debe indicar el motivo del rechazo.')
        return _repintar_revision(request, solicitud, form_rechazo=formulario)

    try:
        servicios.rechazar(
            solicitud, request.user, formulario.cleaned_data['motivo_decision'])
    except servicios.ErrorDeSolicitud as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f'Solicitud rechazada: {solicitud.descriptor}')
        from progreso.servicios import completar_tarea
        completar_tarea(request.user, 'primera_solicitud_decidida')
        from ranking.models import Actividad
        from ranking.servicios import registrar_actividad
        registrar_actividad(request.user, Actividad.SOLICITUD_DECIDIDA, detalle=solicitud.descriptor)
    return redirect(_volver_al_listado(request))


@require_POST
@solo_admin
def cancelar_revision(request, pk):
    """Sale de la revisión sin decidir y sin guardar nada de lo escrito."""
    solicitud = _solicitud_visible(request, pk)
    try:
        servicios.cancelar_revision(solicitud, request.user)
    except servicios.ErrorDeSolicitud as error:
        messages.error(request, str(error))
    else:
        messages.info(
            request, 'Revisión cancelada. La solicitud vuelve a quedar en espera '
                     'y no se guardó ningún cambio.')
    return redirect(_volver_al_listado(request))


@require_POST
@solo_admin
def devolver_solicitud(request, pk):
    """Reabre una rechazada. Corrige un rechazo por error humano."""
    solicitud = _solicitud_visible(request, pk)
    try:
        servicios.devolver_a_espera(solicitud, request.user)
    except servicios.ErrorDeSolicitud as error:
        messages.error(request, str(error))
    else:
        messages.success(request, 'La solicitud volvió a quedar En Espera.')
    return redirect(_volver_al_listado(request))


# ----------------------------------------------------------------------
# Consulta
# ----------------------------------------------------------------------

@acceso_solicitudes
def ver_solicitud(request, pk):
    """Solo lectura. Es el destino del enlace «Abrir solicitud» de las notificaciones.

    Una solicitud ya aprobada o rechazada solo se puede consultar; una pendiente se
    muestra igual, sin acciones, para que el Moderador pueda repasar lo que envió.
    """
    solicitud = _solicitud_visible(request, pk)
    contexto = _contexto_solicitud(solicitud, request.user, editable=False)
    contexto['modo'] = 'lectura'
    contexto['puede_editar'] = solicitud.puede_editarla(request.user)
    contexto['puede_revisar'] = solicitud.puede_revisarla(request.user)
    return render(request, 'pages/solicitudes/ver_solicitud.html', contexto)


class SolicitudAccesoMixin(AccesoSolicitudesMixin):
    """Reservado para futuras vistas basadas en clase del módulo."""
    model = Solicitud


__all__ = [
    'lista_solicitudes', 'buscar_solicitudes', 'campos_solicitud', 'crear_solicitud',
    'editar_solicitud', 'eliminar_solicitud', 'revisar_solicitud', 'aprobar_solicitud',
    'rechazar_solicitud', 'cancelar_revision', 'devolver_solicitud', 'ver_solicitud',
    'EstadoSolicitud',
]
