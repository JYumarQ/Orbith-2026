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

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse

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
    formularios y no necesita pedirse permiso a sí mismo. Tampoco el Moderador con el
    permiso especial «Editar sin solicitud» (25-10-2026): guarda directamente y queda
    en Auditoría marcado «con permiso especial».
    """
    if not es_moderador(usuario):
        return False
    from usuarios.permisos_especiales import marcar_en_esta_peticion, por_permiso_especial
    if por_permiso_especial(usuario, 'editar_sin_solicitud'):
        marcar_en_esta_peticion('editar_sin_solicitud')
        return False
    return True


def _fuera_de_alcance(usuario, definicion, objeto, datos):
    """¿La Unidad Organizativa de `objeto`/`datos` no está entre las asignadas a
    `usuario`?

    Solo tiene sentido llamarla para un Moderador (ver `requiere_solicitud`): un
    Administrador no tiene restricción de UO. Si la operación no pertenece a ninguna
    unidad —el resolutor `unidad` de la definición devuelve `None`, como el nomenclador
    global de Cargos— no hay nada que restringir.

    Se comprueba aquí, en el único punto de desvío de TODAS las operaciones, y no en cada
    vista por separado: así protege también las que ya se piden hoy y las que se añadan
    al catálogo en el futuro, sin depender de que cada vista nueva recuerde añadir el
    chequeo.
    """
    unidad = definicion['unidad'](objeto, datos)
    if unidad is None:
        return False
    return not usuario.unidades.filter(pk=unidad.pk).exists()


def _solo_cambia_campos_libres(definicion, objeto, request):
    """¿El envío, comparado con el registro real, solo toca campos de `campos_libres`?

    Se valida con el ModelForm normal —NO el de propuesta (`form_de_propuesta`)—: ese
    deshabilita a nivel de Django cualquier campo cuyo widget ya nazca con `disabled` en
    `Meta.widgets` (ver `serializacion._widget_deshabilitado`), como `motivo` de
    `CAltaForm`, que solo se habilita por JavaScript cuando el tipo de contrato lo exige.
    Mirar el cambio a través del formulario de propuesta lo vería SIEMPRE como «sin
    cambios» —Django ignora el POST y usa el valor actual—, así que esta comprobación
    nunca podría activarse para ese campo. El ModelForm normal es, además, el mismo que
    usará `super().post()` para guardar de verdad si esta función devuelve `True`.

    Se valida sobre una COPIA releída de la base de datos, no sobre `objeto`: validar un
    ModelForm con `instance=` aplica los datos del formulario sobre esa instancia en
    memoria (`_post_clean`), y `objeto` todavía tiene que servir sin tocar para construir
    el formulario de propuesta si esta comprobación no autoriza el atajo.
    """
    campos_libres = set(definicion.get('campos_libres', ()))
    if not campos_libres or objeto is None:
        return False

    from solicitudes import serializacion

    form_kwargs = form_kwargs_de(definicion, request.user)
    originales = serializacion.capturar(objeto, definicion['form'], form_kwargs=form_kwargs)

    copia = type(objeto)._default_manager.get(pk=objeto.pk)
    formulario = serializacion.construir_formulario(
        definicion['form'], instancia=copia, datos=request.POST, form_kwargs=form_kwargs)
    if not formulario.is_valid():
        return False

    propuestos = serializacion.serializar(formulario)
    cambiados = serializacion.comparar(originales, propuestos)
    # Restringido a los campos que el ModelForm realmente persiste (`Meta.fields`).
    # `CAltaForm` también declara campos puramente visuales que nunca se guardan —`rol`
    # y `grupo_escala` son texto de solo lectura derivado del cargo, `funcionario` y
    # `designado` son casillas sin campo en el modelo desde que se les quitó en
    # `contratos.0007_remove_calta_designado_remove_calta_funcionario`— y esos, al no
    # tener un valor inicial real, aparecerían como «cambiados» en CUALQUIER envío
    # aunque nada de lo que se guarda haya cambiado, bloqueando el atajo siempre.
    campos_persistidos = set(getattr(definicion['form']._meta, 'fields', ()) or ())
    cambiados &= campos_persistidos
    return bool(cambiados) and cambiados.issubset(campos_libres)


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

    # Un Moderador solo puede proponer sobre sus propias UO. Se comprueba ANTES de
    # construir la propuesta para que ni siquiera pueda intentarlo manipulando la
    # petición (URL, PK, o el desplegable de unidad en una creación).
    if _fuera_de_alcance(request.user, definicion, objeto, request.POST):
        return HttpResponseForbidden('Fuera de su Unidad Organizativa asignada.')

    if _solo_cambia_campos_libres(definicion, objeto, request):
        # Nada que proponer: se deja seguir como si fuera un Administrador, y
        # `super().post()` guarda el cambio con el ModelForm normal.
        return None

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

    El formulario de Contrato (`updt_contrato.html`), en cambio, NO envía por HTMX: lo
    hace con `$.ajax(..., dataType: 'json')` y su `success` solo mira `form_is_valid` /
    `success_url` — el mismo contrato que ya usa `ContratoUpdateView.form_valid()` para el
    Administrador. Sin `success_url` explícito el JS cae a su propio valor por defecto
    (`list_contrato`), así que no hace falta más para que el modal se cierre y navegue.

    Solo se llama tras crear la solicitud de verdad, así que también es el sitio
    de la Guía de Orbith para las solicitudes enviadas desde un formulario.
    """
    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primera_solicitud_enviada')

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
    """Espejo de `_respuesta_enviada` para el camino de error.

    La rama no-HTMX tenía que llevar `error_popup`: es la clave que el `success` de
    `updt_contrato.html` (y de cualquier otro formulario que envíe por `$.ajax` en lugar
    de HTMX, como `ContratoUpdateView.form_invalid`) usa para mostrar el SweetAlert. Sin
    ella, el JS entraba de todas formas por la rama de "formulario inválido" —porque
    `form_is_valid` es `False`— pero no encontraba ni `error_popup` ni `html_form`, así
    que el `.html(undefined)` de esa rama actúa como GETTER en jQuery (no como setter) y
    no hace absolutamente nada: ni popup, ni modal cerrado, ni pista de que la solicitud
    falló (p. ej. por «ya existe una solicitud pendiente sobre este registro»).
    """
    if request.headers.get('HX-Request'):
        respuesta = HttpResponse(status=204)
        respuesta['HX-Trigger'] = json.dumps({
            'closeModal': True,
            'showMessage': {'icon': 'error', 'text': mensaje},
        })
        return respuesta
    return JsonResponse({
        'status': 'error', 'form_is_valid': False, 'message': mensaje,
        'error_popup': mensaje,
    })


def desviar_borrado(vista, request):
    """Equivalente para las vistas de borrado, que no usan formulario ni `form_valid()`.

    Se llama al principio de su `post()`, antes de tocar el registro.
    """
    if not requiere_solicitud(request.user):
        return None

    clave = clave_para(vista.model, AccionSolicitud.ELIMINAR)
    if clave is None:
        return None

    definicion = definicion_de(clave)
    objeto = vista.get_object()

    if _fuera_de_alcance(request.user, definicion, objeto, None):
        return HttpResponseForbidden('Fuera de su Unidad Organizativa asignada.')

    try:
        servicios.crear_solicitud(
            operacion=clave,
            usuario=request.user,
            formulario=None,
            objeto=objeto,
            motivo=request.POST.get(CAMPO_MOTIVO, ''))
    except servicios.ErrorDeSolicitud as error:
        return _respuesta_error(request, str(error))

    return _respuesta_enviada(
        request, 'Solicitud de eliminación enviada. Un Administrador la revisará.')
