from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from .forms import CargoPlantillaForm, DepartamentoForm, UnidadOrganizativaForm
from nomencladores.models import NCargo, NCausaAltaBaja, NTipoUnidadOrganizativa
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Case, When, Value, IntegerField, Q, ProtectedError, Count, RestrictedError, Sum, F
from django.db import transaction
from contratos.models import CAlta
from django.contrib.messages.views import SuccessMessageMixin
import json

# ------------------  CARGO PLANTILLA  ------------------

class CargoPlantillaListView(ListView):
    model = CargoPlantilla
    template_name = "pages/cargo/list_cargo.html"

    def get_queryset(self):
        if self.request.user.is_superuser:
            qs = CargoPlantilla.objects.all()
        else:
            qs = CargoPlantilla.objects.filter(
                departamento__unidad_organizativa__in=self.request.user.unidades.all()
            )

        dpto_id = self.kwargs.get('dpto_id')
        if dpto_id:
            qs = qs.filter(departamento__id=dpto_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CargoPlantillaForm()
        dpto_id = self.kwargs.get('dpto_id')
        if dpto_id:
            context['dpto'] = get_object_or_404(
                Departamento,
                id=dpto_id,
                **({} if self.request.user.is_superuser else
                   {'unidad_organizativa__in': self.request.user.unidades.all()})
            )
        return context


def search_cargos_view(request):
    query   = request.GET.get('filter_cargos', '')
    dpto_id = request.GET.get('dpto_id', None)

    if request.user.is_superuser:
        results = CargoPlantilla.objects.all()
    else:
        results = CargoPlantilla.objects.filter(
            departamento__unidad_organizativa__in=request.user.unidades.all()
        )

    if dpto_id:
        results = results.filter(departamento__id=dpto_id)

    if query:
        results = results.filter(
            Q(ncargo__descripcion__icontains=query) |
            Q(departamento__descripcion__icontains=query) |
            Q(departamento__unidad_organizativa__descripcion__icontains=query)
        )

    return render(request,
                  'pages/cargo/partials/filter_cargos_list.html',
                  {'object_list': results})


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


class CargoPlantillaCreateView(SuccessMessageMixin, CreateView):
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
        transaction.set_rollback(True)
        print("❌ ERROR DE VALIDACIÓN EN CARGO:", form.errors)
        return super().form_invalid(form)

class CargoPlantillaUpdateView(SuccessMessageMixin, UpdateView):
    model = CargoPlantilla
    form_class = CargoPlantillaForm
    template_name = 'pages/cargo/updt_cargo.html'
    success_url = reverse_lazy('gestor_plantilla')

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
        
        # 2. Guardar definitivamente en la base de datos
        cargo.save()

        # 3. La magia de HTMX para refrescar la columna de Cargos automáticamente
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            
            # Ajustamos el mensaje flotante (SweetAlert) dependiendo de si el rol era válido
            if rol_valido:
                mensaje = {'icon': 'success', 'text': 'Cargo actualizado correctamente'}
            else:
                mensaje = {'icon': 'warning', 'text': 'Guardado, pero debe seleccionar un rol para los cargos que no son cuadro'}

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
        transaction.set_rollback(True)
        return super().form_invalid(form)


class CargoPlantillaDeleteView(DeleteView):
    model = CargoPlantilla
    
    def post(self, request, *args, **kwargs):
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
            elif 'Solicitud' in error_msg:
                mensaje = "No se puede eliminar: Hay solicitudes pendientes para este cargo."
            else:
                mensaje = "No se puede eliminar: Está siendo utilizado en otros registros del sistema."

            return JsonResponse({
                'status': 'error', 
                'message': mensaje
            }, status=200)
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=200)

# ------------------  DEPARTAMENTOS  ------------------

class DepartamentoListView(ListView):
    model = Departamento
    template_name = "pages/dpto/list_dpto.html"

    def get_queryset(self):
        if self.request.user.is_superuser:
            qs = Departamento.objects.all()
        else:
            qs = Departamento.objects.filter(
                unidad_organizativa__in=self.request.user.unidades.all()
            )

        unidad_id = self.kwargs.get('unidad_id')
        if unidad_id:
            qs = qs.filter(unidad_organizativa__grupo_nomina=unidad_id)
        return qs.order_by('orden_informe', 'id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = DepartamentoForm()
        unidad_id = self.kwargs.get('unidad_id')
        if unidad_id:
            context['unidad'] = get_object_or_404(
                UnidadOrganizativa,
                grupo_nomina=unidad_id,
                **({} if self.request.user.is_superuser else
                   {'grupo_nomina__in': self.request.user.unidades.values_list('grupo_nomina', flat=True)})
            )
        return context


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


class DepartamentoCreateView(SuccessMessageMixin, CreateView):
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
        transaction.set_rollback(True)
        return super().form_invalid(form)

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
    
    

class DepartamentoUpdateView(SuccessMessageMixin, UpdateView):
    model = Departamento
    form_class = DepartamentoForm
    template_name = "pages/dpto/updt_dpto.html"
    success_url = reverse_lazy('gestor_plantilla')

    def post(self, request, *args, **kwargs):
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
        transaction.set_rollback(True)
        return super().form_invalid(form)

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
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
    
    

class DepartamentoDeleteView(DeleteView):
    model = Departamento

    def post(self, request, *args, **kwargs):
        try:
            self.get_object().delete()
            return JsonResponse({'status': 'ok', 'message': 'Departamento eliminado correctamente.'})
        except (ProtectedError, RestrictedError):
            return JsonResponse({'status': 'error', 'message': 'No se puede eliminar: Tiene cargos asociados.'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})


def search_dpto_view(request):
    query = request.GET.get('filter_dpto', '')
    unidad_id = request.GET.get('unidad_id', None)

    if request.user.is_superuser:
        results = Departamento.objects.all()
    else:
        results = Departamento.objects.filter(
            unidad_organizativa__in=request.user.unidades.all()
        )

    if unidad_id:
        results = results.filter(unidad_organizativa__grupo_nomina=unidad_id)

    if query:
        results = results.filter(
            Q(descripcion__icontains=query) |
            Q(unidad_organizativa__descripcion__icontains=query)
        )
    results = results.order_by('orden_informe', 'id')

    return render(request,
                  'pages/dpto/partials/filter_dptos_list.html',
                  {'object_list': results})


# ------------------  UNIDAD ORGANIZATIVA  ------------------

class UnidadOrganizativaListView(ListView):
    model = UnidadOrganizativa
    template_name = "pages/uniorg/list_uniorg.html"

    def get_queryset(self):
        if self.request.user.is_superuser:
            return UnidadOrganizativa.objects.all()
        return self.request.user.unidades.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = UnidadOrganizativaForm()
        return context


def search_unidades_views(request):
    query = request.GET.get('filter_unidad', '')
    if request.user.is_superuser:
        qs = UnidadOrganizativa.objects.all()
    else:
        qs = request.user.unidades.all()

    if query:
        qs = qs.filter(descripcion__icontains=query)

    return render(request,
                  'pages/uniorg/partials/filter_unidades_list.html',
                  {'object_list': qs})


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
        if request.POST.get('autoriza_desplazamiento') == 'true':
            orden = request.POST.get('orden_informe')
            if orden and orden.isdigit():
                with transaction.atomic():
                    # Empujamos +1 a todos los que estén de esa posición hacia abajo
                    UnidadOrganizativa.objects.filter(orden_informe__gte=int(orden)).update(
                        orden_informe=F('orden_informe') + 1
                    )
        return super().post(request, *args, **kwargs)

class UnidadOrganizativaUpdateView(SuccessMessageMixin, UpdateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = 'pages/uniorg/updt_uniorg.html'
    success_url = reverse_lazy('gestor_plantilla')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        padres_qs = UnidadOrganizativa.objects.filter(tipo__es_principal=True).exclude(pk=self.object.pk)
        context['tipos_info'] = json.dumps({t.id: {'es_subunidad': t.es_subunidad} for t in NTipoUnidadOrganizativa.objects.all()})
        context['padres_info'] = json.dumps({p.pk: p.grupo_nomina for p in padres_qs})
        return context
    
    def form_valid(self, form):
        self.object = form.save()
        
        if self.request.htmx:
            # 204 significa "Todo salió bien, no devuelvas HTML que rompa la pantalla"
            response = HttpResponse(status=204)
            # Aquí disparamos la recarga de la lista, cerramos el modal y mostramos el toast
            response['HX-Trigger'] = 'updateUnitList, closeModal, showMessage'
            return response
            
        return super().form_valid(form)
    
    def post(self, request, *args, **kwargs):
        self.object = self.get_object() # Capturamos qué unidad estamos editando
        if request.POST.get('autoriza_desplazamiento') == 'true':
            orden = request.POST.get('orden_informe')
            if orden and orden.isdigit():
                with transaction.atomic():
                    # 1. EL TRUCO DEL PARQUEO: Movemos la unidad actual a un "limbo" 
                    # para que no estorbe ni colisione cuando empujemos a los demás
                    self.object.orden_informe = 999999 
                    self.object.save(update_fields=['orden_informe'])
                    
                    # 2. Buscamos a todos los afectados y los ORDENAMOS DE MAYOR A MENOR
                    unidades_a_desplazar = UnidadOrganizativa.objects.filter(
                        orden_informe__gte=int(orden)
                    ).exclude(pk=self.object.pk).order_by('-orden_informe')
                    
                    # 3. Los movemos uno por uno de arriba hacia abajo
                    for u in unidades_a_desplazar:
                        u.orden_informe += 1
                        u.save(update_fields=['orden_informe'])
                        
        # 4. Al llamar a super(), el formulario tomará el "orden" del request 
        # y bajará a la unidad desde el 999999 a su asiento final correcto.
        return super().post(request, *args, **kwargs)

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
    if request.user.is_superuser:
        unidades = UnidadOrganizativa.objects.annotate(total_dptos=Count('departamentos'))
    else:
        unidades = request.user.unidades.annotate(total_dptos=Count('departamentos'))

    # 2. LÓGICA DE ORDENAMIENTO PERSONALIZADO (El "Peso" de la Unidad)
    # Asignamos: 1 (Principal), 3 (Temporal), 2 (Cualquier otra normal)
    unidades = unidades.annotate(
        jerarquia_visual=Case(
            When(tipo__es_principal=True, then=Value(1)),
            When(tipo__descripcion__icontains='temporal', then=Value(3)),
            default=Value(2),
            output_field=IntegerField()
        )
    )

    # 3. Control de visibilidad para el Gestor de Plantilla
    if hay_unidad_principal:
        # Si hay una unidad raíz, las subunidades solo se ven dentro del desplegable
        unidades = unidades.filter(padre__isnull=True)

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
    
    # Ordenamos primero por jerarquía (Para que la Principal siempre sea la reina) y luego por tu número
    unidades = unidades.order_by('jerarquia_visual', field)

    # 5. Respuestas HTMX o Render normal
    context = {'unidades': unidades, 'q': q}
    
    if request.htmx:
        return render(request, 'pages/plantilla/partials/lista_unidades_div.html', context)

    context['causas_baja'] = NCausaAltaBaja.objects.filter(alta=False)
    return render(request, 'pages/plantilla/gestor_plantilla.html', context)


# 2. COLUMNA 2 (DEPARTAMENTOS)
@login_required
def htmx_load_departamentos(request, unidad_id):
    unidad = get_object_or_404(UnidadOrganizativa, pk=unidad_id)
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

    return render(request, 'pages/plantilla/partials/lista_departamentos.html', {
        'departamentos': dptos,
        'unidad_seleccionada': unidad,
        'q': q
    })


# 3. COLUMNA 3 (CARGOS)
@login_required
def htmx_load_cargos(request, dpto_id):
    dpto = get_object_or_404(Departamento, pk=dpto_id)
    cargos = CargoPlantilla.objects.filter(departamento=dpto)

    q = request.GET.get('q')
    if q:
        cargos = cargos.filter(ncargo__descripcion__icontains=q)

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

    return render(request, 'pages/plantilla/partials/lista_cargos.html', {
        'cargos': cargos,
        'departamento_seleccionado': dpto,
        'q': q
    })


# 4. COLUMNA 4 (CONTRATOS)
@login_required
def htmx_load_contratos(request, cargo_id):
    cargo = get_object_or_404(CargoPlantilla, pk=cargo_id)
    contratos = CAlta.objects.filter(cargo=cargo).select_related('aspirante')

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

    return render(request, 'pages/plantilla/partials/lista_contratos.html', {
        'contratos': contratos,
        'cargo_seleccionado': cargo,
        'q': q
    })

def validar_orden_uniorg(request):
    orden = request.GET.get('orden')
    exclude_id = request.GET.get('exclude_id')
    
    if not orden or not orden.isdigit():
        return JsonResponse({'ocupado': False})
        
    qs = UnidadOrganizativa.objects.filter(orden_informe=int(orden))
    if exclude_id and exclude_id.isdigit():
        qs = qs.exclude(codigo_interno=int(exclude_id)) # Excluimos la propia unidad si estamos editando
        
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