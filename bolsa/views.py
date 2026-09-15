from datetime import date

from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect, HttpResponseNotAllowed, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, DeleteView, UpdateView
from django.urls import reverse, reverse_lazy
from django.db.models import Q, ProtectedError, Value, RestrictedError, OuterRef, Subquery
from django.db.models.functions import Concat
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
from nomencladores.models import NProvincia

from django.views.decorators.cache import never_cache

from .models import Aspirante
from .forms import AspiranteForm
from usuarios.decorators import write_required
from core.mixins import AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin
# Convierte la eliminación en una solicitud cuando la pide un Moderador; devuelve None
# para el Administrador, que elimina directamente.
from solicitudes.integracion import desviar_borrado

def _anotar_baja_sin_datos(qs):
    """Marca cada Aspirante con si su BAJA más reciente es un registro "vacío"
    (sin cargo ni fecha_alta): el marcador que crea `contratos.models
    ._al_eliminar_movimiento` cuando se borra TODO el histórico de nómina de
    alguien desde el Admin de Django. No representa una baja real documentada,
    así que la plantilla la resalta en rojo para que no se confunda con una.
    """
    from contratos.models import CBaja
    ultima_baja = CBaja.objects.filter(aspirante_id=OuterRef('pk')).order_by('-fecha_baja', '-pk')
    return qs.annotate(
        ultima_baja_fecha_alta=Subquery(ultima_baja.values('fecha_alta')[:1]),
        ultima_baja_cargo_id=Subquery(ultima_baja.values('cargo_id')[:1]),
    )


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
        return Aspirante.objects.filter(estado='ASPIRANTE').order_by('-id')

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

@never_cache
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

    # Filtro base (Añadido ordenamiento cronológico por defecto)
    qs = Aspirante.objects.filter(estado='ASPIRANTE').order_by('-id')

    # Filtro de seguridad (Moderador)
    

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
        return _anotar_baja_sin_datos(Aspirante.objects.filter(estado='BAJA')).order_by('-id')

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
@never_cache
def search_bajas(request):
    query = request.GET.get('filter_aspirante', '').strip() # Usamos mismo nombre de input para no tocar template
    qs = _anotar_baja_sin_datos(Aspirante.objects.filter(estado='BAJA')).order_by('-id')

    

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
def _edad_desde_carnet(ci):
    """Fecha de nacimiento y edad que codifica un carnet, o `(None, None)`.

    Delega en `Aspirante._calcular_fecha_nacimiento` (el mismo método que usa el
    modelo al guardar y la regla ASP-001 de Subsanación) en vez de repetir aquí la
    regla del 7º dígito. Así el formulario muestra exactamente la edad que Orbith
    va a guardar, y no una segunda interpretación del carnet hecha en JavaScript.

    La edad se calcula igual que `Aspirante.get_edad`, pero sobre una fecha suelta:
    aquí todavía no existe ninguna instancia porque el aspirante se está creando.
    """
    fecha_nacimiento = Aspirante._calcular_fecha_nacimiento(ci)
    if fecha_nacimiento is None:
        return None, None

    hoy = date.today()
    edad = hoy.year - fecha_nacimiento.year - (
        (hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day)
    )
    return fecha_nacimiento, edad


def validar_datos_aspirante(request):
    ci = request.GET.get('doc_identidad', None)
    movil = request.GET.get('movil', None)
    serie = request.GET.get('serie', None)
    aspirante_id = request.GET.get('aspirante_id', None)
    
    data = {
        'ci_existe': False,
        'ci_error_msg': '', # Nuevo campo para mensaje específico
        'movil_existe': False,
        # La edad NO es un campo de la base de datos: cambia sola con el paso de los
        # días. Se deriva aquí del carnet y el formulario solo la pinta, de solo
        # lectura, para que el usuario confirme que tecleó bien el carnet.
        'edad': None,
        'fecha_nacimiento': '',
        'serie_existe': False,
        'serie_error_msg': '',
    }

    if ci:
        fecha_nacimiento, edad = _edad_desde_carnet(ci)
        if edad is not None:
            data['edad'] = edad
            data['fecha_nacimiento'] = fecha_nacimiento.strftime('%d/%m/%Y')

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

    if serie:
        # Se normaliza con el mismo método del modelo para que «ab12cd34e» y
        # «AB12CD34E» no se consideren series distintas al buscar el duplicado.
        serie_normalizada = Aspirante._normalizar_serie_ci(serie)
        if serie_normalizada:
            qs = Aspirante.objects.filter(serie_ci=serie_normalizada)
            if aspirante_id:
                qs = qs.exclude(pk=aspirante_id)
            persona = qs.first()
            if persona:
                data['serie_existe'] = True
                data['serie_error_msg'] = (
                    f'La serie ya está registrada a nombre de {persona} '
                    f'(CI {persona.doc_identidad}).')

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

    def form_valid(self, form):
        # 1. Pausamos el guardado para hacer las validaciones
        aspirante = form.save(commit=False)

        # 2. Lógica de especialidad según nivel educativo
        if aspirante.nivel_educ not in ['NS', 'MS', 'TM']:
            aspirante.especialidad = None
        if aspirante.nivel_educ == 'NS' and not aspirante.especialidad:
            messages.warning(self.request, 'Debe seleccionar una especialidad si el nivel educativo es Nivel Superior')

        # 3. Guardamos directamente
        aspirante.save()

        # ---> LA LÍNEA CLAVE PARA EVITAR EL ERROR <---
        self.object = aspirante

        from progreso.servicios import completar_tarea
        tarea = completar_tarea(self.request.user, 'primer_aspirante')
        if tarea:
            messages.info(self.request, f"🧭 Nuevo en tu Guía de Orbith: {tarea.titulo}")

        # 4. Cerramos el modal sin recargar página (HTMX)
        if self.request.headers.get('HX-Request'):
            import json
            from django.http import HttpResponse
            response = HttpResponse(status=204)

            # CORRECCIÓN: Mandamos un texto simple para que list_aspir.html no colapse
            response['HX-Trigger'] = json.dumps({
                'updateContratoList': '',
                'searchFilters': '',
                'closeModal': '',
                'showMessage': f'Datos de "{aspirante.nombre}" guardados correctamente.'
            })
            return response

        messages.success(self.request, f'Aspirante "{aspirante.nombre}" creado correctamente.')
        return HttpResponseRedirect(self.get_success_url())


# ----------------- EDITAR -----------------
@method_decorator(write_required, name='dispatch')
class AspiranteUpdateView(AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = Aspirante
    form_class = AspiranteForm
    template_name = "pages/aspirante/updt_aspir.html"
    template_name_pagina = "pages/aspirante/updt_aspir_pagina.html"
    url_por_defecto = reverse_lazy('list_aspir')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # 1. Pausamos el guardado para hacer las validaciones
        aspirante = form.save(commit=False)

        # 2. Lógica de especialidad según nivel educativo
        if aspirante.nivel_educ not in ['NS', 'MS', 'TM']:
            aspirante.especialidad = None
        if aspirante.nivel_educ == 'NS' and not aspirante.especialidad:
            messages.warning(self.request, 'Debe seleccionar una especialidad si el nivel educativo es Nivel Superior')

        # 3. Guardamos
        aspirante.save()
        self.object = aspirante # Por seguridad, actualizamos la instancia en la vista

        # 4. Retornamos usando el flujo normal de Django (Recarga la página)
        form.instance = aspirante
        mensaje = self.mensaje_de_guardado_exitoso(
            f'Datos de "{aspirante.nombre}" actualizados correctamente.')

        # Salvo cuando quien pregunta es una pantalla que NO quiere recargar.
        # El Gestor de Plantilla mantiene su estado (unidad, departamento y cargo
        # seleccionados) solo en el navegador: una recarga lo perdería y devolvería
        # al usuario al listado de aspirantes. Envía la petición por AJAX y se le
        # responde con JSON para que cierre el modal y refresque sus columnas.
        # El `messages.success` se omite en esa rama a propósito: no habrá ninguna
        # página nueva donde consumirlo y quedaría colgado en la sesión.
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            from django.http import JsonResponse
            return JsonResponse({'form_is_valid': True, 'mensaje': mensaje})

        messages.success(self.request, mensaje)
        return super().form_valid(form)


# ----------------- BORRAR -----------------
@method_decorator(write_required, name='dispatch')
class AspiranteDeleteView(DeleteView):
    """Eliminar un trabajador. Es el botón «Eliminar» de la Lista de Bajas, que RRHH
    llama «eliminar contrato»: borra la persona y con ella su historial.

    Para un Moderador genera una solicitud; el registro no se toca hasta que un
    Administrador la apruebe.
    """
    model = Aspirante
    http_method_names = ['post']  # SOLO POST

    def post(self, request, *args, **kwargs):
        aspirante = get_object_or_404(Aspirante, pk=kwargs['pk'])

        # Moderador: solo en sus UO. Se comprueba ANTES del desvío para que no pueda
        # siquiera solicitar la eliminación de alguien fuera de su alcance.
        if getattr(request.user, 'es_moderador', False):
            permitidas = set(getattr(request.user, 'unidades').values_list('pk', flat=True))
            uo_id = getattr(aspirante, 'unidad_organizativa_id')
            if uo_id not in permitidas:
                return HttpResponseForbidden("Fuera de su UO asignada.")

        desvio = desviar_borrado(self, request)
        if desvio is not None:
            return desvio

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

        except (ProtectedError, RestrictedError):
            # Si falla por protección (tiene contratos activos) o restricción (tiene historial de bajas)
            mensaje_amigable = (
                f'Acción denegada: No se puede eliminar a "{aspirante.nombre}" '
                f'porque tiene un historial de contratos o bajas asociado en el sistema. '
                f'Por normas de auditoría, este registro está protegido.'
            )
            messages.error(request, mensaje_amigable)
            
            # Importante: Forzamos recarga (HX-Refresh) para que el usuario vea que la fila SIGUE ahí
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Refresh': 'true'})
            
            return HttpResponseRedirect(reverse('list_aspir'))
            
        except Exception as e:
            messages.error(request, f"Error inesperado al intentar eliminar: {e}")
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Refresh': 'true'})
            return HttpResponseRedirect(reverse('list_aspir'))
        
        

    # Si alguien navega con GET a esta URL => 405
    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(['POST'])




# ---------------------------------------------------------------------------
# SELECTOR DE ASPIRANTES PARA CONTRATAR (modal)
# ---------------------------------------------------------------------------
# Antes, «Nuevo contrato» llevaba a la Lista de Aspirantes y desde alli habia
# que buscar a la persona, seleccionarla y pulsar «Contratar». Tres pantallas
# para una sola decision. Ahora la lista viene al usuario en un modal.
#
# Solo salen los CONTRATABLES —`estado='ASPIRANTE'`—, que es el mismo criterio
# de la Lista de Aspirantes. Los de la Lista de Bajas (`estado='BAJA'`) no
# aparecen: contratarlos desde aqui no tendria sentido y el formulario los
# rechazaria despues.

ASPIRANTES_POR_PAGINA_MODAL = 15


@login_required
def seleccionar_aspirante(request):
    """Listado paginado y buscable de aspirantes contratables, para el modal.

    La busqueda entiende nombre, apellido, nombre y apellido juntos, o carnet.
    El nombre completo se arma en SQL con `Concat` para que «Ana Perez» case
    aunque el nombre y el apellido esten en columnas distintas; buscar solo en
    `nombre` obligaria a escribir exactamente una de las dos partes.
    """
    query = (request.GET.get('q') or '').strip()

    qs = Aspirante.objects.filter(estado='ASPIRANTE')
    if query:
        qs = qs.annotate(
            nombre_completo=Concat('nombre', Value(' '), 'papellido',
                                   Value(' '), 'sapellido')
        ).filter(
            Q(doc_identidad__icontains=query)
            | Q(nombre_completo__icontains=query)
            | Q(nombre__icontains=query)
            | Q(papellido__icontains=query)
            | Q(sapellido__icontains=query)
        )

    paginator = Paginator(qs.order_by('nombre', 'papellido', 'sapellido'),
                          ASPIRANTES_POR_PAGINA_MODAL)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'pages/contrato/partials/tabla_aspirantes_modal.html', {
        'aspirantes': page_obj,
        'page_obj': page_obj,
        'q': query,
        # El cargo desde el que se abrio el modal, si viene del Gestor de
        # Cargos: viaja hasta el enlace de contratar para que el formulario
        # llegue con la plaza ya elegida.
        'cargo_id': request.GET.get('cargo') or '',
    })
