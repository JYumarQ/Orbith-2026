from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect, HttpResponseNotAllowed, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, DeleteView, UpdateView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, ProtectedError, Value
from django.db.models.functions import Concat
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
from nomencladores.models import NProvincia

from .models import Aspirante
from .forms import AspiranteForm
from usuarios.decorators import write_required

ABR_PROVINCIAS = {
    'Isla de la Juventud': 'IJU',
    'Pinar del Río': 'PRI',
    'Artemisa': 'ART',
    'La Habana': 'HAB',
    'Mayabeque': 'MAY',
    'Matanzas': 'MAT',
    'Cienfuegos': 'CFG',
    'Villa Clara': 'VCL',
    'Sancti Spíritus': 'SSP',
    'Ciego de Ávila': 'CAV',
    'Camagüey': 'CMG',
    'Las Tunas': 'LTU',
    'Holguín': 'HOL',
    'Granma': 'GRA',
    'Santiago de Cuba': 'SCU',
    'Guantánamo': 'GTM'
}

# ----------------- LISTA -----------------
class AspiranteListView(ListView):
    model = Aspirante
    template_name = "pages/aspirante/list_aspir.html"

    def get_queryset(self):
        # FILTRO CORREGIDO
        qs = Aspirante.objects.filter(estado='ASPIRANTE')
        u = self.request.user
        if getattr(u, 'es_moderador', False):
            # Usamos getattr para evitar error de tipado en 'unidades'
            ids_permitidos = getattr(u, 'unidades').values_list('pk', flat=True)
            qs = qs.filter(unidad_organizativa_id__in=ids_permitidos)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        paginator = Paginator(qs, 8) # Por defecto 8
        page_obj = paginator.get_page(1)


        context['aspirantes'] = page_obj
        context['page_obj'] = page_obj
        context['current_page_size'] = '8'
        context['form'] = AspiranteForm(user=self.request.user)
        # Variable para controlar el botón "Nuevo" en el template
        context['es_baja_view'] = False 
        context['search_url'] = 'search_aspirantes'

        # --- PROCESAR SIGLAS DE PROVINCIAS ---
        provincias_raw = NProvincia.objects.all()
        provincias_list = []
        for p in provincias_raw:
            # Busca la sigla en el diccionario, si no existe usa las 3 primeras letras mayúsculas
            sigla = ABR_PROVINCIAS.get(p.nombre, p.nombre[:3].upper())
            provincias_list.append({
                'id': p.pk,
                'nombre': p.nombre,
                'sigla': sigla
            })

        context['provincias_list'] = provincias_list

        context['provincias'] = NProvincia.objects.all()
        context['niveles_educ'] = Aspirante._meta.get_field('nivel_educ').choices
        return context

def search_aspirantes(request):
    # Obtenemos todos los parámetros
    query = request.GET.get('filter_aspirante', '').strip()
    provincia_id = request.GET.get('provincia')
    municipio_id = request.GET.get('municipio')
    nivel_educ = request.GET.get('nivel_educ')
    especialidad_id = request.GET.get('especialidad')

    # --- NUEVOS PARÁMETROS ---
    sexo = request.GET.get('sexo')
    raza = request.GET.get('raza')
    grado_cientifico = request.GET.get('grado_cientifico')

    # Filtro base
    qs = Aspirante.objects.filter(estado='ASPIRANTE')

    # Filtro de seguridad (Moderador)
    u = request.user
    if getattr(u, 'es_moderador', False):
        ids_permitidos = u.unidades.values_list('pk', flat=True)
        qs = qs.filter(unidad_organizativa_id__in=ids_permitidos)

    # --- APLICAR NUEVOS FILTROS ---
    if provincia_id:
        qs = qs.filter(provincia_id=provincia_id)
    
    if municipio_id:
        qs = qs.filter(municipio_id=municipio_id)
        
    if nivel_educ:
        qs = qs.filter(nivel_educ=nivel_educ)
        
    if especialidad_id:
        qs = qs.filter(especialidad_id=especialidad_id)

    if sexo:
        qs = qs.filter(sexo=sexo)
        
    if raza:
        qs = qs.filter(raza=raza)
        
    if grado_cientifico:
        qs = qs.filter(grado_cientifico=grado_cientifico)

    
    # Filtro de texto (Buscador Inteligente)
    if query:
        # Creamos un campo temporal 'nombre_completo' uniendo las partes
        qs = qs.annotate(
            nombre_completo=Concat('nombre', Value(' '), 'papellido', Value(' '), 'sapellido')
        ).filter(
            # Buscamos en el CI o en el nombre completo armado
            Q(doc_identidad__icontains=query) |
            Q(nombre_completo__icontains=query)
        )

    # --- INICIO LÓGICA DE PAGINACIÓN ---
    page_num = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', '8') # Recibe 8 o 10
    
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page_num)
        
    return render(request, 'pages/aspirante/partials/filter_aspirantes_list.html', {
        'aspirantes': page_obj,
        'page_obj': page_obj,
        'current_page_size': str(page_size),
        'search_url': 'search_aspirantes' # Necesario para que los botones sepan a dónde llamar
    })

# 3. NUEVO: Lista de Bajas (Reutiliza template list_aspir)
class BajaListView(ListView):
    model = Aspirante
    template_name = "pages/aspirante/list_aspir.html" # Reutilizamos el template

    def get_queryset(self):
        # SOLO BAJAS
        qs = Aspirante.objects.filter(estado='BAJA')
        u = self.request.user
        if getattr(u, 'es_moderador', False):
            ids_permitidos = getattr(u,'unidades').values_list('pk', flat=True)
            qs = qs.filter(unidad_organizativa_id__in=ids_permitidos)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        qs = self.get_queryset()
        paginator = Paginator(qs, 8) # Por defecto 8
        page_obj = paginator.get_page(1)

        context['aspirantes'] = page_obj
        context['page_obj'] = page_obj
        context['current_page_size'] = '8'

        context['form'] = AspiranteForm(user=self.request.user)
        # Ocultar botón nuevo
        context['es_baja_view'] = True
        context['titulo_pagina'] = 'Bajas' # Para cambiar título visualmente
        context['search_url'] = 'search_bajas'

        provincias_raw = NProvincia.objects.all()
        provincias_list = []
        for p in provincias_raw:
            sigla = ABR_PROVINCIAS.get(p.nombre, p.nombre[:3].upper())
            provincias_list.append({'id': p.pk, 'nombre': p.nombre, 'sigla': sigla})
        context['provincias_list'] = provincias_list
        context['niveles_educ'] = Aspirante._meta.get_field('nivel_educ').choices

        return context

# 4. NUEVO: Búsqueda de Bajas
def search_bajas(request):
    query = request.GET.get('filter_aspirante', '').strip() # Usamos mismo nombre de input para no tocar template
    qs = Aspirante.objects.filter(estado='BAJA')

    u = request.user
    if getattr(u, 'es_moderador', False):
        ids_permitidos = u.unidades.values_list('pk', flat=True)
        qs = qs.filter(unidad_organizativa_id__in=ids_permitidos)

    # Filtro de texto (Buscador Inteligente)
    if query:
        # Creamos un campo temporal 'nombre_completo' uniendo las partes
        qs = qs.annotate(
            nombre_completo=Concat('nombre', Value(' '), 'papellido', Value(' '), 'sapellido')
        ).filter(
            # Buscamos en el CI o en el nombre completo armado
            Q(doc_identidad__icontains=query) |
            Q(nombre_completo__icontains=query)
        )
    # --- INICIO LÓGICA DE PAGINACIÓN ---
    page_num = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', '8') # Recibe 8 o 10
    
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page_num)

    return render(request, 'pages/aspirante/partials/filter_aspirantes_list.html', {
        'aspirantes': page_obj,
        'page_obj': page_obj,
        'current_page_size': str(page_size),
        'search_url': 'search_aspirantes' # Necesario para que los botones sepan a dónde llamar
    })

# 5. MODIFICAR: Validación con mensajes específicos
def validar_datos_aspirante(request):
    ci = request.GET.get('doc_identidad', None)
    movil = request.GET.get('movil', None)
    aspirante_id = request.GET.get('aspirante_id', None)
    
    data = {
        'ci_existe': False,
        'ci_error_msg': '', # Nuevo campo para mensaje específico
        'movil_existe': False
    }

    if ci:
        qs = Aspirante.objects.filter(doc_identidad=ci)
        if aspirante_id:
            qs = qs.exclude(pk=aspirante_id)
        
        if qs.exists():
            data['ci_existe'] = True
            persona = qs.first()
            # Mensajes personalizados según estado (Verificamos que persona no sea None)
            if persona and persona.estado == 'ACTIVO':
                data['ci_error_msg'] = 'El CI ya está asociado a un trabajador de la Empresa (ACTIVO).'
            elif persona and persona.estado == 'BAJA':
            
                data['ci_error_msg'] = 'El CI pertenece a una persona en BAJA.'
            else:
                data['ci_error_msg'] = 'El CI ya existe en el registro de ASPIRANTES.'

    if movil:
        qs = Aspirante.objects.filter(movil_personal=movil) # Ojo: validar nombre exacto campo movil vs movil_personal
        if aspirante_id:
            qs = qs.exclude(pk=aspirante_id)
        if qs.exists():
            data['movil_existe'] = True

    return JsonResponse(data)



# ----------------- CREAR -----------------
@method_decorator(write_required, name='dispatch')
class AspiranteCreateView(CreateView):
    model = Aspirante
    form_class = AspiranteForm
    template_name = "pages/aspirante/add_aspir.html"
    success_url = reverse_lazy('list_aspir')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user   # pasar user al form (para limitar UO si es moderador)
        return kwargs

    def form_invalid(self, form):
        # útil en desarrollo
        print("Errores del formulario:", form.errors)
        return super().form_invalid(form)

    def form_valid(self, form):
        u = self.request.user
        # Moderador: solo en sus UO
        if getattr(u, 'es_moderador', False):
            permitidas = set(getattr(u, 'unidades').values_list('pk', flat=True))
            if not form.instance.unidad_organizativa_id:
                form.add_error('unidad_organizativa', 'Debe seleccionar una UO.')
                return self.form_invalid(form)
            if form.instance.unidad_organizativa_id not in permitidas:
                return HttpResponseForbidden("Fuera de su UO asignada.")
        self.object = form.save(commit=False)
        nombre = self.object.nombre
        messages.success(self.request, f'Aspirante "{nombre}" ha sido creado correctamente.')
        return super().form_valid(form)


# ----------------- EDITAR -----------------
@method_decorator(write_required, name='dispatch')
class AspiranteUpdateView(UpdateView):
    model = Aspirante
    form_class = AspiranteForm
    template_name = "pages/aspirante/updt_aspir.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.request.GET.get('next', '')
        return context

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        return next_url or reverse_lazy('list_aspir')

    def form_valid(self, form):
        aspirante = form.save()
        messages.success(self.request, f'Datos de "{aspirante.nombre}" actualizados correctamente (CI: {aspirante.doc_identidad}).')
        return HttpResponseRedirect(self.get_success_url())

        # Lógica de especialidad según nivel educativo
        if aspirante.nivel_educ not in ['NS', 'MS', 'TM']:
            aspirante.especialidad = None
        if aspirante.nivel_educ == 'NS' and not aspirante.especialidad:
            messages.warning(self.request, 'Debe seleccionar una especialidad si el nivel educativo es Nivel Superior')
        else:
            messages.success(self.request, f'Aspirante "{aspirante.nombre}" ha sido actualizado correctamente.')
        # Moderador: solo edición en sus UO
        u = self.request.user
        if getattr(u, 'es_moderador', False):
            permitidas = set(getattr(u, 'unidades').values_list('pk', flat=True))
            if aspirante.unidad_organizativa_id not in permitidas:
                return HttpResponseForbidden("Fuera de su UO asignada.")

        form.instance = aspirante
        return super().form_valid(form)


# ----------------- BORRAR -----------------
@method_decorator(write_required, name='dispatch')
class AspiranteDeleteView(DeleteView):
    model = Aspirante
    http_method_names = ['post']  # SOLO POST

    def post(self, request, *args, **kwargs):
        aspirante = get_object_or_404(Aspirante, pk=kwargs['pk'])
        
        # Moderador: solo en sus UO
        if getattr(request.user, 'es_moderador', False):
            permitidas = set(getattr(request.user, 'unidades').values_list('pk', flat=True))
            uo_id = getattr(aspirante, 'unidad_organizativa_id')
            if uo_id not in permitidas:
                return HttpResponseForbidden("Fuera de su UO asignada.")
        
        try:
            nombre = aspirante.nombre  # Guardamos el nombre para el mensaje
            aspirante.delete()

            # --- MODIFICACIÓN AQUÍ ---
            # Si es HTMX, usamos un header para disparar el Toast en el cliente
            if request.headers.get('HX-Request'):
                # Devolvemos string vacío para borrar la fila + Header con el mensaje
                response = HttpResponse("", status=200)
                # 'showMessage' es un evento que escucharemos en JS
                response['HX-Trigger'] = f'{{"showMessage": "Aspirante \\"{nombre}\\" eliminado correctamente"}}'
                return response

            # Fallback normal
            messages.success(request, f'Aspirante "{nombre}" ha sido eliminado correctamente.')
            return HttpResponseRedirect(reverse('list_aspir'))

        except ProtectedError:
            # Si falla por integridad (tiene contrato u otros datos), avisamos al usuario
            messages.error(request, "No se puede eliminar el aspirante porque tiene contratos o datos asociados.")
            
            # Importante: Forzamos recarga (HX-Refresh) para que el usuario vea que la fila SIGUE ahí
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Refresh': 'true'})
            
            return HttpResponseRedirect(reverse('list_aspir'))
            
        except Exception as e:
            messages.error(request, f"Error desconocido al eliminar: {e}")
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Refresh': 'true'})
            return HttpResponseRedirect(reverse('list_aspir'))
        
        

    # Si alguien navega con GET a esta URL => 405
    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(['POST'])


