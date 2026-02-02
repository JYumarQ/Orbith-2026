from typing import override
from django.http import response, HttpResponseRedirect, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, DeleteView, UpdateView, View
from django.core.paginator import Paginator
from bolsa.models import Aspirante
from .models import CAlta, CBaja
from .forms import CAltaForm
from strorganizativa.models import Departamento, CargoPlantilla
from nomencladores.models import NSalario, NCausaAltaBaja
from django.urls import reverse_lazy
from configuracion.models import Configuracion
from django.template.loader import get_template
from django.db.models import Q, ProtectedError, Value
from django.db.models.functions import Concat
from django.db import transaction
from xhtml2pdf import pisa
from .forms import CAltaForm, MovimientoForm

# Create your views here.
    
#?ONTRATO
class ContratoListView(ListView):
    model = CAlta
    template_name = "pages/contrato/list_contrato.html"
    paginate_by = 8
    ordering = ['-fecha_alta']  
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = CAltaForm()
        context['search_url'] = 'search_contrato'
        context['causas_baja'] = NCausaAltaBaja.objects.filter(alta=False)
        return context
    

class MovimientoNominaListView(ListView):
    model = CAlta
    # Usaremos la nueva ruta de plantilla que acordamos
    template_name = "pages/movimientos/list_movimientos.html" 
    paginate_by = 8
    ordering = ['-fecha_alta']

    def get_queryset(self):
        # FILTRO CLAVE: Solo mostramos los marcados como "En Proceso"
        return CAlta.objects.filter(en_proceso_movimiento=True).order_by('-fecha_alta')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pasamos search_url por si quieres implementar búsqueda aquí también en el futuro
        # (Por ahora reutilizaremos lógica básica o lo dejaremos simple)
        context['titulo'] = "Movimientos de Nómina Pendientes"
        return context


def search_contratos(request):
    # 1. Obtener parámetros de filtros
    query = request.GET.get('filter_contrato', '').strip()
    page_num = request.GET.get('page', 1)
    page_size = request.GET.get('page_size', '8')
    
    # Filtros directos del Contrato (o Cargo)
    # (Si quisieras filtrar por Cargo o Unidad, irían aquí)
    
    # Filtros del Aspirante asociado
    provincia_id = request.GET.get('provincia')
    municipio_id = request.GET.get('municipio')
    nivel_educ = request.GET.get('nivel_educ')
    especialidad_id = request.GET.get('especialidad')
    sexo = request.GET.get('sexo')
    raza = request.GET.get('raza')
    grado_cientifico = request.GET.get('grado_cientifico')

    # 2. QuerySet Base
    qs = CAlta.objects.select_related('aspirante', 'cargo').all().order_by('-fecha_alta')

    # 3. Aplicar Filtros "Embudo" (Relación aspirante__)
    if provincia_id:
        qs = qs.filter(aspirante__provincia_id=provincia_id)
    if municipio_id:
        qs = qs.filter(aspirante__municipio_id=municipio_id)
    if nivel_educ:
        qs = qs.filter(aspirante__nivel_educ=nivel_educ)
    if especialidad_id:
        qs = qs.filter(aspirante__especialidad_id=especialidad_id)
    if sexo:
        qs = qs.filter(aspirante__sexo=sexo)
    if raza:
        qs = qs.filter(aspirante__raza=raza)
    if grado_cientifico:
        qs = qs.filter(aspirante__grado_cientifico=grado_cientifico)

    # 4. Buscador Inteligente (Concatenación)
    if query:
        qs = qs.annotate(
            nombre_completo=Concat(
                'aspirante__nombre', Value(' '), 
                'aspirante__papellido', Value(' '), 
                'aspirante__sapellido'
            )
        ).filter(
            Q(no_expediente__icontains=query) |
            Q(nombre_completo__icontains=query)
        )

    # 5. Paginación
    
    
    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page_num)

    return render(request, 'pages/contrato/partials/filter_contratos_list.html', {
        'object_list': page_obj,  # La lista de contratos de ESTA página
        'page_obj': page_obj,     # El objeto paginador (para contar páginas)
        'paginator': paginator,   # Esto es lo que usa para decir "Total de X registros"
        'search_url': 'search_contrato', # Clave para que HTMX sepa a dónde pedir la siguiente página
        'current_page_size': str(page_size)  # Para mantener el tamaño de página seleccionado
    })

#!UTIL
def cargar_salario(request):
    # lee correctamente los parámetros que HTMX está enviando
    cargo_id    = request.GET.get('cargo')
    tridente_id = request.GET.get('tridente')


    context = {}
    try:
        cargo = CargoPlantilla.objects.select_related('rol', 'ncargo').get(id=cargo_id)
        grupo_escala = cargo.ncargo.grupo_escala
        rol = cargo.rol

        salario = NSalario.objects.get(
            grupo_escala=grupo_escala,
            rol=rol,
            tridente_id=tridente_id
        )
        config = Configuracion.objects.first()
        if config and config.fondo_tiempo_calc_tarif is not None:
            fondo = float(config.fondo_tiempo_calc_tarif)
        else:
            fondo = 190.6

        tarifa_calculada = round(salario.monto / fondo, 5) if fondo else 0

        context = {
            'salario': round(float(salario.monto), 2),
            #Usar esta en caso de error o cambio, esta llama al valor en BD
            # 'tarifa':  round(salario.monto / config.fondo_tiempo_calc_tarif, 5),
            'tarifa':  tarifa_calculada,
            'extras':  round(float(salario.monto) / 160.6, 5),
        }
    except Exception as e:
        context = {
            'salario': '',
            'tarifa':  '',
            'extras':  '',
        }

    return render(request, "pages/contrato/partials/cargar_salario.html", context)


def validar_datos_contrato(request):
    expediente = request.GET.get('no_expediente', None)
    data = {
        'expediente_existe': False
    }
    if expediente:
        # Verifica si existe algún contrato con ese No. Expediente
        if CAlta.objects.filter(no_expediente=expediente).exists():
            data['expediente_existe'] = True
            
    return JsonResponse(data)

def solicitar_movimiento_nomina(request, pk):
    """
    Marca un contrato como 'En Proceso de Movimiento' para que aparezca
    en la bandeja de Mov. Nómina.
    """
    if request.method == "POST":
        try:
            contrato = get_object_or_404(CAlta, pk=pk)
            contrato.en_proceso_movimiento = True
            contrato.save()
            return JsonResponse({'success': True, 'message': 'Contrato enviado a proceso de movimiento.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Método no permitido.'}, status=405)

# orbith/contratos/views.py

def validar_plazas_cargo(request):
    cargo_id = request.GET.get('cargo_id', None)
    data = {
        'plazas_agotadas': False,
        'mensaje': ''
    }
    
    if cargo_id:
        try:
            # Buscamos el cargo y sus relaciones para el nombre
            cargo = CargoPlantilla.objects.select_related('ncargo').get(pk=cargo_id)
            
            # Comprobamos disponibilidad (Solo si es contrato INDETERMINADO normalmente, 
            # pero aquí validamos disponibilidad general del cargo según tu petición)
            if cargo.cant_cubierta >= cargo.cant_aprobada:
                data['plazas_agotadas'] = True
                data['mensaje'] = f"El Cargo '{cargo.ncargo.descripcion}' no tiene plazas disponibles ({cargo.cant_cubierta}/{cargo.cant_aprobada})"
                
        except CargoPlantilla.DoesNotExist:
            pass
            
    return JsonResponse(data)

def cargar_departamentos(request):
    unidad_id = request.GET.get('unidad')
    departamentos = Departamento.objects.none()
    
    if unidad_id:
        try:
            departamentos = Departamento.objects.filter(unidad_organizativa_id=unidad_id).order_by('descripcion')
        except (ValueError, TypeError):
            pass

    return render(request, 'pages/contrato/partials/options_generico.html', {'opciones': departamentos})

def cargar_cargos(request):
    dpto_id = request.GET.get('departamento')
    cargos = CargoPlantilla.objects.none()
    
    if dpto_id:
        try:
            # Filtramos cargos del departamento
            cargos = CargoPlantilla.objects.filter(departamento_id=dpto_id).select_related('ncargo').order_by('ncargo__descripcion')
        except (ValueError, TypeError):
            pass
            
    return render(request, 'pages/contrato/partials/options_cargos.html', {'cargos': cargos})


class ContratoCreateView(CreateView):
    model = CAlta
    form_class = CAltaForm
    template_name = "pages/contrato/add_contrato.html"
    success_url = reverse_lazy('list_aspir')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # aspirante_id viene en la URL
        aspirante_id = self.kwargs['aspirante_id']
        context['aspirante'] = get_object_or_404(Aspirante, doc_identidad=aspirante_id)
        return context

    def form_valid(self, form):
        # Asignar aspirante
        aspirante_id = self.kwargs['aspirante_id']
        form.instance.aspirante = get_object_or_404(Aspirante, doc_identidad=aspirante_id)
        
        self.object = form.save()
        
        messages.success(self.request, 'Contrato registrado correctamente.')

        # RESPUESTA AJAX (ÉXITO)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': True,
                'message': 'Contrato registrado correctamente.',
                'success_url': str(self.success_url) 
            })
        return super().form_valid(form)

    def form_invalid(self, form):
        # 1. Imprimir en consola para depuración
        print("🔴 ERRORES AL CREAR CONTRATO:", form.errors)

        # 2. RESPUESTA AJAX (Para evitar el crasheo)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            
            # Buscar si hay un error específico de "cargo" (Plazas agotadas)
            error_mensaje = None
            if 'cargo' in form.errors:
                # Tomamos el primer error de la lista del campo 'cargo'
                error_mensaje = form.errors['cargo'][0]
            elif 'reg_militar' in form.errors:
                error_mensaje = "El campo Servicio Militar es obligatorio."
            
            # Renderizamos el formulario con los errores pintados (rojo)
            html = render_to_string(
                self.template_name,
                self.get_context_data(form=form),
                request=self.request
            )
            
            # Devolvemos JSON con el HTML y el mensaje para el SweetAlert
            return JsonResponse({
                'form_is_valid': False, 
                'html_form': html,
                'error_popup': error_mensaje  # <--- Este es el dato clave
            })
            
        return super().form_invalid(form)

class ContratoUpdateView(UpdateView):
    model = CAlta
    form_class = CAltaForm
    template_name = "pages/contrato/updt_contrato.html"
    success_url = reverse_lazy('list_contrato')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        # --- TU LÓGICA ORIGINAL SE MANTIENE INTACTA ---
        context = super().get_context_data(**kwargs)

        contrato = self.object
        context['aspirante'] = contrato.aspirante

        config = Configuracion.objects.first()
        if config and config.fondo_tiempo_calc_tarif is not None:
            fondo = float(config.fondo_tiempo_calc_tarif)
        else:
            fondo = 190.6
            messages.warning(self.request, "Parámetros de configuración no encontrados. Usando valor por defecto.")
        context['fondo'] = fondo
    
        # 2) Si ya tiene cargo y tridente, calculo salario/tarifa/extras
        if contrato.cargo and contrato.tridente:
            cargo = contrato.cargo
            tridente_id = contrato.tridente.id
            grupo_escala = cargo.ncargo.grupo_escala
            rol = cargo.rol

            try:
                salario_obj = NSalario.objects.get(
                    grupo_escala=grupo_escala,
                    rol=rol,
                    tridente_id=tridente_id
                )
                monto = float(salario_obj.monto)
                
                tarifa = round(monto / fondo, 5) if fondo else 0
                extras = round((tarifa*0.25)+tarifa, 5) 
                
                context['initial_salario_escala'] = round(monto, 2)
                context['initial_tarifa_horaria'] = tarifa
                context['initial_tarifa_extras'] = extras
            except NSalario.DoesNotExist:
                context['initial_salario_escala'] = ""
                context['initial_tarifa_horaria'] = ""
                context['initial_tarifa_extras'] = ""
        else:
            context['initial_salario_escala'] = ""
            context['initial_tarifa_horaria'] = ""
            context['initial_tarifa_extras'] = ""

        return context

    # --- MÉTODOS AÑADIDOS PARA SOPORTE AJAX ---

    def form_valid(self, form):
        self.object = form.save()
        
        messages.success(self.request, 'Contrato actualizado correctamente.')

        # RESPUESTA AJAX (ÉXITO)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({
                'form_is_valid': True,
                'message': 'Contrato actualizado correctamente.',
                'success_url': str(self.success_url)
            })
        return super().form_valid(form)

    def form_invalid(self, form):
        # RESPUESTA AJAX (ERROR)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                self.template_name,
                self.get_context_data(form=form),
                request=self.request
            )
            return JsonResponse({'form_is_valid': False, 'html_form': html})
            
        return super().form_invalid(form)

# contratos/views.py
from django.db import transaction # IMPORTANTE
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.generic import DeleteView
from .models import CAlta, CBaja

class ContratoDeleteView(DeleteView):
    model = CAlta

    def post(self, request, *args, **kwargs):
        # 1. Recuperar el objeto de forma segura
        try:
            self.object = self.get_object()
        except CAlta.DoesNotExist:
            return JsonResponse({
                'success': False, 
                'message': 'El contrato que intenta eliminar no existe.'
            }, status=404)

        # 2. Obtener y validar datos del formulario
        fecha_baja = request.POST.get('fecha_baja')
        causa_id = request.POST.get('causa_baja')

        if not fecha_baja or not causa_id:
            return JsonResponse({
                'success': False, 
                'message': 'Faltan datos obligatorios: Fecha de Baja o Causa.'
            }, status=400)

        try:
            # 3. Iniciar Transacción Atómica
            # Asegura que se crea la baja Y se borra el alta, o no sucede nada.
            with transaction.atomic():
                
                # A. Crear el registro histórico (CBaja)
                # Pasamos SOLO los campos confirmados que existen en tu modelo CBaja.
                CBaja.objects.create(
                    # --- Campos heredados de ContratoBase ---
                    aspirante=self.object.aspirante,
                    no_expediente=self.object.no_expediente,
                    tipo=self.object.tipo,
                    cargo=self.object.cargo,
                    reg_militar=self.object.reg_militar,
                    profesional=self.object.profesional,
                    
                    # --- Campos específicos de CBaja (Confirmados) ---
                    fecha_baja=fecha_baja,
                    causa_baja_id=causa_id,  # Usamos el ID recibido del POST
                    
                    # Estos campos existen en CAlta y confirmaste que están en CBaja
                    fecha_alta=self.object.fecha_alta,
                    tridente=self.object.tridente
                    
                    # NOTA: Se ha eliminado 'observaciones' porque causaba Error 500
                )

                # B. Eliminar el contrato activo
                # Esto dispara la lógica del modelo CAlta (liberar plaza, cambiar estado aspirante)
                self.object.delete()

            # Si llegamos aquí, todo salió bien
            return JsonResponse({
                'success': True, 
                'message': 'Contrato dado de baja y archivado correctamente.'
            })

        except Exception as e:
            # Captura cualquier error (Integridad, Modelo, etc.) y evita el crash del servidor
            return JsonResponse({
                'success': False, 
                'message': f'Error interno al procesar la baja: {str(e)}'
            }, status=500)
#*REPORTES
class ContratoPDFView(View):
    def get(self, request, *args, **kwargs):
        # Obtiene todos los contratos
        list_contratos = CAlta.objects.all()
        template = get_template('pages/reportes/reporte_contratos.html')
        context = {
            'titulo': 'Contratos',
            'contratos': list_contratos
            }
        html = template.render(context)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachement; filename="report.pdf"'
        pisaStatus = pisa.CreatePDF(html, dest=response)
        if pisaStatus.err:
            return HttpResponse('Hay un error <pre>'+html+'</pre>')
        return response
        
class PrintContratoPDFView(View):
    def get(self, request, *args, **kwargs):
        # Obtiene todos los contratos
        contrato = get_object_or_404(CAlta, no_expediente=kwargs['no_expediente'])
        template = get_template('pages/reportes/nuevo_contrato.html')
        context = {
            'titulo': 'Contratos',
            'contrato': contrato
            }
        html = template.render(context)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachement; filename="'+contrato.aspirante.nombre+"_"+'"contrato.pdf"'
        pisaStatus = pisa.CreatePDF(html, dest=response)
        if pisaStatus.err:
            return HttpResponse('Hay un error <pre>'+html+'</pre>')
        return response
        


class MovimientoUpdateView(UpdateView):
    model = CAlta
    form_class = MovimientoForm
    template_name = "pages/contrato/movimiento_nomina.html"
    success_url = reverse_lazy('list_contrato')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contrato = self.object
        context['contrato_actual'] = contrato
        context['aspirante'] = contrato.aspirante
        
        # --- LÓGICA DE PRE-CARGA (Lo nuevo) ---
        # Calculamos datos para la columna IZQUIERDA (Actual) y DERECHA (Inicial)
        if contrato.cargo:
            # Datos fijos del cargo
            grupo = contrato.cargo.ncargo.grupo_escala
            cat = contrato.cargo.ncargo.get_cat_ocupacional_display()
            rol = contrato.cargo.rol.tipo if contrato.cargo.rol else "Cuadro"
            
            # Pasamos estos datos para rellenar los inputs al abrir el modal
            context['initial_grupo'] = grupo
            context['initial_cat'] = cat
            context['initial_rol'] = rol
            
            # Cálculo de Salario (Si tiene tridente)
            if contrato.tridente:
                try:
                    salario_obj = NSalario.objects.filter(
                        grupo_escala=contrato.cargo.ncargo.grupo_escala,
                        rol=contrato.cargo.rol,
                        tridente=contrato.tridente
                    ).first()
                    
                    if salario_obj:
                        monto = float(salario_obj.monto)
                        context['salario_actual'] = monto # Para la Izquierda
                        
                        # Para la derecha (Inputs ocultos o visibles de resultados)
                        config = Configuracion.objects.first()
                        fondo = float(config.fondo_tiempo_calc_tarif) if config and config.fondo_tiempo_calc_tarif else 190.6
                        
                        context['initial_salario_escala'] = round(monto, 2)
                        context['initial_tarifa_horaria'] = round(monto / fondo, 5) if fondo else 0
                        context['initial_tarifa_extras'] = round((context['initial_tarifa_horaria']*0.25)+context['initial_tarifa_horaria'], 5)
                except:
                    pass
        
        return context
    
    # ... (form_valid y form_invalid se quedan igual) ...
    def form_valid(self, form):
        nueva_fecha = form.cleaned_data.get('fecha_efectiva')
        if nueva_fecha: form.instance.fecha_alta = nueva_fecha
        form.instance.en_proceso_movimiento = False
        self.object = form.save()
        messages.success(self.request, 'Movimiento de Nómina registrado correctamente.')
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'form_is_valid': True, 'message': 'Movimiento registrado correctamente.', 'success_url': str(self.success_url)})
        return super().form_valid(form)

    def form_invalid(self, form):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(self.template_name, self.get_context_data(form=form), request=self.request)
            return JsonResponse({'form_is_valid': False, 'html_form': html})
        return super().form_invalid(form)


# 2. ACTUALIZA ESTA FUNCIÓN (Agregamos el retorno de textos para OOB)
def cargar_salario(request):
    cargo_id    = request.GET.get('cargo')
    tridente_id = request.GET.get('tridente')
    
    # DETECTAR SI ES MOVIMIENTO (buscamos el parámetro extra en la URL)
    es_movimiento = request.GET.get('es_movimiento') 

    context = {}
    try:
        cargo = CargoPlantilla.objects.select_related('rol', 'ncargo').get(id=cargo_id)
        
        # Datos extra (solo necesarios para movimiento, pero no estorban si se calculan)
        context['nuevo_grupo'] = cargo.ncargo.grupo_escala
        context['nueva_cat'] = cargo.ncargo.get_cat_ocupacional_display()
        context['nuevo_rol'] = cargo.rol.tipo if cargo.rol else "Cuadro"

        salario = NSalario.objects.get(
            grupo_escala=cargo.ncargo.grupo_escala,
            rol=cargo.rol,
            tridente_id=tridente_id
        )
        
        config = Configuracion.objects.first()
        fondo = float(config.fondo_tiempo_calc_tarif) if config and config.fondo_tiempo_calc_tarif else 190.6
        tarifa_calculada = round(salario.monto / fondo, 5) if fondo else 0

        context.update({
            'salario': round(float(salario.monto), 2),
            'tarifa':  tarifa_calculada,
            'extras':  round(float(salario.monto) / 160.6, 5),
        })
    except Exception:
        context.update({
            'salario': 0.00, 'tarifa': 0, 'extras': 0,
            'nuevo_grupo': '', 'nueva_cat': '', 'nuevo_rol': ''
        })

    # DECISIÓN DE PLANTILLA
    if es_movimiento:
        # Usamos el archivo NUEVO con estilos corregidos y OOB swaps extra
        return render(request, "pages/contrato/partials/cargar_datos_movimiento.html", context)
    else:
        # Usamos el archivo VIEJO (Original) para no romper Add/Update Contrato
        return render(request, "pages/contrato/partials/cargar_salario.html", context)