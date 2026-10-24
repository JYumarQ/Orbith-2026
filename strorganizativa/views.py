from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import CreateView, UpdateView, DeleteView
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from .forms import CargoPlantillaForm, DepartamentoForm, UnidadOrganizativaForm
from nomencladores.models import NCargo, NCausaAltaBaja, NTipoUnidadOrganizativa
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.contrib import messages
from django.db.models import Q, ProtectedError, Count, Prefetch, RestrictedError, Sum, F
from django.db import transaction
from contratos.models import CAlta
from django.contrib.messages.views import SuccessMessageMixin
from core.mixins import (AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin,
                         MotivoDeCambioMixin, VolverAlOrigenMixin)
# Cierra al Observador TODA vista que escriba. Va como primera base de cada clase
# para que su `dispatch` corte antes que el de cualquier otro mixin, y responde
# JSON cuando la petición es HTMX/AJAX: el Gestor de Plantilla habla por JSON y
# un 403 en texto plano se vería como una pantalla rota, no como un aviso.
from usuarios.mixins import RequiereEdicionMixin
from .permisos import cargos_visibles, departamentos_visibles, unidades_visibles
# Convierten el guardado en una solicitud cuando quien envía el formulario es un
# Moderador; devuelven None (y la vista sigue como siempre) para un Administrador.
# Ver `solicitudes/integracion.py`.
from cierres import integracion as integracion_cierres
from solicitudes.integracion import desviar_borrado, interceptar
from solicitudes.models import AccionSolicitud
import json

# ------------------  CARGO PLANTILLA  ------------------


def cargar_cargos(request):
    id_dpto = request.GET.get('departamento')
    if id_dpto and id_dpto.isdigit():
        if request.user.is_superuser:
            cargos = CargoPlantilla.objects.filter(departamento_id=id_dpto)
        else:
            cargos = CargoPlantilla.objects.filter(
                departamento_id=id_dpto,
                departamento__unidad_organizativa__in=request.user.unidades.all()
            )
    else:
        cargos = CargoPlantilla.objects.none()
    return render(request,
                  'pages/cargo/partials/cargos_opt.html',
                  {'cargos': cargos})


def get_cat_ocup_from_ncargo(request):
    """API para obtener categoría y grupo escala al seleccionar un cargo"""
    cargo_id = request.GET.get('id')
    try:
        cargo = NCargo.objects.select_related('grupo_escala').get(id=cargo_id)
        return JsonResponse({
            'cat_ocupacional': cargo.cat_ocupacional,
            'grupo_escala': cargo.grupo_escala.nivel  # Devolvemos el nivel (ej. "XI")
        })
    except NCargo.DoesNotExist:
        return JsonResponse({'error': 'Cargo no encontrado'}, status=400)


class CargoPlantillaCreateView(RequiereEdicionMixin, SuccessMessageMixin, CreateView):
    model = CargoPlantilla
    form_class = CargoPlantillaForm
    template_name = "pages/cargo/add_cargo.html"
    success_url = reverse_lazy('gestor_plantilla')

    def get_initial(self):
        """Pre-carga datos solo en la petición inicial (GET)"""
        initial = super().get_initial()
        dpto_id = self.request.GET.get('departamento')
        if dpto_id:
            dpto = get_object_or_404(Departamento, pk=dpto_id)
            initial['departamento'] = dpto
            initial['unidad'] = dpto.unidad_organizativa
        return initial

    def get_context_data(self, **kwargs):
        """
        BEST PRACTICE: Inyectar los objetos visuales (Unidad/Depto) en el contexto
        tanto en GET (carga inicial) como en POST (recarga por error).
        Esto evita que los campos readonly se queden en blanco al fallar.
        """
        context = super().get_context_data(**kwargs)
        # Buscamos el ID en el POST (si hubo error) o en el GET (si es nuevo)
        dpto_id = self.request.POST.get('departamento') or self.request.GET.get('departamento')
        
        if dpto_id:
            try:
                dpto = Departamento.objects.get(pk=dpto_id)
                context['dpto_visual'] = dpto
                context['unidad_visual'] = dpto.unidad_organizativa
            except Departamento.DoesNotExist:
                pass
        return context

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateCargoList': True,
                'updateDeptList': True,
                'showMessage': {'icon': 'success', 'text': 'Cargo creado correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)
    
    def post(self, request, *args, **kwargs):
        # Un Moderador no ejecuta nada: registra la propuesta y sale. Va lo primero
        # porque el desplazamiento de abajo escribe en la base de datos antes incluso de
        # validar, y eso no debe ocurrir al proponer.
        desvio = interceptar(self, request, AccionSolicitud.CREAR)
        if desvio is not None:
            return desvio

        # Desplazamiento y guardado en UNA sola transacción, para que la
        # restricción diferida se compruebe una única vez al confirmar.
        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                departamento_id = request.POST.get('departamento')
                if orden and orden.isdigit() and departamento_id and departamento_id.isdigit():
                    # Liberamos la posición ANTES de que Django valide la unicidad
                    CargoPlantilla.objects.filter(
                        departamento_id=int(departamento_id),
                        orden_informe__gte=int(orden)
                    ).update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # El formulario no es válido: deshacemos el desplazamiento aplicado en post()
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta

class CargoPlantillaUpdateView(MotivoDeCambioMixin, RequiereEdicionMixin, SuccessMessageMixin, AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = CargoPlantilla
    form_class = CargoPlantillaForm
    template_name = 'pages/cargo/updt_cargo.html'
    template_name_pagina = 'pages/cargo/updt_cargo_pagina.html'
    url_por_defecto = reverse_lazy('gestor_plantilla')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # 1. Guardar temporalmente para evaluar tu validación de roles
        cargo = form.save(commit=False)
        
        # Evaluamos si el rol es correcto según la categoría ocupacional
        rol_valido = ((cargo.ncargo.cat_ocupacional in ('CDI', 'CEJ') and cargo.rol is None) or
                      (cargo.ncargo.cat_ocupacional not in ('CDI', 'CEJ') and cargo.rol is not None))
        
        # 2. Guardar definitivamente en la base de datos. Si el cambio (rol,
        # nomenclador o departamento) afecta a contratos, hace falta un motivo: se
        # anota en el histórico de cada trabajador (decisión de RRHH, 23-10-2026).
        def guardar():
            cargo.save()
            return cargo
        error = self.guardar_con_motivo(form, guardar)
        if error is not None:
            return error

        # 3. La magia de HTMX para refrescar la columna de Cargos automáticamente
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)

            # Ajustamos el mensaje flotante (SweetAlert) dependiendo de si el rol era válido
            if rol_valido:
                mensaje = {'icon': 'success', 'text': 'Cargo actualizado correctamente'}
            else:
                mensaje = {'icon': 'warning', 'text': 'Guardado, pero debe seleccionar un rol para los cargos que no son cuadro'}

            # Hay una redirección real posterior SOLO cuando se llegó desde una
            # advertencia (`next` presente): sin eso, el modal se cierra en la MISMA
            # página y un `messages.success()` aquí quedaría «colgado» en la sesión.
            if rol_valido and (self.request.POST.get('next') or self.request.GET.get('next')):
                messages.success(self.request, self.mensaje_de_guardado_exitoso('Cargo actualizado correctamente'))

            triggers = {
                'closeModal': True,
                'updateCargoList': True,
                'updateDeptList': True,
                'showMessage': mensaje
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
            
        return super().form_valid(form)
    
    def post(self, request, *args, **kwargs):
        # Ver la nota en `CargoPlantillaCreateView.post`.
        desvio = interceptar(self, request, AccionSolicitud.EDITAR)
        if desvio is not None:
            return desvio

        self.object = self.get_object()

        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                departamento_id = request.POST.get('departamento')
                if orden and orden.isdigit() and departamento_id and departamento_id.isdigit():
                    CargoPlantilla.objects.filter(
                        departamento_id=int(departamento_id),
                        orden_informe__gte=int(orden)
                    ).exclude(pk=self.object.pk).update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta


class CargoPlantillaDeleteView(RequiereEdicionMixin, DeleteView):
    """Eliminar cargo. Para un Moderador genera una solicitud de eliminación:
    el registro no se toca hasta que un Administrador la apruebe."""
    model = CargoPlantilla

    def post(self, request, *args, **kwargs):
        desvio = desviar_borrado(self, request)
        if desvio is not None:
            return desvio

        try:
            cargo = self.get_object()
            cargo.delete()
            messages.success(request, 'Cargo eliminado correctamente.')
            return JsonResponse({'status': 'ok', 'message': 'Cargo eliminado'}, status=200)

        except (ProtectedError, RestrictedError) as e:
            # Convertimos el error a texto para analizarlo
            error_msg = str(e)
            
            # Analizamos qué tabla está bloqueando el borrado
            if 'CBaja' in error_msg:
                mensaje = "No se puede eliminar: Este cargo tiene historial de Bajas asociadas. Borrarlo rompería el historial laboral."
            elif 'Contrato' in error_msg or 'calta' in error_msg:
                mensaje = "No se puede eliminar: Hay contratos activos asociados a este cargo."
            # Ya no se comprueba 'Solicitud': el modelo antiguo tenía una FK PROTECT a
            # CargoPlantilla, pero el actual apunta con una GenericForeignKey y no puede
            # bloquear un borrado. Una solicitud pendiente sobre un cargo que se elimina
            # queda huérfana y se detecta al aprobarla (`servicios.obtener_objeto`).
            else:
                mensaje = "No se puede eliminar: Está siendo utilizado en otros registros del sistema."

            return JsonResponse({
                'status': 'error', 
                'message': mensaje
            }, status=200)
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=200)

# ------------------  DEPARTAMENTOS  ------------------


def cargar_dptos(request):
    id_unidad = request.GET.get('unidad')
    if id_unidad and id_unidad.isdigit():
        if request.user.is_superuser:
            dptos = Departamento.objects.filter(unidad_organizativa_id=id_unidad)
        else:
            dptos = Departamento.objects.filter(
                unidad_organizativa_id=id_unidad,
                unidad_organizativa__in=request.user.unidades.all()
            )
        dptos = dptos.order_by('orden_informe', 'id')
    else:
        dptos = Departamento.objects.none()
    return render(request,
                  'pages/dpto/partials/dptos_opt.html',
                  {'dptos': dptos})


class DepartamentoCreateView(RequiereEdicionMixin, SuccessMessageMixin, CreateView):
    """Crear departamento. Para un Moderador se convierte en solicitud de aprobación."""
    model = Departamento
    form_class = DepartamentoForm
    template_name = "pages/dpto/add_dpto.html"
    success_url = reverse_lazy('gestor_plantilla')


    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def get_initial(self):
        initial = super().get_initial()
        unidad_id = self.request.GET.get('unidad')
        if unidad_id:
            initial['unidad_organizativa'] = unidad_id
        return initial

    def get_context_data(self, **kwargs):
        """
        Inyecta el objeto UnidadOrganizativa para poder mostrar su descripción
        en el campo visual de solo lectura. Se busca tanto en POST (re-render
        del modal si hay errores) como en GET (apertura normal del modal).
        """
        context = super().get_context_data(**kwargs)
        unidad_id = self.request.POST.get('unidad_organizativa') or self.request.GET.get('unidad')

        if unidad_id:
            try:
                context['unidad_visual'] = UnidadOrganizativa.objects.get(pk=unidad_id)
            except (UnidadOrganizativa.DoesNotExist, ValueError, TypeError):
                pass

        return context

    def post(self, request, *args, **kwargs):
        # Un Moderador no ejecuta nada: registra la propuesta y sale. Va lo primero
        # porque el desplazamiento de abajo escribe en la base de datos antes incluso de
        # validar, y eso no debe ocurrir al proponer.
        desvio = interceptar(self, request, AccionSolicitud.CREAR)
        if desvio is not None:
            return desvio

        # Todo dentro de UNA transacción: el desplazamiento y el guardado
        # deben confirmarse juntos para que la restricción diferida funcione.
        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                unidad_id = request.POST.get('unidad_organizativa')
                if orden and orden.isdigit() and unidad_id and unidad_id.isdigit():
                    # Liberamos la posición ANTES de que Django valide la unicidad
                    Departamento.objects.filter(
                        unidad_organizativa_id=int(unidad_id),
                        orden_informe__gte=int(orden)
                    ).update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # El formulario no es válido: deshacemos el desplazamiento aplicado en post()
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateDeptList': True,
                'updateUnitList': True,
                'showMessage': {'icon': 'success', 'text': 'Departamento creado correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)
    
    
class DepartamentoUpdateView(MotivoDeCambioMixin, RequiereEdicionMixin, SuccessMessageMixin, AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    """Editar departamento. Para un Moderador se convierte en solicitud de aprobación."""
    model = Departamento
    form_class = DepartamentoForm
    template_name = "pages/dpto/updt_dpto.html"
    template_name_pagina = "pages/dpto/updt_dpto_pagina.html"
    url_por_defecto = reverse_lazy('gestor_plantilla')

    def post(self, request, *args, **kwargs):
        # Ver la nota en `DepartamentoCreateView.post`.
        desvio = interceptar(self, request, AccionSolicitud.EDITAR)
        if desvio is not None:
            return desvio

        self.object = self.get_object()

        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                unidad_id = request.POST.get('unidad_organizativa')
                if orden and orden.isdigit() and unidad_id and unidad_id.isdigit():
                    Departamento.objects.filter(
                        unidad_organizativa_id=int(unidad_id),
                        orden_informe__gte=int(orden)
                    ).exclude(pk=self.object.pk).update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta

    def form_valid(self, form):
        error = self.guardar_con_motivo(form, form.save)
        if error is not None:
            return error
        if self.request.headers.get('HX-Request'):
            if self.request.POST.get('next') or self.request.GET.get('next'):
                messages.success(self.request, self.mensaje_de_guardado_exitoso('Departamento actualizado correctamente'))
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateDeptList': True,
                'updateUnitList': True,
                'showMessage': {'icon': 'success', 'text': 'Departamento actualizado correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)
    
    
class DepartamentoDeleteView(RequiereEdicionMixin, DeleteView):
    """Eliminar departamento. Para un Moderador genera una solicitud de eliminación:
    el registro no se toca hasta que un Administrador la apruebe."""
    model = Departamento

    def post(self, request, *args, **kwargs):
        desvio = desviar_borrado(self, request)
        if desvio is not None:
            return desvio

        try:
            self.get_object().delete()
            return JsonResponse({'status': 'ok', 'message': 'Departamento eliminado correctamente.'})
        except (ProtectedError, RestrictedError):
            return JsonResponse({'status': 'error', 'message': 'No se puede eliminar: Tiene cargos asociados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})


# ------------------  UNIDAD ORGANIZATIVA  ------------------


class UnidadOrganizativaCreateView(SuccessMessageMixin, CreateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = 'pages/uniorg/add_uniorg.html'
    success_url = reverse_lazy('gestor_plantilla') 

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        # Le enviamos al frontend qué tipos son subunidades y qué grupo de nómina tiene cada padre
        context['tipos_info'] = json.dumps({t.id: {'es_subunidad': t.es_subunidad} for t in NTipoUnidadOrganizativa.objects.all()})
        context['padres_info'] = json.dumps({p.pk: p.grupo_nomina for p in UnidadOrganizativa.objects.filter(tipo__es_principal=True)})
        return context

    def form_valid(self, form):
        # ... (Mantén tu código actual del form_valid)
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateUnitList': True,
                'showMessage': {'icon': 'success', 'text': 'Unidad creada correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)
    
    def post(self, request, *args, **kwargs):
        # Desplazamiento y guardado en UNA transacción (restricción diferida)
        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                padre_id = request.POST.get('padre')
                if orden and orden.isdigit():
                    qs = UnidadOrganizativa.objects.filter(orden_informe__gte=int(orden))
                    # El desplazamiento afecta SOLO a la rama correspondiente
                    if padre_id and padre_id.isdigit():
                        qs = qs.filter(padre_id=int(padre_id))
                    else:
                        qs = qs.filter(padre__isnull=True)
                    qs.update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # Formulario inválido: deshacemos el desplazamiento
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta

class UnidadOrganizativaUpdateView(MotivoDeCambioMixin, RequiereEdicionMixin, SuccessMessageMixin, AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = 'pages/uniorg/updt_uniorg.html'
    template_name_pagina = 'pages/uniorg/updt_uniorg_pagina.html'
    url_por_defecto = reverse_lazy('gestor_plantilla')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        padres_qs = UnidadOrganizativa.objects.filter(tipo__es_principal=True).exclude(pk=self.object.pk)
        context['tipos_info'] = json.dumps({t.id: {'es_subunidad': t.es_subunidad} for t in NTipoUnidadOrganizativa.objects.all()})
        context['padres_info'] = json.dumps({p.pk: p.grupo_nomina for p in padres_qs})
        return context
    
    def form_valid(self, form):
        error = self.guardar_con_motivo(form, form.save)
        if error is not None:
            return error

        if self.request.htmx:
            if self.request.POST.get('next') or self.request.GET.get('next'):
                messages.success(self.request, self.mensaje_de_guardado_exitoso('Unidad organizativa actualizada correctamente'))
            # 204 significa "Todo salió bien, no devuelvas HTML que rompa la pantalla"
            response = HttpResponse(status=204)
            # Aquí disparamos la recarga de la lista, cerramos el modal y mostramos el toast
            response['HX-Trigger'] = 'updateUnitList, closeModal, showMessage'
            return response

        return super().form_valid(form)
    
    def post(self, request, *args, **kwargs):
        # Un Moderador solo puede editar las unidades que tiene asignadas, y su envío se
        # convierte en solicitud. Crear y eliminar unidades no le está permitido en
        # absoluto (ver `strorganizativa/urls.py`).
        if getattr(request.user, 'es_moderador', False):
            if not request.user.unidades.filter(pk=self.get_object().pk).exists():
                return HttpResponseForbidden('Fuera de su Unidad Organizativa asignada.')

        desvio = interceptar(self, request, AccionSolicitud.EDITAR)
        if desvio is not None:
            return desvio

        self.object = self.get_object()

        with transaction.atomic():
            if request.POST.get('autoriza_desplazamiento') == 'true':
                orden = request.POST.get('orden_informe')
                padre_id = request.POST.get('padre')
                if orden and orden.isdigit():
                    qs = UnidadOrganizativa.objects.filter(
                        orden_informe__gte=int(orden)
                    ).exclude(pk=self.object.pk)

                    # El desplazamiento afecta SOLO a la rama correspondiente
                    if padre_id and padre_id.isdigit():
                        qs = qs.filter(padre_id=int(padre_id))
                    else:
                        qs = qs.filter(padre__isnull=True)

                    qs.update(orden_informe=F('orden_informe') + 1)

            return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        # OJO CON EL ORDEN. `set_rollback(True)` deja la transacción marcada y, a
        # partir de ese momento, PostgreSQL rechaza CUALQUIER consulta hasta que
        # se cierre el bloque `atomic`. Pero la respuesta de un formulario
        # inválido todavía tiene que construir su contexto y renderizar la
        # plantilla, y eso consulta la base (el panel de advertencias del
        # registro, `AdvertenciasDelRegistroMixin`). Marcando el rollback antes,
        # esa consulta reventaba con `TransactionManagementError` y el usuario
        # recibía un 500 en lugar del formulario con sus mensajes de error.
        # Por eso se renderiza primero —con la transacción todavía viva— y solo
        # después se marca el rollback, que es lo que deshace el desplazamiento
        # de `orden_informe` aplicado en `post()`.
        respuesta = super().form_invalid(form)
        if hasattr(respuesta, 'render') and not respuesta.is_rendered:
            respuesta.render()
        transaction.set_rollback(True)
        return respuesta

class UnidadOrganizativaDeleteView(DeleteView):
    model = UnidadOrganizativa
    
    # Estandarizado para devolver JSON al Gestor Visual
    def post(self, request, *args, **kwargs):
        try:
            self.get_object().delete()
            return JsonResponse({'status': 'ok', 'message': 'Unidad eliminada correctamente.'})
        except (ProtectedError, RestrictedError):
            return JsonResponse({'status': 'error', 'message': 'No se puede eliminar: Esta unidad tiene departamentos asociados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
    

# --- AGREGAR AL FINAL DE strorganizativa/views.py ---

# 1. VISTA CONTENEDOR Y COLUMNA 1 (UNIDADES)
@login_required
def gestor_plantilla_view(request):
    # 1. Verificamos si el sistema debe comportarse como un acordeón
    hay_unidad_principal = UnidadOrganizativa.objects.filter(tipo__es_principal=True).exists()

    # 2. Base de datos con optimización de conteo
    # El alcance por rol se decide en un único sitio (`strorganizativa/permisos.py`):
    # Administrador y Observador ven toda la empresa; el Moderador, solo sus
    # Unidades Organizativas. Antes aquí se comparaba `is_superuser`, y como el
    # Observador no lo es, el Gestor le salía vacío pese a ser un rol de consulta
    # global igual que en el Dashboard y en el listado de Contratos.
    unidades = unidades_visibles(request.user).annotate(total_dptos=Count('departamentos'))

    # `lista_unidades_div.html` recorre `u.tipo.*` y `u.direcciones_hijas.all/.count`
    # por cada fila: sin precargarlos Django lanzaba una consulta suelta por unidad
    # (42 consultas, 18 repetidas). El `select_related('tipo')` del prefetch evita que
    # las subunidades repitan el mismo problema un nivel más abajo.
    # `estado_cierre` alimenta el punto de color de cada fila (ver
    # `lista_unidades_div.html`). Sin el select_related aquí y en el prefetch de
    # las hijas, pintar el indicador costaría una consulta por unidad.
    unidades = unidades.select_related('tipo', 'estado_cierre').prefetch_related(
        Prefetch(
            'direcciones_hijas',
            queryset=UnidadOrganizativa.objects.select_related('tipo', 'estado_cierre').order_by('orden_informe', 'descripcion'),
        )
    )

    # 3. Control de visibilidad para el Gestor de Plantilla
    if hay_unidad_principal:
        # Si hay una unidad raíz, las subunidades solo se ven dentro del
        # desplegable de su padre... salvo que ese padre NO sea visible para
        # quien mira. Sin esa salvedad, una unidad que el usuario tiene derecho
        # a ver desaparecía del listado sin decir nada: la pantalla salía vacía
        # y no había manera de saber por qué. Un fallo así no deja rastro en
        # ningún log, solo se nota usando la aplicación.
        #
        # Con las reglas de asignación actuales ese dato ya no se puede crear
        # desde la aplicación —una subunidad solo se asigna a través de su
        # Unidad Principal, ver el bloque de `usuarios/forms.py`—, pero sí
        # puede entrar por un `loaddata` al restaurar un backup antiguo, que es
        # justo cuando menos ayuda una pantalla muda.
        #
        # Para el Administrador y el Observador la condición añadida no se
        # cumple nunca —lo ven todo, así que el padre siempre está entre lo
        # visible— y el listado sale exactamente igual que antes.
        ids_visibles = unidades_visibles(request.user).values_list('pk', flat=True)
        unidades = unidades.filter(
            Q(padre__isnull=True) | ~Q(padre_id__in=ids_visibles))

    # 4. Búsqueda y Ordenamiento
    q = request.GET.get('q')
    if q:
        unidades = unidades.filter(descripcion__icontains=q)

    # CAMBIO: Por defecto, que ordene usando tu campo numérico
    sort_by = request.GET.get('sort', 'orden_informe') 
    order = request.GET.get('order', 'asc')
    
    # Sintaxis limpia: Si piden alfabético usa descripción, si no, usa el orden numérico
    field = 'descripcion' if sort_by == 'alpha' else 'orden_informe'
    if order == 'desc': field = f'-{field}'
    
    # El orden lo decide el usuario mediante el Orden de Prioridad
    unidades = unidades.order_by(field)

    # 5. Acciones de Cierres disponibles para cada fila
    # Cuelga `acciones_cierre` de cada unidad y de cada subunidad. Lo resuelve en
    # dos consultas para todo el listado, no en una por fila.
    unidades = integracion_cierres.anotar_acciones(list(unidades), request.user)

    # 6. Respuestas HTMX o Render normal. `unidades_con_problemas`: triángulo rojo
    # en cascada (Fase 2): alguna subunidad, departamento, cargo o contrato por
    # debajo tiene un problema Crítico abierto en Subsanación.
    from subsanacion.indicadores import cascada_critica
    context = {'unidades': unidades, 'q': q,
               'unidades_con_problemas': cascada_critica()['unidades']}

    if request.htmx:
        return render(request, 'pages/plantilla/partials/lista_unidades_div.html', context)

    context['causas_baja'] = NCausaAltaBaja.objects.filter(alta=False)
    return render(request, 'pages/plantilla/gestor_plantilla.html', context)


# 2. COLUMNA 2 (DEPARTAMENTOS)
@login_required
def htmx_load_departamentos(request, unidad_id):
    # El id llega por la URL, así que se busca DENTRO del alcance del usuario y no
    # en toda la tabla: antes un Moderador podía leer la plantilla de cualquier
    # unidad ajena cambiando el número a mano. Un id fuera de alcance responde 404
    # —igual que uno inexistente—, de modo que la respuesta tampoco revela si esa
    # unidad existe. htmx no intercambia nada ante un 404, así que la columna se
    # queda como estaba en vez de pintar una página de error dentro del panel.
    unidad = get_object_or_404(unidades_visibles(request.user), pk=unidad_id)
    dptos = Departamento.objects.filter(unidad_organizativa=unidad)

    q = request.GET.get('q')
    if q:
        dptos = dptos.filter(descripcion__icontains=q)

    # ====================================================
    # 🔥 ORDENAMIENTO CORREGIDO
    # ====================================================
    sort_by = request.GET.get('sort', 'orden')  # 'orden' por defecto
    order = request.GET.get('order', 'asc')

    # Construir el orden según los parámetros
    if sort_by == 'alpha':
        field = 'descripcion'
    else:
        field = 'orden_informe'

    if order == 'desc':
        field = f'-{field}'

    # Anotaciones (agregar estadísticas)
    dptos = dptos.annotate(
        total_cargos=Count('cargoplantilla'),
        total_plazas=Sum('cargoplantilla__cant_aprobada'),
        activos=Count('cargoplantilla', filter=Q(cargoplantilla__activo=True)),
        inactivos=Count('cargoplantilla', filter=Q(cargoplantilla__activo=False))
    )

    # Aplicar orden
    if sort_by == 'alpha':
        dptos = dptos.order_by(field)
    else:
        # Si ordenamos por prioridad, usamos id como desempate
        dptos = dptos.order_by(field, 'id')

    from subsanacion.indicadores import cascada_critica
    return render(request, 'pages/plantilla/partials/lista_departamentos.html', {
        'departamentos': dptos,
        'unidad_seleccionada': unidad,
        'q': q,
        'departamentos_con_problemas': cascada_critica()['departamentos'],
    })


# 3. COLUMNA 3 (CARGOS)
@login_required
def htmx_load_cargos(request, dpto_id):
    # Mismo criterio que `htmx_load_departamentos`: el departamento tiene que
    # colgar de una unidad visible para quien pregunta.
    dpto = get_object_or_404(departamentos_visibles(request.user), pk=dpto_id)
    cargos = CargoPlantilla.objects.filter(departamento=dpto)

    q = request.GET.get('q')
    if q:
        cargos = cargos.filter(ncargo__descripcion__icontains=q)

    # Filtro «En plantilla / Fuera de plantilla» de la tarjeta de Cargos.
    # 'todos' (por defecto) no toca el queryset.
    filtro_plantilla = request.GET.get('plantilla', 'todos')
    if filtro_plantilla == 'si':
        cargos = cargos.filter(en_plantilla=True)
    elif filtro_plantilla == 'no':
        cargos = cargos.filter(en_plantilla=False)

    # Anotaciones para estadísticas
    cargos = cargos.select_related('ncargo', 'rol').annotate(
        count_ind=Count('calta', filter=Q(calta__tipo__ocupa_plaza=True, calta__aspirante__estado='ACTIVO')),
        count_cont=Count('calta', filter=Q(calta__tipo__ocupa_plaza=False, calta__aspirante__estado='ACTIVO'))
    )

    # 🔥 ORDENAMIENTO CORREGIDO (con soporte para 'orden', 'alpha', 'estado')
    sort_by = request.GET.get('sort', 'orden')  # 'orden' por defecto
    order = request.GET.get('order', 'asc')

    if sort_by == 'estado':
        if order == 'asc':
            cargos = cargos.order_by('activo', 'ncargo__descripcion')  # Inactivos primero
        else:
            cargos = cargos.order_by('-activo', 'ncargo__descripcion') # Activos primero
    elif sort_by == 'alpha':
        field = 'ncargo__descripcion'
        if order == 'desc':
            field = f'-{field}'
        cargos = cargos.order_by(field)
    else:  # 'orden' (prioridad)
        field = 'orden_informe'
        if order == 'desc':
            field = f'-{field}'
        cargos = cargos.order_by(field, 'id')  # desempate por id

    # Triángulos (Fase 2): rojo si el cargo o algo por debajo tiene un problema
    # Crítico; ámbar si el cargo tiene uno Alto propio.
    from subsanacion.indicadores import marcar, niveles_de_cargos
    cargos = list(cargos)
    niveles, propios = niveles_de_cargos([c.pk for c in cargos])
    cargos = marcar(cargos, niveles)
    for cargo in cargos:
        if cargo.pk in propios:
            cargo.url_problemas = reverse('subsanacion:problemas_registro', args=['cargo', cargo.pk])

    return render(request, 'pages/plantilla/partials/lista_cargos.html', {
        'cargos': cargos,
        'departamento_seleccionado': dpto,
        'q': q,
        'filtro_plantilla': filtro_plantilla,
    })


# 4. COLUMNA 4 (CONTRATOS)
@login_required
def htmx_load_contratos(request, cargo_id):
    # Es la columna más sensible de las tres: lista personas con nombre y
    # apellidos. Mismo acotado por alcance que las dos anteriores.
    cargo = get_object_or_404(cargos_visibles(request.user), pk=cargo_id)
    contratos = CAlta.objects.filter(cargo=cargo).select_related('aspirante')
    # La fecha mínima de la Baja de cada persona, en la misma consulta.
    contratos = CAlta.con_fecha_ultimo_movimiento(contratos)

    # Guía de Orbith: recorrer la plantilla hasta las personas de un cargo.
    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primera_exploracion_plantilla')

    q = request.GET.get('q')
    if q:
        contratos = contratos.filter(
            Q(aspirante__nombre__icontains=q) |
            Q(aspirante__papellido__icontains=q) |
            Q(aspirante__sapellido__icontains=q)
        )

    # Ordenamiento Dinámico
    sort_by = request.GET.get('sort', 'alpha') # alpha, salario, expediente
    order = request.GET.get('order', 'asc')

    if sort_by == 'expediente':
        # Ordenar por No. Expediente
        field = 'no_expediente'
        if order == 'desc': field = f'-{field}'
        contratos = contratos.order_by(field)
        
    elif sort_by == 'salario':
        lista_contratos = list(contratos)
        reverse = (order == 'desc')
        
        # CORRECCIÓN: Validamos si es ejecutable (método) o propiedad
        def get_salario(x):
            try:
                val = x.calcular_salario_escala() # Ejecutamos el método del modelo
                return float(val) if val is not None else 0.0
            except:
                return 0.0 # Si falla, lo mandamos al final (o principio) como 0

        lista_contratos.sort(key=get_salario, reverse=reverse)
        contratos = lista_contratos

    else:
        # Default: Alfabético por nombre
        field = 'aspirante__nombre'
        if order == 'desc': field = f'-{field}'
        contratos = contratos.order_by(field)

    # Triángulos (Fase 2): problemas Críticos (rojo) y Altos (ámbar) del contrato y
    # de la ficha del trabajador; al pulsarlo se abre su ventana.
    from subsanacion.indicadores import marcar, problemas_por_contrato
    contratos = list(contratos)
    contratos = marcar(contratos, problemas_por_contrato(contratos), 'contrato')

    return render(request, 'pages/plantilla/partials/lista_contratos.html', {
        'contratos': contratos,
        'cargo_seleccionado': cargo,
        'q': q
    })

def validar_orden_uniorg(request):
    orden = request.GET.get('orden')
    padre_id = request.GET.get('padre_id')
    exclude_id = request.GET.get('exclude_id')

    if not orden or not orden.isdigit():
        return JsonResponse({'ocupado': False})

    # La colisión se busca dentro de la misma rama:
    # si hay padre -> entre sus hijas; si no -> entre las unidades raíz
    if padre_id and padre_id.isdigit():
        qs = UnidadOrganizativa.objects.filter(padre_id=int(padre_id), orden_informe=int(orden))
    else:
        qs = UnidadOrganizativa.objects.filter(padre__isnull=True, orden_informe=int(orden))

    if exclude_id and exclude_id.isdigit():
        qs = qs.exclude(codigo_interno=int(exclude_id))

    colision = qs.first()
    if colision:
        return JsonResponse({
            'ocupado': True,
            'mensaje': f'Ocupado por "{colision.descripcion}"'
        })
    return JsonResponse({'ocupado': False})


def validar_orden_dpto(request):
    orden = request.GET.get('orden')
    unidad_id = request.GET.get('unidad_id')
    exclude_id = request.GET.get('exclude_id')

    if not orden or not orden.isdigit() or not unidad_id or not unidad_id.isdigit():
        return JsonResponse({'ocupado': False})

    # Buscamos colisión estrictamente dentro de la misma Unidad Organizativa
    qs = Departamento.objects.filter(unidad_organizativa_id=int(unidad_id), orden_informe=int(orden))
    if exclude_id and exclude_id.isdigit():
        qs = qs.exclude(id=int(exclude_id))

    colision = qs.first()
    if colision:
        return JsonResponse({
            'ocupado': True, 
            'mensaje': f'Ocupado por "{colision.descripcion}"'
        })
    return JsonResponse({'ocupado': False})

def validar_orden_cargo(request):
    orden = request.GET.get('orden')
    departamento_id = request.GET.get('departamento_id')
    exclude_id = request.GET.get('exclude_id')

    if not orden or not orden.isdigit() or not departamento_id or not departamento_id.isdigit():
        return JsonResponse({'ocupado': False})

    qs = CargoPlantilla.objects.filter(departamento_id=int(departamento_id), orden_informe=int(orden))
    if exclude_id and exclude_id.isdigit():
        qs = qs.exclude(pk=int(exclude_id))

    colision = qs.first()
    if colision:
        return JsonResponse({
            'ocupado': True,
            'mensaje': f'Ocupado por "{colision.ncargo.descripcion}"'
        })
    return JsonResponse({'ocupado': False})