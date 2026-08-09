"""Desvío de los formularios existentes hacia una solicitud.

Las operaciones sobre Departamento, Cargo Plantilla, Unidad Organizativa, Contrato y
Aspirante NO se piden desde la tabla de Solicitudes: se piden desde el formulario que ya
existe en su propio módulo. Cuando quien lo envía es un Moderador, el guardado no toca la
base de datos definitiva sino que crea una solicitud pendiente de aprobación.

**Proponer y ejecutar están completamente separados.** Cuando el Moderador envía, se
intercepta al principio del `post()` y su petición no llega a tocar la base de datos: ni
el guardado, ni el `UPDATE` de reordenación que estas vistas ejecutan antes incluso de
validar. Lo único que ocurre es que se registra la propuesta. El cambio real —guardar,
desplazar posiciones, aplicar el orden final— sucede solo cuando el Administrador aprueba,
en `solicitudes/servicios.py::aprobar()`, y con los valores que él haya dejado.

De ahí que el Moderador pueda proponer una posición de orden ya ocupada: al proponer no se
mueve nada, y el conflicto lo resuelve el Administrador al aprobar.

**Se ofrecen funciones, no mixins, y es una decisión deliberada.** Un mixin parece más
limpio, pero las vistas de Orbith definen su propio `post()` en la clase concreta, y ese
siempre gana al de cualquier base: el desvío no llegaría a ejecutarse nunca y el Moderador
seguiría guardando directamente, en silencio.

Para conectar una vista nueva basta una llamada al PRINCIPIO de su `post()`:

    class MiCreateView(CreateView):
        def post(self, request, *args, **kwargs):
            desvio = interceptar(self, request, AccionSolicitud.CREAR)
            if desvio is not None:
                return desvio
            ...  # el resto de la vista queda intacto

    class MiDeleteView(DeleteView):
        def post(self, request, *args, **kwargs):
            desvio = desviar_borrado(self, request)
            if desvio is not None:
                return desvio
            ...
"""

import json

from django.http import HttpResponse, JsonResponse

from solicitudes import servicios
from solicitudes.models import AccionSolicitud
from solicitudes.operaciones import (
    clave_para, definicion_de, form_de_propuesta, form_kwargs_de)
from solicitudes.permisos import es_moderador

#: Nombre del campo de motivo que se añade a los formularios desviados. Deliberadamente
#: distinto de `motivo` a secas: `CAlta` ya tiene un campo `motivo` (FK a
#: `NMotivoContrato`) y colisionarían en el mismo POST.
CAMPO_MOTIVO = 'motivo_solicitud'


def requiere_solicitud(usuario):
    """¿Los guardados de este usuario deben convertirse en solicitud?

    Solo el Moderador. El Administrador conserva el comportamiento normal de los
    formularios y no necesita pedirse permiso a sí mismo.
    """
    return es_moderador(usuario)


def interceptar(vista, request, accion):
    """Convierte el envío en una solicitud. Devuelve la respuesta, o None si no procede.

    Se llama al PRINCIPIO del `post()` de la vista, antes de cualquier escritura. Ese
    momento es deliberado: las vistas de Estructura Organizativa ejecutan un
    `UPDATE ... orden_informe + 1` sobre registros reales antes incluso de validar, y ese
    desplazamiento no debe ocurrir al proponer. Interceptando aquí, el camino del
    Moderador no llega a tocar la base de datos en ningún punto.

    Devolver None significa «sigue con tu comportamiento normal»: o quien envía es un
    Administrador, o esta operación no está en el catálogo aprobado por RRHH. Eso último
    es lo que mantiene el desvío acotado a la lista oficial en vez de convertir en
    solicitud cualquier cosa que toque un Moderador.
    """
    if not requiere_solicitud(request.user):
        return None

    clave = clave_para(vista.model, accion)
    if clave is None:
        return None

    definicion = definicion_de(clave)
    objeto = vista.get_object() if accion == AccionSolicitud.EDITAR else None

    # Formulario de PROPUESTA: valida las reglas de negocio pero omite las restricciones
    # que solo importan al persistir, porque aquí no se persiste nada. Ver
    # `solicitudes/serializacion.py::formulario_de_propuesta`.
    formulario = form_de_propuesta(definicion)(
        request.POST, instance=objeto, **form_kwargs_de(definicion, request.user))

    if not formulario.is_valid():
        # Se repinta con el flujo normal de la vista para que el Moderador vea los
        # errores en el mismo formulario de siempre.
        vista.object = objeto
        return vista.render_to_response(vista.get_context_data(form=formulario))

    try:
        servicios.crear_solicitud(
            operacion=clave,
            usuario=request.user,
            formulario=formulario,
            objeto=objeto,
            motivo=request.POST.get(CAMPO_MOTIVO, ''))
    except servicios.ErrorDeSolicitud as error:
        return _respuesta_error(request, str(error))

    return _respuesta_enviada(request)


def _respuesta_enviada(request, mensaje='Solicitud enviada. Un Administrador la revisará.'):
    """Respuesta de éxito con el mismo contrato que usan estas vistas al guardar.

    Las plantillas de Estructura Organizativa envían por HTMX y esperan un 204 con
    `HX-Trigger`; devolver otra cosa dejaría el modal abierto y la lista sin refrescar.
    """
    if request.headers.get('HX-Request'):
        respuesta = HttpResponse(status=204)
        respuesta['HX-Trigger'] = json.dumps({
            'closeModal': True,
            'updateDeptList': True,
            'updateUnitList': True,
            'updateCargoList': True,
            'showMessage': {'icon': 'info', 'text': mensaje},
        })
        return respuesta
    return JsonResponse({'status': 'ok', 'form_is_valid': True, 'message': mensaje})


def _respuesta_error(request, mensaje):
    if request.headers.get('HX-Request'):
        respuesta = HttpResponse(status=204)
        respuesta['HX-Trigger'] = json.dumps({
            'closeModal': True,
            'showMessage': {'icon': 'error', 'text': mensaje},
        })
        return respuesta
    return JsonResponse({'status': 'error', 'form_is_valid': False, 'message': mensaje})


def desviar_borrado(vista, request):
    """Equivalente para las vistas de borrado, que no usan formulario ni `form_valid()`.

    Se llama al principio de su `post()`, antes de tocar el registro.
    """
    if not requiere_solicitud(request.user):
        return None

    clave = clave_para(vista.model, AccionSolicitud.ELIMINAR)
    if clave is None:
        return None

    try:
        servicios.crear_solicitud(
            operacion=clave,
            usuario=request.user,
            formulario=None,
            objeto=vista.get_object(),
            motivo=request.POST.get(CAMPO_MOTIVO, ''))
    except servicios.ErrorDeSolicitud as error:
        return _respuesta_error(request, str(error))

    return _respuesta_enviada(
        request, 'Solicitud de eliminación enviada. Un Administrador la revisará.')
