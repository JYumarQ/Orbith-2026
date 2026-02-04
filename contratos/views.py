from typing import override, Any
from django.http import response, HttpResponseRedirect, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, DeleteView, UpdateView, View
from django.core.paginator import Paginator
from django.conf import settings
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
from datetime import datetime
from .forms import CAltaForm, MovimientoForm
from docxtpl import DocxTemplate, RichText
from io import BytesIO
import os
import traceback
import sys

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


def obtener_datos_previos(request):
    """
    Busca datos previos en CAlta (Activos) O CBaja (Histórico de Bajas)
    para recuperar No. Expediente y Registro Militar.
    """
    aspirante_id = request.GET.get('aspirante_id')
    if not aspirante_id:
        return JsonResponse({'existe': False})

    # 1. Buscar primero en Bajas (lo más probable si se está recontratando)
    baja_reciente = CBaja.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_baja').first()
    
    if baja_reciente:
        return JsonResponse({
            'existe': True,
            'no_expediente': baja_reciente.no_expediente,
            'reg_militar': baja_reciente.reg_militar
        })

    # 2. Si no está en bajas, buscar en Activos (casos raros de pluriempleo o errores)
    alta_reciente = CAlta.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_alta').first()
    
    if alta_reciente:
        return JsonResponse({
            'existe': True,
            'no_expediente': alta_reciente.no_expediente,
            'reg_militar': alta_reciente.reg_militar
        })

    # 3. No se encontró nada
    return JsonResponse({'existe': False})

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


def historico_trabajador(request, aspirante_id):
    from .models import CAlta, CBaja, TMovimiento 
    from bolsa.models import Aspirante

    # 1. Obtener Aspirante
    try:
        aspirante = Aspirante.objects.get(pk=aspirante_id)
        encabezado = {
            'nombre_completo': f"{aspirante.nombre} {aspirante.papellido} {aspirante.sapellido}",
            'ci': aspirante.doc_identidad
        }
    except Aspirante.DoesNotExist:
        return JsonResponse({'data': [], 'encabezado': {'nombre_completo': 'Desconocido', 'ci': ''}})

    lista_general = []

    # Helper para formatear dinero con 2 decimales
    def fmt_dinero(valor):
        try:
            return f"{float(valor):.2f}"
        except:
            return "0.00"

    # ---------------------------------------------------------
    # FUENTE A: Contratos Activos (CAlta)
    # ---------------------------------------------------------
    altas = CAlta.objects.filter(aspirante_id=aspirante_id).select_related('cargo__ncargo', 'cargo__departamento__unidad_organizativa')
    
    for alta in altas:
        # LÓGICA INTELIGENTE:
        # Buscamos si este contrato tiene movimientos.
        primer_mov = TMovimiento.objects.filter(contrato=alta).order_by('fecha_efectiva').first()
        
        if primer_mov:
            # Si hubo movimientos, el "Alta Inicial" era lo que había ANTES del primer movimiento
            cargo_inicial = primer_mov.cargo_anterior
            unidad_inicial = primer_mov.unidad_anterior or "---"
            salario_inicial = primer_mov.salario_anterior
        else:
            # Si nunca hubo movimientos, el "Alta Inicial" es lo que tiene ahora
            cargo_inicial = alta.cargo.ncargo.descripcion if alta.cargo else "---"
            unidad_inicial = alta.cargo.departamento.unidad_organizativa.descripcion if (alta.cargo and alta.cargo.departamento) else "---"
            salario_inicial = alta.calcular_salario_escala()

        item = {
            'fecha_orden': alta.fecha_alta,
            'evento': 'Alta / Recontratación',
            'expediente': alta.no_expediente,
            'unidad': unidad_inicial,
            'cargo': cargo_inicial,
            'salario': fmt_dinero(salario_inicial), # Formato corregido
            'fecha_inicio': alta.fecha_alta.strftime('%d/%m/%Y') if alta.fecha_alta else "-",
            'fecha_fin': "Activo",
            'estado_clase': 'text-success'
        }
        lista_general.append(item)

    # ---------------------------------------------------------
    # FUENTE B: Contratos Cerrados (CBaja)
    # ---------------------------------------------------------
    bajas = CBaja.objects.filter(aspirante_id=aspirante_id)
    
    for baja in bajas:
        if baja.fecha_alta:
            # Misma lógica: Buscamos si hubo movimientos para este expediente viejo
            # Nota: Al estar de baja, el 'contrato' en TMovimiento es Null, buscamos por expediente
            primer_mov_baja = TMovimiento.objects.filter(
                aspirante_id=aspirante_id, 
                no_expediente=baja.no_expediente
            ).order_by('fecha_efectiva').first()

            if primer_mov_baja:
                # Recuperamos el pasado real
                cargo_baja_ini = primer_mov_baja.cargo_anterior
                unidad_baja_ini = primer_mov_baja.unidad_anterior or "---"
                # Ojo: salario_anterior en TMovimiento es Decimal, salario_basico en Nomenclador es otra cosa.
                salario_baja_ini = primer_mov_baja.salario_anterior
            else:
                # Si no hubo movimientos, usamos la foto final de la baja
                cargo_baja_ini = baja.cargo.ncargo.descripcion if baja.cargo else "---"
                unidad_baja_ini = "---" 
                if baja.cargo and baja.cargo.departamento:
                    unidad_baja_ini = baja.cargo.departamento.unidad_organizativa.descripcion
                
                # Intentamos sacar salario básico histórico
                salario_baja_ini = 0
                if baja.cargo and baja.cargo.ncargo.salario_basico:
                    salario_baja_ini = baja.cargo.ncargo.salario_basico

            item_alta_vieja = {
                'fecha_orden': baja.fecha_alta,
                'evento': 'Alta / Recontratación',
                'expediente': baja.no_expediente,
                'unidad': unidad_baja_ini,
                'cargo': cargo_baja_ini,
                'salario': fmt_dinero(salario_baja_ini),
                'fecha_inicio': baja.fecha_alta.strftime('%d/%m/%Y'),
                'fecha_fin': baja.fecha_baja.strftime('%d/%m/%Y') if baja.fecha_baja else "-",
                'estado_clase': 'text-muted'
            }
            lista_general.append(item_alta_vieja)

    # ---------------------------------------------------------
    # FUENTE C: Movimientos (TMovimiento)
    # ---------------------------------------------------------
    movimientos = TMovimiento.objects.filter(aspirante_id=aspirante_id)
    
    for mov in movimientos:
        nombre_evento = mov.tipo_movimiento
        
        # Refinar nombres
        if nombre_evento == "Movimiento de Nómina":
            if mov.unidad_anterior != mov.unidad_nueva:
                nombre_evento = "Cambio de Unidad"
            elif mov.cargo_anterior != mov.cargo_nuevo:
                nombre_evento = "Cambio de Cargo"
            elif mov.salario_anterior != mov.salario_nuevo:
                nombre_evento = "Movimiento Salarial"

        clase_css = 'text-warning'
        if nombre_evento == 'Baja':
             clase_css = 'text-danger fw-bold'

        item_mov = {
            'fecha_orden': mov.fecha_efectiva,
            'evento': nombre_evento,
            'expediente': mov.no_expediente,
            'unidad': mov.unidad_nueva if mov.unidad_nueva else "---", 
            'cargo': mov.cargo_nuevo,
            'salario': fmt_dinero(mov.salario_nuevo),
            'fecha_inicio': mov.fecha_efectiva.strftime('%d/%m/%Y'),
            'fecha_fin': "-", 
            'estado_clase': clase_css
        }
        lista_general.append(item_mov)

    # ---------------------------------------------------------
    # ORDENAR Y ENCADENAR
    # ---------------------------------------------------------
    lista_general.sort(key=lambda x: x['fecha_orden'])

    primer_alta_encontrada = False
    for item in lista_general:
        if 'Alta' in item['evento']:
            if not primer_alta_encontrada:
                item['evento'] = "Alta Inicial"
                primer_alta_encontrada = True
            else:
                item['evento'] = "Recontratación"

    for i in range(len(lista_general)):
        item_actual = lista_general[i]
        
        if item_actual['evento'] == 'Baja':
            item_actual['fecha_fin'] = item_actual['fecha_inicio']
            continue

        if i < len(lista_general) - 1:
            siguiente_item = lista_general[i + 1]
            if item_actual['expediente'] == siguiente_item['expediente']:
                item_actual['fecha_fin'] = siguiente_item['fecha_inicio']
                if item_actual['estado_clase'] == 'text-success': 
                     item_actual['estado_clase'] = 'text-muted'

    return JsonResponse({
        'data': lista_general, 
        'encabezado': encabezado
    })


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
        # Asegúrate de tener este import arriba del todo en el archivo:
        from datetime import datetime
        
        # 1. Recuperar el objeto de forma segura
        try:
            contrato: CAlta = self.get_object() # type: ignore
        except CAlta.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'El contrato que intenta eliminar no existe.'}, status=404)

        # 2. Obtener datos del formulario
        fecha_baja_str = request.POST.get('fecha_baja')
        causa_id = request.POST.get('causa_baja')

        if not fecha_baja_str or not causa_id:
            return JsonResponse({'success': False, 'message': 'Faltan datos obligatorios: Fecha de Baja o Causa.'}, status=400)

        # 3. Convertir fecha para validar
        try:
            fecha_baja = datetime.strptime(fecha_baja_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
             return JsonResponse({'success': False, 'message': 'Formato de fecha inválido.'}, status=400)

        # =================================================================
        # VALIDACIÓN CRONOLÓGICA (La Barrera)
        # =================================================================
        from .models import TMovimiento
        
        # A. Buscar último movimiento registrado
        ultimo_mov = TMovimiento.objects.filter(contrato=contrato).order_by('-fecha_efectiva').first()
        
        # B. Definir fecha límite (El evento más reciente entre el último mov o el alta original)
        fecha_limite = ultimo_mov.fecha_efectiva if ultimo_mov else contrato.fecha_alta
        
        # C. Comparar (Baja no puede ser anterior a lo último que pasó)
        if fecha_limite and fecha_baja < fecha_limite:
            return JsonResponse({
                'success': False, 
                'message': f"No puede dar Baja con fecha {fecha_baja.strftime('%d/%m/%Y')} porque existe un evento posterior el {fecha_limite.strftime('%d/%m/%Y')}."
            }, status=400)
        # =================================================================

        try:
            # 4. Iniciar Transacción (Si pasó la validación)
            with transaction.atomic():
                # A. SALVAR EL HISTORIAL EXISTENTE
                TMovimiento.objects.filter(contrato=contrato).update(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente
                )

                # 2. CREAR EL NUEVO EVENTO DE "BAJA" EN EL HISTÓRICO
                # Capturamos datos finales
                cargo_final = contrato.cargo.ncargo.descripcion if contrato.cargo else "---"
                unidad_final = contrato.cargo.departamento.unidad_organizativa.descripcion if (contrato.cargo and contrato.cargo.departamento) else "---"
                salario_final = contrato.calcular_salario_escala() or 0

                TMovimiento.objects.create(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente,
                    contrato=None, # Ya no hay contrato activo
                    fecha_efectiva=fecha_baja,
                    tipo_movimiento="Baja",
                    
                    cargo_anterior=contrato.cargo.ncargo.descripcion if contrato.cargo else "---",
                    cargo_nuevo="---",
                    salario_anterior=contrato.calcular_salario_escala() or 0,
                    salario_nuevo=0,
                    unidad_anterior=contrato.cargo.departamento.unidad_organizativa.descripcion if (contrato.cargo and contrato.cargo.departamento) else "---",
                    unidad_nueva="---"
                )
                
                # A. Crear el registro histórico (CBaja)
                CBaja.objects.create(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente,
                    tipo=contrato.tipo,
                    cargo=contrato.cargo,
                    reg_militar=contrato.reg_militar,
                    profesional=contrato.profesional,
                    fecha_baja=fecha_baja,
                    causa_baja_id=causa_id,
                    fecha_alta=contrato.fecha_alta,
                    tridente=contrato.tridente
                )
                # B. Eliminar el contrato activo
                contrato.delete()

            # Si llegamos aquí, todo salió bien
            return JsonResponse({
                'success': True, 
                'message': 'Contrato dado de baja y archivado correctamente.'
            })

        except Exception as e:
            # Captura cualquier error (Integridad, Modelo, etc.) y evita el crash del servidor
            print(f"ERROR AL DAR BAJA: {e}")
            return JsonResponse({
                'success': False, 
                'message': f'Error interno al procesar la baja: {str(e)}'
            }, status=500)
#*REPORTES

        


class MovimientoUpdateView(UpdateView):
    model = CAlta
    form_class = MovimientoForm
    template_name = "pages/contrato/movimiento_nomina.html"
    success_url = reverse_lazy('list_movimientos')

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
    @transaction.atomic
    def form_valid(self, form):
        try:
            # 1. Obtener contrato y fecha nueva
            contrato = self.object
            nueva_fecha = form.cleaned_data.get('fecha_efectiva')

            # =================================================================
            # PASO 1: VALIDACIÓN CRONOLÓGICA (EL PORTERO)
            # =================================================================
            from .models import TMovimiento
            
            # Buscamos si hay movimientos previos
            ultimo_mov = TMovimiento.objects.filter(contrato=contrato).order_by('-fecha_efectiva').first()
            
            # La fecha límite es: La del último movimiento, O si no hay, la fecha de Alta original
            fecha_limite = ultimo_mov.fecha_efectiva if ultimo_mov else contrato.fecha_alta

            if nueva_fecha and nueva_fecha < fecha_limite:
                # Si la nueva fecha es viajar al pasado -> ERROR
                mensaje = f"Error Cronológico: La fecha seleccionada ({nueva_fecha.strftime('%d/%m/%Y')}) es anterior al último evento registrado ({fecha_limite.strftime('%d/%m/%Y')})."
                
                if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
                else:
                    form.add_error('fecha_efectiva', mensaje)
                    return self.form_invalid(form)

            # =================================================================
            # PASO 2: CAPTURAR DATOS PREVIOS (LÓGICA DE NEGOCIO)
            # =================================================================
            # Como pasamos la validación, ahora sí procedemos a guardar
            
            contrato_previo = CAlta.objects.get(pk=self.object.pk)
            
            cargo_ant = contrato_previo.cargo.ncargo.descripcion if contrato_previo.cargo else "---"
            unidad_ant = contrato_previo.cargo.departamento.unidad_organizativa.descripcion if (contrato_previo.cargo and contrato_previo.cargo.departamento) else "---"
            
            salario_ant = 0
            if contrato_previo.cargo:
                 try:
                     salario_obj = NSalario.objects.filter(
                         grupo_escala=contrato_previo.cargo.ncargo.grupo_escala,
                         rol=contrato_previo.cargo.rol,
                         tridente=contrato_previo.tridente
                     ).first()
                     salario_ant = salario_obj.monto if salario_obj else 0
                 except:
                     salario_ant = 0

            # PASO 3: CAPTURAR DATOS NUEVOS
            cargo_nuevo_obj = form.cleaned_data.get('cargo')
            
            cargo_nue = cargo_nuevo_obj.ncargo.descripcion if cargo_nuevo_obj else "---"
            unidad_nue = cargo_nuevo_obj.departamento.unidad_organizativa.descripcion if (cargo_nuevo_obj and cargo_nuevo_obj.departamento) else "---"
            
            salario_nue = float(self.request.POST.get('salarioEscala', 0))

            observaciones_txt = form.cleaned_data.get('observaciones', '')
            fecha_solicitud_dt = form.cleaned_data.get('fecha_solicitud')

            # PASO 4: GUARDAR EL HISTÓRICO
            from django.utils import timezone 
            
            TMovimiento.objects.create(
                contrato=self.object,
                aspirante=self.object.aspirante,
                no_expediente=self.object.no_expediente,
                fecha_efectiva=nueva_fecha if nueva_fecha else timezone.now().date(),

                fecha_solicitud=fecha_solicitud_dt,
                observaciones=observaciones_txt,
                
                cargo_anterior=cargo_ant,
                cargo_nuevo=cargo_nue,
                salario_anterior=salario_ant,
                salario_nuevo=salario_nue,
                unidad_anterior=unidad_ant,
                unidad_nueva=unidad_nue,
                
                tipo_movimiento="Movimiento de Nómina"
            )

            # PASO 5: ACTUALIZAR CONTRATO
            # NOTA: NO actualizamos fecha_alta aquí para preservar la antigüedad original
            
            form.instance.en_proceso_movimiento = False
            self.object = form.save()

            messages.success(self.request, 'Movimiento de Nómina registrado correctamente.')

            if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                from django.urls import reverse

                return JsonResponse({
                    'form_is_valid': True, 
                    'message': 'Movimiento registrado correctamente.', 
                    'success_url': str(self.success_url),
                    'pdf_url': reverse('imprimir_modelo_movimiento', kwargs={'pk': self.object.pk})
                })
            return super().form_valid(form)

        
        except Exception as e:
            # --- MANEJO DE ERRORES ---
            print("\n" + "="*50)
            print("🔴 ERROR CRÍTICO EN MOVIMIENTO DE NÓMINA")
            print(f"Tipo: {type(e).__name__}")
            print(f"Mensaje: {str(e)}")
            print("-" * 20)
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            print("="*50 + "\n")

            transaction.set_rollback(True)
            return JsonResponse({'form_is_valid': False, 'error_popup': str(e)}, status=500)

            if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'form_is_valid': False,
                    'error_popup': f"Error del Sistema: {str(e)}",
                    'html_form': render_to_string(
                        self.template_name, 
                        self.get_context_data(form=form), 
                        request=self.request
                    )
                }, status=500)
            else:
                messages.error(self.request, f"Error crítico: {str(e)}")
                return self.form_invalid(form)

    def form_invalid(self, form):
        # --- 1. EL CHIVATO (Debug) ---
        # Esto imprimirá en tu terminal EXACTAMENTE por qué falla el formulario
        print("\n" + "!"*50)
        print("❌ ERROR DE VALIDACIÓN (400):")
        print(form.errors.as_json()) 
        print("!"*50 + "\n")
        
        # --- 2. RESPUESTA AL FRONTEND ---
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            # Renderizamos de nuevo el modal, ahora con los mensajes de error (rojos) que Django generó
            html = render_to_string(self.template_name, self.get_context_data(form=form), request=self.request)
            return JsonResponse({'form_is_valid': False, 'html_form': html}, status=400)
            
        return super().form_invalid(form)
    

def abreviar_cargo_inteligente(texto_cargo):
    if not texto_cargo: return "-"
    
    diccionario = {
        "OPERADOR": "OP.", "OPERARIO": "OPE.", "ESPECIALISTA": "ESP.",
        "MANTENIMIENTO": "MANT.", "DEPARTAMENTO": "DPTO.", "ADMINISTRATIVO": "ADMIN.",
        "ADMINISTRACION": "ADMIN.", "SERVICIOS": "SERVS.", "GENERAL": "GRAL.",
        "AUXILIAR": "AUX.", "TECNICO": "TEC.", "TÉCNICO": "TÉC.",
        "SUPERIOR": "SUP.", "PRINCIPAL": "PRAL.", "PRODUCCION": "PROD.",
        "FABRICACION": "FAB.", "FABRICACIÓN": "FAB.", "TRANSFORMADORES": "TRANSF.",
        "DISTRIBUCION": "DIST.", "ENERGETICO": "ENERG.", "MAQUINARIA": "MAQ.",
        "RECURSOS": "REC.", "HUMANOS": "HUM.", "SEGURIDAD": "SEG.",
    }
    
    palabras = texto_cargo.upper().split()
    # Pylance fix: Aseguramos que 'p' siempre es str y el resultado también
    palabras_nuevas = [str(diccionario.get(p, p)) for p in palabras]
    return " ".join(palabras_nuevas)


# --- LA VISTA DEFINITIVA (Sustituye a ModeloMovimientoPDFView) ---
class ModeloMovimientoDocxView(View):
    def get(self, request, *args, **kwargs):
        from .models import CAlta, TMovimiento
        
        contrato = get_object_or_404(CAlta, pk=kwargs['pk'])
        mov = TMovimiento.objects.filter(contrato=contrato).order_by('-id').first()
        
        # --- CORRECCIÓN PARA PYLANCE ---
        if not mov:
            return HttpResponse("Error: No se encontró el movimiento de nómina.", status=404)
        # -------------------------------

        hoy = datetime.now()
        
        template_path = os.path.join(settings.BASE_DIR, 'templates', 'pages', 'reportes', '13-MOVIMIENTO DE NOMINAS.docx')
        
        try:
            doc = DocxTemplate(template_path)
        except FileNotFoundError:
            return HttpResponse(f"Error: No se encuentra la plantilla en {template_path}", status=500)

        # Lógica de Cargo
        cargo_texto = contrato.cargo.ncargo.descripcion if contrato.cargo else "-"
        cargo_abreviado = abreviar_cargo_inteligente(cargo_texto)
        
        if len(cargo_abreviado) > 35:
            cargo_final = RichText(cargo_abreviado, size=14)
        elif len(cargo_abreviado) > 25:
            cargo_final = RichText(cargo_abreviado, size=16)
        else:
            cargo_final = cargo_abreviado

        # Contexto (Con protecciones para valores None)
        context = {
            'ueb': mov.unidad_nueva if mov.unidad_nueva else (contrato.cargo.departamento.unidad_organizativa.descripcion if contrato.cargo else ""),
            'doc_id': f"{mov.pk:06d}", # Pylance ya sabe que mov no es None
            'd': hoy.strftime("%d"),
            'm': hoy.strftime("%m"),
            'a': hoy.strftime("%y"),
            
            'x_alta': "X" if "Alta" in (mov.tipo_movimiento or "") else "",
            'x_baja': "X" if "Baja" in (mov.tipo_movimiento or "") else "",
            'x_mov':  "X" if "Movimiento" in (mov.tipo_movimiento or "") else "",
            
            'ed': mov.fecha_efectiva.strftime("%d") if mov.fecha_efectiva else "-",
            'em': mov.fecha_efectiva.strftime("%m") if mov.fecha_efectiva else "-",
            'ea': mov.fecha_efectiva.strftime("%Y") if mov.fecha_efectiva else "-",
            
            'nombre': contrato.aspirante.nombre,
            'ap1': contrato.aspirante.papellido,
            'ap2': contrato.aspirante.sapellido,
            'exp': contrato.no_expediente,
            
            # Usamos getattr para métodos mágicos de Django que Pylance no ve
            'cat': getattr(contrato.cargo.ncargo, 'get_cat_ocupacional_display')() if contrato.cargo else "-",
            'cargo': cargo_final,
            'area': contrato.cargo.departamento.descripcion if contrato.cargo else "-",
            
            'sal_ant': mov.salario_anterior if mov.salario_anterior is not None else 0,
            'rol_nue': contrato.cargo.rol.tipo if (contrato.cargo and contrato.cargo.rol) else "-",
            'tri_nue': contrato.tridente if contrato.tridente else "-",
            'sal_nue': mov.salario_nuevo if mov.salario_nuevo is not None else 0,
            
            'observaciones': mov.observaciones or ""
        }

        doc.render(context)
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        filename = f"Movimiento_{contrato.no_expediente}.docx"
        
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response


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
        context['nueva_cat'] = getattr(cargo.ncargo, 'get_cat_ocupacional_display')()
        context['nuevo_rol'] = cargo.rol.tipo if cargo.rol else "Cuadro"

        salario = NSalario.objects.get(
            grupo_escala=cargo.ncargo.grupo_escala,
            rol=cargo.rol,
            tridente_id=tridente_id
        )
        
        config = Configuracion.objects.first()
        fondo = float(config.fondo_tiempo_calc_tarif) if config and config.fondo_tiempo_calc_tarif else 190.6
        tarifa_calculada = round(float(salario.monto) / fondo, 5) if fondo else 0

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