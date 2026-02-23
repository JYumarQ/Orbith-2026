from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from .forms import CargoPlantillaForm, DepartamentoForm, UnidadOrganizativaForm
from nomencladores.models import NCargo
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.db.models import Q, ProtectedError, Count, RestrictedError
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
                'showMessage': {'icon': 'success', 'text': 'Cargo creado correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)

    def form_invalid(self, form):
        # LOGGING PROFESIONAL: Esto imprimirá el error exacto en tu terminal (donde corre runserver)
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
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateCargoList': True,
                'showMessage': {'icon': 'success', 'text': 'Cargo actualizado correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)

class CargoPlantillaDeleteView(DeleteView):
    model = CargoPlantilla

    def post(self, request, *args, **kwargs):
        try:
            self.get_object().delete()
            return JsonResponse({'status': 'ok', 'message': 'Cargo eliminado correctamente.'})
        except (ProtectedError, RestrictedError) as e:
            error_msg = str(e)
            if 'CBaja' in error_msg:
                mensaje = "No se puede eliminar: Tiene historial de Bajas."
            elif 'Contrato' in error_msg or 'calta' in error_msg:
                mensaje = "No se puede eliminar: Hay contratos activos."
            else:
                mensaje = "No se puede eliminar: Está en uso en el sistema."
            return JsonResponse({'status': 'error', 'message': mensaje})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})


class CargoPlantillaUpdateView(UpdateView):
    model = CargoPlantilla
    form_class = CargoPlantillaForm
    template_name = 'pages/cargo/updt_cargo.html'
    success_url = reverse_lazy('list_cargos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        return kwargs

    def form_valid(self, form):
        cargo = form.save(commit=False)
        if ((cargo.ncargo.cat_ocupacional in ('CDI', 'CDJ') and cargo.rol is None) or
            (cargo.ncargo.cat_ocupacional not in ('CDI', 'CDJ') and cargo.rol is not None)):
            messages.success(self.request, 'Cargo actualizado correctamente')
        else:
            messages.warning(self.request,
                             'Debe seleccionar un rol para los cargos que no son cuadro')
        cargo.save()
        return super().form_valid(form)


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
        return qs

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
        """Pre-selecciona la unidad organizativa si viene en la URL"""
        initial = super().get_initial()
        unidad_id = self.request.GET.get('unidad') # Capturamos el ?unidad=ID
        if unidad_id:
            initial['unidad_organizativa'] = unidad_id
        return initial

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateDeptList': True, # <--- OJO: Trigger específico
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

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateDeptList': True,
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
    success_url = reverse_lazy('gestor_plantilla') # Fallback por si falla JS

    def form_valid(self, form):
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

class UnidadOrganizativaUpdateView(SuccessMessageMixin, UpdateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = 'pages/uniorg/updt_uniorg.html'
    success_url = reverse_lazy('gestor_plantilla')

    def form_valid(self, form):
        self.object = form.save()
        if self.request.headers.get('HX-Request'):
            response = HttpResponse(status=204)
            triggers = {
                'closeModal': True,
                'updateUnitList': True,
                'showMessage': {'icon': 'success', 'text': 'Unidad actualizada correctamente'}
            }
            response['HX-Trigger'] = json.dumps(triggers)
            return response
        return super().form_valid(form)

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
    # 1. Filtro base
    if request.user.is_superuser:
        unidades = UnidadOrganizativa.objects.annotate(total_dptos=Count('departamento'))
    else:
        unidades = request.user.unidades.annotate(total_dptos=Count('departamento'))

    # 2. Búsqueda
    q = request.GET.get('q')
    if q:
        unidades = unidades.filter(descripcion__icontains=q)

    # 3. Lógica de Ordenamiento (Columna 1)
    # Default: grupo_nomina (numérico)
    sort_by = request.GET.get('sort', 'grupo_nomina') 
    order = request.GET.get('order', 'asc')
    
    if sort_by == 'alpha':
        # Orden alfabético (descripcion)
        field = 'descripcion'
    else:
        # Por defecto numérico (grupo_nomina)
        field = 'grupo_nomina'
        
    if order == 'desc':
        field = f'-{field}'
        
    unidades = unidades.order_by(field)

    if request.htmx:
        return render(request, 'pages/plantilla/partials/lista_unidades_div.html', {
            'unidades': unidades, 'q': q
        })

    return render(request, 'pages/plantilla/gestor_plantilla.html', {
        'unidades': unidades
    })


# 2. COLUMNA 2 (DEPARTAMENTOS)
@login_required
def htmx_load_departamentos(request, unidad_id):
    unidad = get_object_or_404(UnidadOrganizativa, pk=unidad_id)
    dptos = Departamento.objects.filter(unidad_organizativa=unidad)

    q = request.GET.get('q')
    if q:
        dptos = dptos.filter(descripcion__icontains=q)

    # Ordenamiento
    sort_by = request.GET.get('sort', 'alpha')
    order = request.GET.get('order', 'asc')
    
    # En Dptos solo tenemos orden alfabético por ahora
    field = 'descripcion'
    if order == 'desc':
        field = '-descripcion'

    dptos = dptos.annotate(
        total_cargos=Count('cargoplantilla'),
        activos=Count('cargoplantilla', filter=Q(cargoplantilla__activo=True)),
        inactivos=Count('cargoplantilla', filter=Q(cargoplantilla__activo=False))
    ).order_by(field)

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

    cargos = cargos.select_related('ncargo', 'rol').annotate(
        count_ind=Count('calta', filter=Q(calta__tipo='IND')),
        count_cont=Count('calta', filter=~Q(calta__tipo='IND'))
    )

    # Ordenamiento Dinámico
    sort_by = request.GET.get('sort', 'alpha') # 'alpha' o 'estado'
    order = request.GET.get('order', 'asc')

    if sort_by == 'estado':
        # Activos primero (True > False en Python, pero queremos True primero en DESC)
        # En DB boolean: False=0, True=1.
        # ASC: Inactivo primero. DESC: Activo primero.
        if order == 'asc':
            cargos = cargos.order_by('activo', 'ncargo__descripcion') # Inactivos arriba
        else:
            cargos = cargos.order_by('-activo', 'ncargo__descripcion') # Activos arriba
    else:
        # Alfabético por nombre de cargo
        if order == 'desc':
            cargos = cargos.order_by('-ncargo__descripcion')
        else:
            cargos = cargos.order_by('ncargo__descripcion')

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