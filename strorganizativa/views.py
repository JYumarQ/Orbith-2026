from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import CargoPlantilla, Departamento, UnidadOrganizativa
from .forms import CargoPlantillaForm, DepartamentoForm, UnidadOrganizativaForm
from nomencladores.models import NCargo
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse
from django.contrib import messages
from django.db.models import Q, ProtectedError # <--- IMPORTANTE

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
    cargo_id = request.GET.get('id')
    try:
        cargo = NCargo.objects.get(id=cargo_id)
        return JsonResponse({'cat_ocupacional': cargo.cat_ocupacional})
    except NCargo.DoesNotExist:
        return JsonResponse({'error': 'Cargo no encontrado'}, status=400)


class CargoPlantillaCreateView(CreateView):
    model = CargoPlantilla
    form_class = CargoPlantillaForm
    template_name = "pages/cargo/add_cargo.html"
    success_url = reverse_lazy('list_cargos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        return kwargs

    def form_valid(self, form):
        cargo = form.save(commit=False)
        if ((cargo.ncargo.cat_ocupacional in ('CDI', 'CDJ') and cargo.rol is None) or
            (cargo.ncargo.cat_ocupacional not in ('CDI', 'CDJ') and cargo.rol is not None)):
            messages.success(self.request, 'Cargo creado correctamente')
        else:
            messages.warning(self.request,
                             'Debe seleccionar un rol para los cargos que no son cuadro')
        cargo.save()
        return super().form_valid(form)


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
    def get(self, request, *args, **kwargs):
        cargo = get_object_or_404(CargoPlantilla, id=kwargs['pk'])
        
        # 1. Verificación Manual: ¿Tiene contratos (CAlta)?
        if cargo.calta_set.exists():
            messages.error(request, f"No se puede eliminar '{cargo.ncargo.descripcion}' porque tiene Contratos asociados")
            return redirect('list_cargos')

        # 2. Intento de borrado con red de seguridad (por si tiene Bajas u otras relaciones)
        try:
            cargo.delete()
            messages.success(request, 'Cargo eliminado correctamente')
        except ProtectedError:
            messages.error(request, f"No se puede eliminar '{cargo.ncargo.descripcion}' porque tiene dependencias asociadas")
        
        return redirect('list_cargos')


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


class DepartamentoCreateView(CreateView):
    model = Departamento
    form_class = DepartamentoForm
    template_name = "pages/dpto/add_dpto.html"
    success_url = reverse_lazy('list_dptos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request,
                         f'Departamento "{self.object.descripcion}" creado correctamente.')
        return response

    def get_success_url(self):
        return reverse('list_cargos_x_dpto', args=[self.object.pk])


class DepartamentoUpdateView(UpdateView):
    model = Departamento
    form_class = DepartamentoForm
    template_name = 'pages/dpto/updt_dpto.html'
    success_url = reverse_lazy('list_dptos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Departamento "{self.object.descripcion}" actualizado correctamente.')
        return response


class DepartamentoDeleteView(DeleteView):
    def get(self, request, *args, **kwargs):
        obj = get_object_or_404(Departamento, id=kwargs['pk'])
        
        # 1. Verificación Manual: ¿Tiene Cargos?
        if obj.cargoplantilla_set.exists():
            messages.error(request, f"No se puede eliminar '{obj.descripcion}' porque tiene Cargos asociados")
            return redirect('list_dptos')

        # 2. Intento de borrado
        try:
            obj.delete()
            messages.success(request, f'Departamento "{obj.descripcion}" eliminado correctamente.')
        except ProtectedError:
            messages.error(request, f"No se puede eliminar '{obj.descripcion}' porque tiene dependencias asociadas")
            
        return redirect('list_dptos')


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


class UnidadOrganizativaCreateView(CreateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = "pages/uniorg/add_uniorg.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request,
                         f'Unidad organizativa "{self.object.descripcion}" creada correctamente.')
        return response

    def get_success_url(self):
        return reverse('list_dpto_x_unidad', args=[self.object.pk])


class UnidadOrganizativaUpdateView(UpdateView):
    model = UnidadOrganizativa
    form_class = UnidadOrganizativaForm
    template_name = 'pages/uniorg/updt_uniorg.html'
    success_url = reverse_lazy('list_uniorg')


class UnidadOrganizativaDeleteView(DeleteView):
    def get(self, request, *args, **kwargs):
        obj = get_object_or_404(UnidadOrganizativa, grupo_nomina=kwargs['pk'])
        
        # 1. Verificación Manual: ¿Tiene Departamentos?
        if obj.departamento_set.exists():
            messages.error(request, f"No se puede eliminar '{obj.descripcion}' porque tiene Departamentos asociados")
            return redirect('list_uniorg')

        # 2. Intento de borrado
        try:
            obj.delete()
            messages.success(request, f'Unidad organizativa "{obj.descripcion}" eliminada correctamente.')
        except ProtectedError:
            messages.error(request, f"No se puede eliminar '{obj.descripcion}' porque tiene dependencias asociadas")
            
        return redirect('list_uniorg')