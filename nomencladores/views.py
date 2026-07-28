from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import NCargo, NProvincia, NMunicipio, NHorario, NJornada, NCausaAltaBaja, NCondicionLaboralAnormal
from .forms import NCargoForm, RegistrarSalariosForm, EditarSalariosForm, NGrupoEscalaForm, NTipoUnidadOrganizativaForm
from django.urls import reverse_lazy
from django.contrib import messages, admin
from django.db import transaction
from nomencladores.models import NSalario, NRol, NTridente, NGrupoEscala, NEspecialidad, NTipoContrato, NMotivoContrato
from django.http import JsonResponse, HttpResponse
import json
from django.db.models.deletion import RestrictedError
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, ProtectedError
from django.core.paginator import Paginator
from .models import NFamiliaCargo, NNivelPreparacion, NTipoUnidadOrganizativa, NTipoFamilia, NNocturnidad
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP

# Mapeo de Municipios de Cuba (Abreviaturas estándar tipo ISO/IATA)
ABR_MUNICIPIOS = {
    # --- Pinar del Río ---
    'Pinar del Río': 'PRI', 'Consolación del Sur': 'CSU', 'Guane': 'GUA', 
    'La Palma': 'LPA', 'Los Palacios': 'LPA', 'Mantua': 'MAN', 
    'Minas de Matahambre': 'MMA', 'San Juan y Martínez': 'SJM', 
    'San Luis': 'SLU', 'Sandino': 'SAN', 'Viñales': 'VIN',

    # --- Artemisa ---
    'Artemisa': 'ART', 'Alquízar': 'ALQ', 'Bahía Honda': 'BHO', 
    'Bauta': 'BAU', 'Caimito': 'CAI', 'Candelaria': 'CAN', 
    'Guanajay': 'GNY', 'Güira de Melena': 'GME', 'Mariel': 'MAR', 
    'San Antonio de los Baños': 'SAB', 'San Cristóbal': 'SCR',

    # --- La Habana ---
    'Arroyo Naranjo': 'ARN', 'Boyeros': 'BOY', 'Centro Habana': 'CHA', 
    'Cerro': 'CER', 'Cotorro': 'COT', 'Diez de Octubre': 'DDO', 
    'Guanabacoa': 'GBC', 'La Habana del Este': 'HDE', 'La Habana Vieja': 'LHV', 
    'La Lisa': 'LIS', 'Marianao': 'MAR', 'Playa': 'PLA', 
    'Plaza de la Revolución': 'PLZ', 'Regla': 'REG', 'San Miguel del Padrón': 'SMP',

    # --- Mayabeque ---
    'San José de las Lajas': 'SJL', 'Batabanó': 'BAT', 'Bejucal': 'BEJ', 
    'Güines': 'GUI', 'Jaruco': 'JAR', 'Madruga': 'MAD', 
    'Melena del Sur': 'MSU', 'Nueva Paz': 'NPA', 'Quivicán': 'QUI', 
    'San Nicolás': 'SNI', 'Santa Cruz del Norte': 'SCN',

    # --- Matanzas ---
    'Matanzas': 'MAT', 'Calimete': 'CAL', 'Cárdenas': 'CAR', 
    'Ciénaga de Zapata': 'CZA', 'Colón': 'COL', 'Jagüey Grande': 'JGR', 
    'Jovellanos': 'JOV', 'Limonar': 'LIM', 'Los Arabos': 'LAR', 
    'Martí': 'MTI', 'Pedro Betancourt': 'PBE', 'Perico': 'PER', 
    'Unión de Reyes': 'URE',

    # --- Cienfuegos ---
    'Cienfuegos': 'CFG', 'Abreus': 'ABR', 'Aguada de Pasajeros': 'APA', 
    'Cruces': 'CRU', 'Cumanayagua': 'CUM', 'Lajas': 'LAJ', 
    'Palmira': 'PAL', 'Rodas': 'ROD',

    # --- Villa Clara ---
    'Santa Clara': 'SCL', 'Caibarién': 'CAI', 'Camajuaní': 'CMJ', 
    'Cifuentes': 'CIF', 'Corralillo': 'COR', 'Encrucijada': 'ENC', 
    'Manicaragua': 'MAN', 'Placetas': 'PLA', 'Quemado de Güines': 'QGU', 
    'Ranchuelo': 'RAN', 'Remedios': 'REM', 'Sagua la Grande': 'SAG', 
    'Santo Domingo': 'SDO',

    # --- Sancti Spíritus ---
    'Sancti Spíritus': 'SSP', 'Cabaiguán': 'CAB', 'Fomento': 'FOM', 
    'Jatibonico': 'JAT', 'La Sierpe': 'SIE', 'Taguasco': 'TAG', 
    'Trinidad': 'TRI', 'Yaguajay': 'YAG',

    # --- Ciego de Ávila ---
    'Ciego de Ávila': 'CAV', 'Baraguá': 'BAR', 'Bolivia': 'BOL', 
    'Chambas': 'CHA', 'Ciro Redondo': 'CRE', 'Florencia': 'FLO', 
    'Majagua': 'MAJ', 'Morón': 'MOR', 'Primero de Enero': 'PEN', 
    'Venezuela': 'VEN',

    # --- Camagüey (Tu configuración original) ---
    'Camagüey': 'CMG', 'Carlos Manuel de Céspedes': 'CES', 
    'Esmeralda': 'ESM', 'Florida': 'FLA', 'Guáimaro': 'GUA', 
    'Jimaguayú': 'JIM', 'Minas': 'MIN', 'Najasa': 'NAJ', 
    'Nuevitas': 'NUE', 'Santa Cruz del Sur': 'SCS', 
    'Sibanicú': 'SIB', 'Sierra de Cubitas': 'SCB', 'Vertientes': 'VER',

    # --- Las Tunas ---
    'Las Tunas': 'LTU', 'Amancio': 'AMA', 'Colombia': 'COL', 
    'Jesús Menéndez': 'JME', 'Jobabo': 'JOB', 'Majibacoa': 'MAJ', 
    'Manatí': 'MNT', 'Puerto Padre': 'PPA',

    # --- Holguín ---
    'Holguín': 'HOL', 'Antilla': 'ANT', 'Báguanos': 'BAG', 
    'Banes': 'BAN', 'Cacocum': 'CAC', 'Calixto García': 'CGA', 
    'Cueto': 'CUE', 'Frank País': 'FPA', 'Gibara': 'GIB', 
    'Mayarí': 'MAY', 'Moa': 'MOA', 'Rafael Freyre': 'RFR', 
    'Sagua de Tánamo': 'STA', 'Urbano Noris': 'UNO',

    # --- Granma ---
    'Bayamo': 'BAY', 'Bartolomé Masó': 'BMA', 'Buey Arriba': 'BAR', 
    'Campechuela': 'CAM', 'Cauto Cristo': 'CCR', 'Guisa': 'GUI', 
    'Jiguaní': 'JIG', 'Manzanillo': 'MAN', 'Media Luna': 'MLU', 
    'Niquero': 'NIQ', 'Pilón': 'PIL', 'Río Cauto': 'RCA', 'Yara': 'YAR',

    # --- Santiago de Cuba ---
    'Santiago de Cuba': 'SCU', 'Contramaestre': 'CON', 'Guamá': 'GUA', 
    'Mella': 'MEL', 'Palma Soriano': 'PSO', 'San Luis': 'SLU', 
    'Segundo Frente': 'IIF', 'Songo - La Maya': 'SLM', 'Tercer Frente': 'IIIF',

    # --- Guantánamo ---
    'Guantánamo': 'GTM', 'Baracoa': 'BCA', 'Caimanera': 'CAI', 
    'El Salvador': 'ESA', 'Imías': 'IMI', 'Maisí': 'MAI', 
    'Manuel Tames': 'MTA', 'Niceto Pérez': 'NPE', 
    'San Antonio del Sur': 'SAS', 'Yateras': 'YAT',

    # --- Municipio Especial ---
    'Nueva Gerona': 'NGE'
}

def cargar_municipios(request):
    prov_id = request.GET.get('provincia')
    is_filter = request.GET.get('for_filter') 

    if prov_id:
        qs = NMunicipio.objects.filter(provincia_id=prov_id).order_by('nombre')
    else:
        qs = NMunicipio.objects.none()

    if is_filter:
        # MODO FILTRO: Enviamos nombre Y sigla
        municipios_list = []
        for m in qs:
            sigla = m.siglas or ABR_MUNICIPIOS.get(m.nombre, m.nombre[:3].upper())
            municipios_list.append({
                'id': m.id, 
                'nombre': m.nombre, # NECESARIO para el despliegue
                'sigla': sigla      # NECESARIO para la selección
            })
        
        return render(request, 'nomencladores/partials/municipios_options.html', {
            'municipios_list': municipios_list,
            'is_filter': True,
            'elem_id': 'filter_municipio_select' 
        })
    else:
        # MODO FORMULARIO (Sin cambios)
        return render(request, 'nomencladores/partials/municipios_options.html', {
            'municipios': qs, 
            'is_filter': False,
            'elem_id': 'id_municipio' 
        })
    


# Agregar estas funciones en views.py

@login_required
def eliminar_salarios_grupo(request, grupo_id):
    if request.method == "DELETE" or request.method == "POST":
        try:
            # Borrar todos los salarios asociados a este grupo escala
            count, _ = NSalario.objects.filter(grupo_escala_id=grupo_id).delete()
            
            if count > 0:
                return JsonResponse({'success': True, 'message': 'Grupo de salarios eliminado y liberado correctamente.'})
            else:
                return JsonResponse({'error': 'No se encontraron salarios para eliminar.'}, status=404)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'Método no permitido'}, status=405)



@login_required
@transaction.atomic
def editar_salarios_grupo(request, grupo_id):
    grupo = get_object_or_404(NGrupoEscala, id=grupo_id)
    salarios_existentes = NSalario.objects.filter(grupo_escala=grupo)
    
    if request.method == 'POST':
        try:
            # Replicamos la misma lógica perfecta de guardado que en la creación
            NSalario.objects.filter(grupo_escala=grupo).delete()
            
            if grupo.es_cuadro:
                monto_c = request.POST.get('salario_cuadro')
                if monto_c:
                    NSalario.objects.create(grupo_escala=grupo, rol=None, tridente=None, monto=monto_c)
            
            if grupo.tiene_rol:
                for key, value in request.POST.items():
                    if key.startswith('salario_') and value:
                        parts = key.split('_')
                        if len(parts) == 3: 
                            NSalario.objects.create(grupo_escala=grupo, rol_id=parts[1], tridente_id=parts[2], monto=value)
                            
            messages.success(request, f"Salarios del Grupo {grupo.nivel} actualizados.")
            return redirect(reverse_lazy('parametros') + '?tab=salario')
            
        except Exception as e:
            messages.error(request, f"Error al guardar: {e}")
            return redirect(reverse_lazy('parametros') + '?tab=salario')
    
    # --- GET: Preparar datos para rellenar el modal de edición ---
    form = EditarSalariosForm(initial={'grupo_nombre': str(grupo)})
    tridentes = NTridente.objects.all().order_by('tipo')
    roles = grupo.roles.all().order_by('tipo') if grupo.tiene_rol else []
    
    # Mapeamos los montos existentes
    mapa_montos = {}
    for s in salarios_existentes:
        # Si no tiene rol ni tridente, es el salario de cuadro
        if not s.rol and not s.tridente:
            mapa_montos['cuadro'] = s.monto
        else:
            # Es un salario de matriz
            r_id = s.rol.id if s.rol else 'None'
            t_id = s.tridente.id if s.tridente else 'None'
            mapa_montos[f"{r_id}_{t_id}"] = s.monto
            
    # Construimos la matriz para el HTML
    matriz_html = []
    if grupo.tiene_rol:
        for rol in roles:
            fila = {'rol': rol, 'celdas': []}
            for tridente in tridentes:
                key = f"{rol.id}_{tridente.id}"
                fila['celdas'].append({
                    'tridente_id': tridente.id,
                    'valor': mapa_montos.get(key, '') 
                })
            matriz_html.append(fila)

    return render(request, 'pages/catalogos/nsalario/edit_salario_modal.html', {
        'form': form,
        'grupo': grupo,
        'tridentes': tridentes,
        'monto_cuadro': mapa_montos.get('cuadro', ''),
        'matriz_html': matriz_html
    })


# NCARGO
class NCargoListView(ListView):
    model = NCargo
    template_name = "pages/catalogos/ncargo/list_ncargo.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = NCargoForm()
        context['cargos_sin_familia'] = NCargo.objects.filter(familia__isnull=True, activo=True)
        context['familias'] = NFamiliaCargo.objects.prefetch_related('cargos').all().order_by('-id')
        return context
    
class NCargoCreateView(CreateView):
    model = NCargo
    form_class = NCargoForm
    template_name = "pages/catalogos/ncargo/add_ncargo.html"
    success_url = reverse_lazy('list_ncargo')

class NCargoUpdateView(UpdateView):
    model = NCargo
    form_class = NCargoForm
    template_name = 'pages/catalogos/ncargo/updt_ncargo.html'
    success_url = reverse_lazy('list_ncargo')

class NCargoDeleteView(DeleteView):
    def get(self, request, *args, **kwargs):
        cargo = get_object_or_404(NCargo, id=kwargs['pk'])
        cargo.delete()
        return redirect('list_ncargo')
    

class NMunicipioInline(admin.TabularInline):
    model = NMunicipio
    extra = 1
    fields = ('nombre',)
    show_change_link = True

#@admin.register(NProvincia)
#class NProvinciaAdmin(admin.ModelAdmin):
 #   list_display = ('id', 'nombre')
  #  search_fields = ('nombre',)
   # inlines = [NMunicipioInline]

#@admin.register(NMunicipio)
#class NMunicipioAdmin(admin.ModelAdmin):
 #   list_display = ('id', 'nombre', 'provincia')
  #  list_filter = ('provincia',)
   # search_fields = ('nombre',)



#SALARIOS
@login_required
@transaction.atomic
def crear_salarios_por_grupo(request):
    if request.method == 'POST':
        grupo_id = request.POST.get('grupo_escala')
        grupo = get_object_or_404(NGrupoEscala, id=grupo_id)
        
        NSalario.objects.filter(grupo_escala=grupo).delete()
        
        if grupo.es_cuadro:
            monto_c = request.POST.get('salario_cuadro')
            if monto_c:
                NSalario.objects.create(grupo_escala=grupo, rol=None, tridente=None, monto=monto_c)
        
        if grupo.tiene_rol:
            for key, value in request.POST.items():
                if key.startswith('salario_') and value:
                    parts = key.split('_')
                    if len(parts) == 3:
                        NSalario.objects.create(grupo_escala=grupo, rol_id=parts[1], tridente_id=parts[2], monto=value)
        
        messages.success(request, f"Configuración salarial del Grupo {grupo.nivel} guardada correctamente.")
        return redirect(reverse_lazy('parametros') + '?tab=salario')
    
    # --- RESPUESTA GET REPARADA E INTELIGENTE ---
    form = RegistrarSalariosForm()
    
    # 1. ORDENAR ROLES PERSONALIZADO: Decisorio, Fundamental, Apoyo
    roles_db = NRol.objects.all()
    orden_deseado = {"Decisorio": 1, "Fundamental": 2, "Apoyo": 3}
    # Ordenamos usando el diccionario. Si hay uno nuevo, se va al final (4)
    roles = sorted(roles_db, key=lambda r: orden_deseado.get(r.tipo, 4))
    
    tridentes = NTridente.objects.all().order_by('tipo')
    
    # 2. MAPA SÚPER INTELIGENTE (Ahora incluye los roles permitidos)
    grupos_info = {}
    for g in NGrupoEscala.objects.prefetch_related('roles'):
        grupos_info[g.id] = {
            'es_cuadro': g.es_cuadro,
            'tiene_rol': g.tiene_rol,
            # Extraemos los IDs de los roles que tú le marcaste a este grupo
            'roles_permitidos': list(g.roles.values_list('id', flat=True)) 
        }
    
    return render(request, 'pages/catalogos/nsalario/add_salario.html', {
        'form': form,
        'roles': roles,
        'tridentes': tridentes,
        'grupos_json': json.dumps(grupos_info)
    })

def obtener_grupo(request, id):
    grupo = get_object_or_404(NGrupoEscala, id=id)
    return JsonResponse({'es_cuadro': grupo.es_cuadro})

def tabla_salarios_modal(request):
    grupo_id = request.GET.get('grupo_escala')
    if not grupo_id:
        return HttpResponse("")
    
    grupo = get_object_or_404(NGrupoEscala, id=grupo_id)
    tridentes = NTridente.objects.all().order_by('tipo')
    
    # Pasamos los roles SOLO si el grupo tiene la bandera encendida
    roles = grupo.roles.all().order_by('tipo') if grupo.tiene_rol else []
    
    return render(request, 'nomencladores/partials/tabla_salarios_dinamica.html', {
        'grupo': grupo,
        'roles': roles,
        'tridentes': tridentes,
    })

def cargar_esp(request):
    nivel = request.GET.get('nivel_educ')
    
    is_filter = request.GET.get('for_filter') == '1'

    

    if nivel == 'NS':
        # Nivel Superior
        list_esp = NEspecialidad.objects.filter(educ_superior=True)
    elif nivel == 'TM':
        # Medio Superior TM (Excluye MS/DG que es educ_superior=False pero no lleva especialidad en filtro)
        list_esp = NEspecialidad.objects.filter(educ_superior=False)
    else:
        # Cualquier otro nivel devuelve vacío
        list_esp = NEspecialidad.objects.none()
    
    return render(request, 'pages/catalogos/nespecialidad/esp_opt.html', {
        'list_esp': list_esp,
        'is_filter': is_filter
    })

#TRIDENTE
# CREATE
@csrf_exempt
@require_POST
def tridente_create(request):
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NTridente.objects.create(tipo=tipo)
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo})

# UPDATE
@csrf_exempt
@require_http_methods(["PUT"])
def tridente_update(request, pk):
    obj = NTridente.objects.get(pk=pk)
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.tipo = tipo
    obj.save()
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo})

# DELETE
@csrf_exempt
@require_http_methods(["DELETE"])
def tridente_delete(request, pk):
    NTridente.objects.get(pk=pk).delete()
    return JsonResponse({'success': True})

# ---------- CRUD NRol ----------
@csrf_exempt
@require_http_methods(["POST"])
def rol_create(request):
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    
    if not tipo: 
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
        
    # Ya no pasamos el es_cuadro
    obj = NRol.objects.create(tipo=tipo)
    
    # Devolvemos solo lo que existe
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo})

@csrf_exempt
@require_http_methods(["PUT"])
def rol_update(request, pk):
    obj = get_object_or_404(NRol, pk=pk)
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    
    if not tipo: 
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
        
    obj.tipo = tipo
    # Eliminamos obj.es_cuadro = data.get('es_cuadro')
    obj.save()
    
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo})

@csrf_exempt
@require_http_methods(["DELETE"])
def rol_delete(request, pk):
    NRol.objects.get(pk=pk).delete()
    return JsonResponse({'success': True})

# ---------- CRUD NGrupoEscala ----------
@csrf_exempt
@require_POST
def grupo_create(request):
    data = json.loads(request.body)
    nivel = data.get('nivel', '').strip()

    if not nivel:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    try:
        obj = NGrupoEscala.objects.create(nivel=nivel.upper())
        return JsonResponse({'id': obj.id, 'nivel': obj.nivel})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["PUT"])
def grupo_update(request, pk):
    obj = NGrupoEscala.objects.get(pk=pk)
    data = json.loads(request.body)
    nivel = data.get('nivel', '').strip()

    if not nivel:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    try:
        obj.nivel = nivel.upper()
        obj.save()
        return JsonResponse({'id': obj.id, 'nivel': obj.nivel})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["DELETE"])
def grupo_delete(request, pk):
    try:
        NGrupoEscala.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NGrupoEscala.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

# ---------- CRUD NProvincia ----------
def _buscar_coincidencia_siglas(siglas, excluir_provincia_id=None, excluir_municipio_id=None):
    """
    Busca si unas siglas ya están en uso, en Provincia o Municipio.
    Devuelve un texto descriptivo de la coincidencia, o None si no hay ninguna.
    """
    if not siglas:
        return None

    q_prov = NProvincia.objects.filter(siglas__iexact=siglas)
    if excluir_provincia_id:
        q_prov = q_prov.exclude(pk=excluir_provincia_id)
    coincidencia = q_prov.first()
    if coincidencia:
        return f'la provincia "{coincidencia.nombre}"'

    q_mun = NMunicipio.objects.filter(siglas__iexact=siglas)
    if excluir_municipio_id:
        q_mun = q_mun.exclude(pk=excluir_municipio_id)
    coincidencia = q_mun.first()
    if coincidencia:
        return f'el municipio "{coincidencia.nombre}"'

    return None

def verificar_siglas(request):
    """
    Comprueba si unas siglas ya están en uso, SIN guardar nada.
    Se llama mientras el usuario escribe, para dar feedback en vivo.
    """
    siglas = request.GET.get('siglas', '').strip().upper()
    excluir_provincia_id = request.GET.get('excluir_provincia_id')
    excluir_municipio_id = request.GET.get('excluir_municipio_id')

    if not siglas or len(siglas) != 3 or not siglas.isalpha():
        return JsonResponse({'coincidencia': None})

    coincidencia = _buscar_coincidencia_siglas(
        siglas,
        excluir_provincia_id=excluir_provincia_id,
        excluir_municipio_id=excluir_municipio_id
    )
    return JsonResponse({'coincidencia': coincidencia})


@csrf_exempt
@require_POST
def provincia_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    siglas = data.get('siglas', '').strip().upper()

    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    if siglas and (len(siglas) != 3 or not siglas.isalpha()):
        return JsonResponse({'error': 'Las siglas deben tener exactamente 3 letras.'}, status=400)

    obj = NProvincia.objects.create(nombre=nombre.title(), siglas=siglas or None)

    coincidencia = _buscar_coincidencia_siglas(siglas, excluir_provincia_id=obj.pk)

    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'siglas': obj.siglas or '',
        'coincidencia': coincidencia,
    })

@csrf_exempt
@require_http_methods(["PUT"])
def provincia_update(request, pk):
    obj = NProvincia.objects.get(pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    siglas = data.get('siglas', '').strip().upper()

    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    if siglas and (len(siglas) != 3 or not siglas.isalpha()):
        return JsonResponse({'error': 'Las siglas deben tener exactamente 3 letras.'}, status=400)

    obj.nombre = nombre.title()
    obj.siglas = siglas or None
    obj.save()

    coincidencia = _buscar_coincidencia_siglas(siglas, excluir_provincia_id=obj.pk)

    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'siglas': obj.siglas or '',
        'coincidencia': coincidencia,
    })

@csrf_exempt
@require_http_methods(["DELETE"])
def provincia_delete(request, pk):
    try:
        NProvincia.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NProvincia.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

# ---------- CRUD NMunicipio ----------
@csrf_exempt
@require_POST
def municipio_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    provincia_id = data.get('provincia_id')
    siglas = data.get('siglas', '').strip().upper()

    if not nombre or not provincia_id:
        return JsonResponse({'error': 'Campos obligatorios'}, status=400)

    if siglas and (len(siglas) != 3 or not siglas.isalpha()):
        return JsonResponse({'error': 'Las siglas deben tener exactamente 3 letras.'}, status=400)

    provincia = get_object_or_404(NProvincia, pk=provincia_id)
    obj = NMunicipio.objects.create(nombre=nombre.title(), provincia=provincia, siglas=siglas or None)

    coincidencia = _buscar_coincidencia_siglas(siglas, excluir_municipio_id=obj.pk)

    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'provincia_id': obj.provincia_id,
        'siglas': obj.siglas or '',
        'coincidencia': coincidencia,
    })

@csrf_exempt
@require_http_methods(["PUT"])
def municipio_update(request, pk):
    obj = NMunicipio.objects.get(pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    siglas = data.get('siglas', '').strip().upper()

    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    if siglas and (len(siglas) != 3 or not siglas.isalpha()):
        return JsonResponse({'error': 'Las siglas deben tener exactamente 3 letras.'}, status=400)

    obj.nombre = nombre.title()
    obj.siglas = siglas or None
    obj.save()

    coincidencia = _buscar_coincidencia_siglas(siglas, excluir_municipio_id=obj.pk)

    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'siglas': obj.siglas or '',
        'coincidencia': coincidencia,
    })

@csrf_exempt
@require_http_methods(["DELETE"])
def municipio_delete(request, pk):
    try:
        NMunicipio.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NMunicipio.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

# ---------- CRUD NHorario ----------
@csrf_exempt
@require_POST
def horario_create(request):
    import json
    from datetime import datetime
    from django.http import JsonResponse
    from nomencladores.models import NHorario

    data = json.loads(request.body)
    desc = data.get('descripcion', '').strip()
    ini  = data.get('hora_inicio', '').strip()
    fin  = data.get('hora_fin', '').strip()

    if not desc or not ini or not fin:
        return JsonResponse({'error': 'Complete todos los campos'}, status=400)

    try:
        ini_time = datetime.strptime(ini, '%H:%M').time()
        fin_time = datetime.strptime(fin, '%H:%M').time()
    except ValueError:
        return JsonResponse({'error': 'Formato de hora inválido, use HH:MM'}, status=400)

    obj = NHorario.objects.create(descripcion=desc.title(),
                                  hora_inicio=ini_time,
                                  hora_fin=fin_time)
    return JsonResponse({'id': obj.id,
                         'descripcion': obj.descripcion,
                         'hora_inicio': obj.hora_inicio.strftime('%H:%M'),
                         'hora_fin': obj.hora_fin.strftime('%H:%M')})


@csrf_exempt
@require_http_methods(["PUT"])
def horario_update(request, pk):
    import json
    from datetime import datetime
    from django.http import JsonResponse
    from django.shortcuts import get_object_or_404
    from nomencladores.models import NHorario

    obj = get_object_or_404(NHorario, pk=pk)
    data = json.loads(request.body)
    desc = data.get('descripcion', '').strip()
    ini  = data.get('hora_inicio', '').strip()
    fin  = data.get('hora_fin', '').strip()

    if not desc or not ini or not fin:
        return JsonResponse({'error': 'Complete todos los campos'}, status=400)

    try:
        ini_time = datetime.strptime(ini, '%H:%M').time()
        fin_time = datetime.strptime(fin, '%H:%M').time()
    except ValueError:
        return JsonResponse({'error': 'Formato de hora inválido, use HH:MM'}, status=400)

    obj.descripcion = desc.title()
    obj.hora_inicio = ini_time
    obj.hora_fin = fin_time
    obj.save()

    return JsonResponse({
        'id': obj.id,
        'descripcion': obj.descripcion,
        # PROTECCIÓN: Si existe la hora, la formatea. Si no, devuelve null (None)
        'hora_inicio': obj.hora_inicio.strftime('%H:%M') if obj.hora_inicio else None,
        'hora_fin': obj.hora_fin.strftime('%H:%M') if obj.hora_fin else None
    })

@csrf_exempt
@require_http_methods(["DELETE"])
def horario_delete(request, pk):
    try:
        horario = NHorario.objects.get(pk=pk)
        horario.delete()
        return JsonResponse({'success': True})
    except NHorario.DoesNotExist:
        return JsonResponse({'error': 'Horario no encontrado'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar: el horario está siendo usado en jornadas'}, status=409)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ---------- CRUD NJornada ----------
@csrf_exempt
@require_POST
def jornada_create(request):
    data = json.loads(request.body)
    tipo    = data.get('tipo', '').strip()
    horario = data.get('horario', '').strip() or None
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NJornada.objects.create(tipo=tipo.title(), horario_id=horario if horario else None)
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo,
                         'horario': obj.horario.descripcion if obj.horario else None})

@csrf_exempt
@require_http_methods(["PUT"])
def jornada_update(request, pk):
    obj = NJornada.objects.get(pk=pk)
    data = json.loads(request.body)
    tipo    = data.get('tipo', '').strip()
    horario = data.get('horario', '').strip() or None
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.tipo = tipo.title()
    obj.horario_id = horario if horario else None
    obj.save()
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo,
                         'horario': obj.horario.descripcion if obj.horario else None})


@csrf_exempt
@require_http_methods(["DELETE"])
def jornada_delete(request, pk):
    try:
        jornada = NJornada.objects.get(pk=pk)
        jornada.delete()
        return JsonResponse({'success': True})
    except NJornada.DoesNotExist:
        return JsonResponse({'error': 'Jornada no encontrada'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar: la jornada está siendo usada en altas de personal'}, status=409)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ---------- CRUD NCausaAltaBaja ----------
@csrf_exempt
@require_POST
def causa_create(request):
    data = json.loads(request.body)
    desc = data.get('descripcion', '').strip()
    alta = data.get('alta', False)
    if not desc:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NCausaAltaBaja.objects.create(descripcion=desc.title(), alta=alta)
    return JsonResponse({'id': obj.id, 'descripcion': obj.descripcion,
                         'alta': obj.alta})

@csrf_exempt
@require_http_methods(["PUT"])
def causa_update(request, pk):
    obj = NCausaAltaBaja.objects.get(pk=pk)
    data = json.loads(request.body)
    desc = data.get('descripcion', '').strip()
    alta = data.get('alta', False)
    if not desc:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.descripcion = desc.title()
    obj.alta = alta
    obj.save()
    return JsonResponse({'id': obj.id, 'descripcion': obj.descripcion,
                         'alta': obj.alta})

@csrf_exempt
@require_http_methods(["DELETE"])
def causa_delete(request, pk):
    try:
        NCausaAltaBaja.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NCausaAltaBaja.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

# ---------- CRUD NCondicionLaboralAnormal ----------
@csrf_exempt
@require_POST
def condicion_create(request):
    try:
        data = json.loads(request.body)
        print("📥 tarifa_hora recibido (CREATE):", data.get('tarifa_hora'))
        print("📥 tipo de tarifa_hora (CREATE):", type(data.get('tarifa_hora')))
        nombre = data.get('nombre', '').strip()
        # 🔥 Convertir a Decimal y redondear a 2 decimales
        tarifa = Decimal(data.get('tarifa_hora', '0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        noct_id = data.get('nocturnidad_id')

        if not nombre:
            return JsonResponse({'error': 'Campo obligatorio'}, status=400)
        
        obj = NCondicionLaboralAnormal(nombre=nombre.title(), tarifa_hora=tarifa)
        if noct_id:
            obj.nocturnidad_id = noct_id
            
        obj.full_clean() 
        obj.save()
        
        return JsonResponse({'id': obj.id, 'nombre': obj.nombre, 'tarifa_hora': str(obj.tarifa_hora)})
    except ValidationError as e:
        error_msg = e.message_dict.get('nocturnidad', [str(e)])[0] if hasattr(e, 'message_dict') and 'nocturnidad' in e.message_dict else str(e)
        return JsonResponse({'error': error_msg}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_POST
@login_required
def nocturnidad_create(request):
    try:
        data = json.loads(request.body)
        codigo = data.get('codigo', '').strip().upper()
        h_inicio = data.get('hora_inicio')
        h_fin = data.get('hora_fin')
        n_id = data.get('id')

        if not codigo or not h_inicio or not h_fin:
            return JsonResponse({'error': 'Todos los campos son obligatorios'}, status=400)

        if n_id:
            obj = get_object_or_404(NNocturnidad, pk=n_id)
            if NNocturnidad.objects.filter(codigo=codigo).exclude(pk=n_id).exists():
                return JsonResponse({'error': f'El código {codigo} ya existe.'}, status=400)
            obj.codigo = codigo
            obj.hora_inicio = h_inicio
            obj.hora_fin = h_fin
            obj.save()
        else:
            if NNocturnidad.objects.filter(codigo=codigo).exists():
                return JsonResponse({'error': f'El código {codigo} ya existe.'}, status=400)
            obj = NNocturnidad.objects.create(codigo=codigo, hora_inicio=h_inicio, hora_fin=h_fin)

        # ----------------------------------------------------------------
        # LA SOLUCIÓN: Refresca el objeto desde PostgreSQL para que 
        # los strings "23:00" se conviertan en verdaderos objetos Time.
        # ----------------------------------------------------------------
        obj.refresh_from_db()

        return JsonResponse({
            'id': obj.id, 
            'codigo': obj.codigo, 
            'horas': obj.horas
        })
    except Exception as e:
        # Imprimimos el error exacto en consola por si falla otra cosa
        print(f"Error en nocturnidad_create: {e}") 
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def nocturnidad_delete(request, pk):
    try:
        NNocturnidad.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except ProtectedError:
        return JsonResponse({'error': 'No se puede eliminar. Está en uso.'}, status=400)

@csrf_exempt
@require_http_methods(["PUT"])
def condicion_update(request, pk):
    try:
        obj = get_object_or_404(NCondicionLaboralAnormal, pk=pk)
        data = json.loads(request.body)

        print("📥 tarifa_hora recibido:", data.get('tarifa_hora'))
        print("📥 tipo de tarifa_hora:", type(data.get('tarifa_hora')))

        nombre = data.get('nombre', '').strip()
        # 🔥 Convertir a Decimal y redondear a 2 decimales
        tarifa = Decimal(data.get('tarifa_hora', '0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        noct_id = data.get('nocturnidad_id')

        if not nombre:
            return JsonResponse({'error': 'Campo obligatorio'}, status=400)
            
        obj.nombre = nombre.title()
        obj.tarifa_hora = tarifa
        obj.nocturnidad_id = noct_id if noct_id else None
        
        obj.full_clean() 
        obj.save()
        
        return JsonResponse({'id': obj.id, 'nombre': obj.nombre, 'tarifa_hora': str(obj.tarifa_hora)})
    except ValidationError as e:
        error_msg = e.message_dict.get('nocturnidad', [str(e)])[0] if hasattr(e, 'message_dict') and 'nocturnidad' in e.message_dict else str(e)
        return JsonResponse({'error': error_msg}, status=400)
    except Exception as e:
        print("❌ Error en backend:", str(e))
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def condicion_delete(request, pk):
    try:
        NCondicionLaboralAnormal.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NCondicionLaboralAnormal.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar. Esta condición está siendo usada por uno o más contratos.'}, status=400)

# ---------- CRUD NEspecialidad ----------
@csrf_exempt
@require_POST
def especialidad_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    educ_sup = data.get('educ_superior', False)
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NEspecialidad.objects.create(
        nombre=nombre.title(),
        educ_superior=educ_sup
    )
    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'educ_superior': obj.educ_superior
    })

@csrf_exempt
@require_http_methods(["PUT"])
def especialidad_update(request, pk):
    obj = get_object_or_404(NEspecialidad, pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    educ_sup = data.get('educ_superior', False)
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.nombre = nombre.title()
    obj.educ_superior = educ_sup
    obj.save()
    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'educ_superior': obj.educ_superior
    })

@csrf_exempt
@require_http_methods(["DELETE"])
def especialidad_delete(request, pk):
    try:
        NEspecialidad.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NEspecialidad.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

# ---------- CRUD NCargo API ----------
@csrf_exempt
@require_POST
def cargo_create(request):
    data = json.loads(request.body)
    descripcion = data.get('descripcion', '').strip()
    cat_ocupacional = data.get('cat_ocupacional', '').strip()
    grupo_escala_id = data.get('grupo_escala_id')
    salario_basico = data.get('salario_basico', 0)
    puesto_clave = data.get('puesto_clave', False) # <-- 1. Atrapamos el dato del JS

    if not descripcion or not cat_ocupacional or not grupo_escala_id:
        return JsonResponse({'error': 'Complete todos los campos obligatorios'}, status=400)

    try:
        grupo = NGrupoEscala.objects.get(pk=grupo_escala_id)
        obj = NCargo.objects.create(
            descripcion=descripcion,
            cat_ocupacional=cat_ocupacional,
            grupo_escala=grupo,
            salario_basico=float(salario_basico),
            puesto_clave=puesto_clave
        )
        return JsonResponse({
            'id': obj.id,
            'descripcion': obj.descripcion,
            'cat_ocupacional': obj.get_cat_ocupacional_display(),
            'cat_ocupacional_value': obj.cat_ocupacional,
            'grupo_escala': obj.grupo_escala.nivel,
            'salario_basico': str(obj.salario_basico)
        })
    except NGrupoEscala.DoesNotExist:
        return JsonResponse({'error': 'Grupo de escala no encontrado'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["PUT"])
def cargo_update(request, pk):
    try:
        obj = NCargo.objects.get(pk=pk)
        data = json.loads(request.body)
        descripcion = data.get('descripcion', '').strip()
        cat_ocupacional = data.get('cat_ocupacional', '').strip()
        grupo_escala_id = data.get('grupo_escala_id')
        salario_basico = data.get('salario_basico', 0)
        puesto_clave = data.get('puesto_clave', False) # <-- 1. Atrapamos el dato

        if not descripcion or not cat_ocupacional or not grupo_escala_id:
            return JsonResponse({'error': 'Complete todos los campos obligatorios'}, status=400)

        grupo = NGrupoEscala.objects.get(pk=grupo_escala_id)
        obj.descripcion = descripcion
        obj.cat_ocupacional = cat_ocupacional
        obj.grupo_escala = grupo
        obj.salario_basico = float(salario_basico)
        obj.puesto_clave = puesto_clave                # <-- 2. Actualizamos la BD
        obj.save()

        return JsonResponse({
            'id': obj.id,
            'descripcion': obj.descripcion,
            'cat_ocupacional': obj.get_cat_ocupacional_display(),
            'cat_ocupacional_value': obj.cat_ocupacional,
            'grupo_escala': obj.grupo_escala.nivel,
            'salario_basico': str(obj.salario_basico)
        })
    except NCargo.DoesNotExist:
        return JsonResponse({'error': 'Cargo no encontrado'}, status=404)
    except NGrupoEscala.DoesNotExist:
        return JsonResponse({'error': 'Grupo de escala no encontrado'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["DELETE"])
def cargo_delete(request, pk):
    try:
        # Buscamos el cargo
        cargo = NCargo.objects.get(pk=pk)
        
        # Intentamos eliminar
        cargo.delete()
        
        return JsonResponse({'success': True})

    except NCargo.DoesNotExist:
        return JsonResponse({'error': 'El cargo no existe.'}, status=404)

    except RestrictedError:
        # Capturamos el bloqueo de seguridad de Django
        return JsonResponse({
            'error': 'No se puede eliminar: Este Nomenclador está siendo usado en la Plantilla de Cargos o tiene históricos asociados.'
        }, status=409) # 409 Conflict

    except Exception as e:
        # Capturamos cualquier otro error inesperado
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)


@csrf_exempt
@require_POST
@login_required
def api_familia_create(request):
    """Crea una nueva familia vinculada a un Tipo de Familia"""
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        tipo_id = data.get('tipo_familia_id')
        
        if not nombre or not tipo_id:
            return JsonResponse({'error': 'Nombre y Tipo son obligatorios'}, status=400)
        
        tipo_familia = get_object_or_404(NTipoFamilia, pk=tipo_id)
        familia = NFamiliaCargo.objects.create(nombre=nombre, tipo_familia=tipo_familia)
        return JsonResponse({'id': familia.id, 'nombre': familia.nombre})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    
@csrf_exempt
@require_POST
@login_required
def api_familia_update(request, pk):
    """Actualiza el nombre de una familia"""
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        if not nombre:
            return JsonResponse({'error': 'El nombre es obligatorio'}, status=400)
        
        familia = get_object_or_404(NFamiliaCargo, pk=pk)
        familia.nombre = nombre
        familia.save()
        return JsonResponse({'success': True, 'nombre': familia.nombre})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_POST
@login_required
def api_familia_delete(request, pk):
    """Elimina una familia (las relaciones M2M se eliminan automáticamente)"""
    try:
        familia = get_object_or_404(NFamiliaCargo, pk=pk)
        familia.delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    

@csrf_exempt
@require_POST
@login_required
def api_cargo_move(request):
    """Mueve un cargo entre familias respetando el contexto del Tipo de Familia"""
    try:
        data = json.loads(request.body)
        cargo_id = data.get('cargo_id')
        familia_id = data.get('familia_id') # Puede ser None (para desasignar)
        tipo_id = data.get('tipo_familia_id')

        cargo = get_object_or_404(NCargo, pk=cargo_id)
        tipo = get_object_or_404(NTipoFamilia, pk=tipo_id)
        
        # 1. Quitar el cargo de cualquier familia que sea del MISMO TIPO actual
        familias_del_tipo = cargo.familias.filter(tipo_familia=tipo)
        cargo.familias.remove(*familias_del_tipo)
        
        # 2. Si se movió a una familia (no a la lista de pendientes), añadir la nueva
        if familia_id:
            nueva_familia = get_object_or_404(NFamiliaCargo, pk=familia_id)
            cargo.familias.add(nueva_familia)
            
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    
@login_required
def api_get_contexto_familias(request):
    """Devuelve el fragmento HTML de familias y cargos pendientes según el Tipo seleccionado"""
    tipo_id = request.GET.get('tipo_id')
    if not tipo_id:
        return HttpResponse('<div class="text-center p-5">Seleccione un Tipo de Familia</div>')
    
    tipo = get_object_or_404(NTipoFamilia, pk=tipo_id)
    familias = NFamiliaCargo.objects.filter(tipo_familia=tipo).prefetch_related('cargos').order_by('-id')
    
    # Cargos que NO están en ninguna familia DE ESTE TIPO
    cargos_pendientes = NCargo.objects.exclude(familias__tipo_famil=tipo).order_by('descripcion')
    
    return render(request, 'pages/config/partials/familias_content.html', {
        'familias': familias,
        'cargos_sin_familia': cargos_pendientes,
    })
    

# ---------- CRUD NNivelPreparacion ----------
@csrf_exempt
@require_POST
def nivel_preparacion_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    
    obj = NNivelPreparacion.objects.create(nombre=nombre.title())
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre})

@csrf_exempt
@require_http_methods(["PUT"])
def nivel_preparacion_update(request, pk):
    obj = get_object_or_404(NNivelPreparacion, pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    
    obj.nombre = nombre.title()
    obj.save()
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre})

@csrf_exempt
@require_http_methods(["DELETE"])
def nivel_preparacion_delete(request, pk):
    try:
        NNivelPreparacion.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NNivelPreparacion.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar porque está en uso.'}, status=409)
    


# ---------- CRUD Tipo de Contrato ----------
@csrf_exempt
@require_POST
def tipo_contrato_create(request):
    data = json.loads(request.body)
    descripcion = data.get('nombre', '').strip() 
    ocupa_plaza = data.get('ocupa_plaza', False)
    requiere_motivo = data.get('requiere_motivo', False)
    es_adiestrado = data.get('es_adiestrado', False)
    
    if not descripcion:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    
    obj = NTipoContrato.objects.create(
        descripcion=descripcion.title(), 
        ocupa_plaza=ocupa_plaza,
        requiere_motivo=requiere_motivo,
        es_adiestrado=es_adiestrado
    )
    return JsonResponse({
        'id': obj.id, 'nombre': obj.descripcion, 
        'ocupa_plaza': obj.ocupa_plaza, 'requiere_motivo': obj.requiere_motivo
    })

@csrf_exempt
@require_http_methods(["PUT"])
def tipo_contrato_update(request, pk):
    obj = get_object_or_404(NTipoContrato, pk=pk)
    data = json.loads(request.body)
    descripcion = data.get('nombre', '').strip()
    
    if not descripcion:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    
    obj.descripcion = descripcion.title()
    # Los switches se guardan solos con sus funciones toggle, así que solo editamos el nombre
    obj.save()
    
    return JsonResponse({'id': obj.id, 'nombre': obj.descripcion})

@csrf_exempt
@require_http_methods(["DELETE"])
def tipo_contrato_delete(request, pk):
    try:
        obj = NTipoContrato.objects.get(pk=pk)
        obj.delete()
        return JsonResponse({'success': True})
    except NTipoContrato.DoesNotExist:
        return JsonResponse({'error': 'El tipo de contrato ya no existe o fue eliminado.'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar porque está siendo usado en un contrato real.'}, status=409)
    except Exception as e:
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)

@csrf_exempt
@require_POST
def tipo_contrato_toggle_plaza(request, pk):
    obj = get_object_or_404(NTipoContrato, pk=pk)
    data = json.loads(request.body)
    obj.ocupa_plaza = data.get('ocupa_plaza', False)
    obj.save()
    return JsonResponse({'success': True})

@csrf_exempt
@require_POST
def tipo_contrato_toggle_motivo(request, pk):
    obj = get_object_or_404(NTipoContrato, pk=pk)
    data = json.loads(request.body)
    obj.requiere_motivo = data.get('requiere_motivo', False)
    obj.save()
    return JsonResponse({'success': True})

# ---------- CRUD Motivo de Contrato ----------
@csrf_exempt
@require_POST
def motivo_contrato_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    tipo_id = data.get('tipo_contrato_id')
    
    if not nombre or not tipo_id: 
        return JsonResponse({'error': 'Nombre y Tipo de Contrato son obligatorios'}, status=400)

    descripcion = nombre.title()

    # No se permite el mismo motivo dentro del mismo tipo de contrato
    if NMotivoContrato.objects.filter(descripcion__iexact=descripcion, tipo_contrato_id=tipo_id).exists():
        return JsonResponse(
            {'error': f'El motivo "{descripcion}" ya existe para este tipo de contrato.'},
            status=400
        )

    obj = NMotivoContrato.objects.create(descripcion=descripcion, tipo_contrato_id=tipo_id)
    return JsonResponse({'id': obj.id, 'nombre': obj.descripcion})

@csrf_exempt
@require_http_methods(["PUT"])
def motivo_contrato_update(request, pk):
    obj = get_object_or_404(NMotivoContrato, pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    tipo_id = data.get('tipo_contrato_id')
    
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    descripcion = nombre.title()
    # Si no llega tipo en la edición, conservamos el que ya tenía
    tipo_destino = tipo_id if tipo_id else obj.tipo_contrato_id

    # No se permite chocar con OTRO motivo del mismo tipo
    duplicado = NMotivoContrato.objects.filter(
        descripcion__iexact=descripcion,
        tipo_contrato_id=tipo_destino
    ).exclude(pk=obj.pk).exists()

    if duplicado:
        return JsonResponse(
            {'error': f'El motivo "{descripcion}" ya existe para este tipo de contrato.'},
            status=400
        )

    obj.descripcion = descripcion
    obj.tipo_contrato_id = tipo_destino
    obj.save()

    return JsonResponse({'id': obj.id, 'nombre': obj.descripcion})

@csrf_exempt
@require_http_methods(["DELETE"])
def motivo_contrato_delete(request, pk):
    try:
        obj = NMotivoContrato.objects.get(pk=pk)
        obj.delete()
        return JsonResponse({'success': True})
    except NMotivoContrato.DoesNotExist:
        return JsonResponse({'error': 'El motivo de contrato ya no existe o fue eliminado.'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar porque está siendo usado en un contrato real.'}, status=409)
    except Exception as e:
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)

@csrf_exempt
def tipo_contrato_info(request, pk):
    try:
        tc = NTipoContrato.objects.get(pk=pk)
        # Buscamos solo los motivos que pertenecen a este tipo de contrato específico
        motivos = list(NMotivoContrato.objects.filter(tipo_contrato=tc).values('id', 'descripcion'))
        
        return JsonResponse({
            'descripcion': tc.descripcion,
            'requiere_motivo': tc.requiere_motivo,
            'motivos_asociados': motivos  # <-- El frontend usará esto
        })
    except NTipoContrato.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    
@csrf_exempt
@require_POST
def toggle_tipo_adiestrado(request, pk):
    obj = get_object_or_404(NTipoContrato, pk=pk)
    data = json.loads(request.body)
    obj.es_adiestrado = data.get('es_adiestrado', False)
    obj.save()
    return JsonResponse({'success': True})

def grupo_escala_modal(request, pk=None):
    """Devuelve el HTML del formulario para el modal (Crear o Editar)"""
    instance = get_object_or_404(NGrupoEscala, pk=pk) if pk else None
    form = NGrupoEscalaForm(instance=instance)
    
    return render(request, 'nomencladores/partials/modal_grupo_form.html', {
        'form': form,
        'instance': instance
    })

@require_POST
def grupo_escala_save(request, pk=None):
    instance = get_object_or_404(NGrupoEscala, pk=pk) if pk else None
    form = NGrupoEscalaForm(request.POST, instance=instance)

    if form.is_valid():
        grupo = form.save()
        return JsonResponse({
            'success': True,
            'grupo': {
                'id': grupo.id,
                'nivel': grupo.nivel,
                'es_cuadro': grupo.es_cuadro,
                'tiene_rol': grupo.tiene_rol,
            }
        })

    return JsonResponse({'success': False, 'errors': form.errors.as_json()}, status=400)

def grupos_escala_tabla_parcial(request):
    """Devuelve solo la tabla de Grupos Escala (para refrescar sin recargar la página)."""
    from operator import attrgetter
    from django.core.paginator import Paginator

    grupos_todos = sorted(NGrupoEscala.objects.all(), key=attrgetter('valor_numerico'))
    page_number = request.GET.get('page_grupos', 1)
    paginator = Paginator(grupos_todos, 5)
    grupos = paginator.get_page(page_number)

    return render(request, 'pages/config/partials/tabla_grupos.html', {'grupos': grupos})

@login_required
def municipios_provincia_tabla(request, prov_id):
    # Buscamos los municipios de esa provincia específica
    municipios = NMunicipio.objects.filter(provincia_id=prov_id).order_by('nombre')
    
    # Devolvemos un pequeño HTML solo con las filas de la tabla
    return render(request, 'nomencladores/partials/municipios_table_rows.html', {
        'municipios_filtrados': municipios
    })

@require_POST
@login_required
def guardar_tipo_unidad(request):
    tipo_id = request.POST.get('id')
    instance = get_object_or_404(NTipoUnidadOrganizativa, id=tipo_id) if tipo_id else None
    
    # Capturamos el padre que envía el selector del modal
    padre_id = request.POST.get('tipo_padre_id') 
    
    form = NTipoUnidadOrganizativaForm(request.POST, instance=instance)
    
    if form.is_valid():
        tipo = form.save(commit=False)
        
        # REGLA 1: Si es subunidad, obligatoriamente hereda el color y el padre
        if tipo.es_subunidad and padre_id:
            try:
                padre = NTipoUnidadOrganizativa.objects.get(id=padre_id)
                tipo.tipo_padre = padre
                tipo.color = padre.color
            except NTipoUnidadOrganizativa.DoesNotExist:
                pass
                
        # REGLA 2: Si NO es subunidad (es Principal o Normal), NO puede tener padre.
        # El color lo tomará directamente del formulario (request.POST).
        elif not tipo.es_subunidad:
            tipo.tipo_padre = None
        
        tipo.save()
        
        return JsonResponse({
            'success': True,
            'tipo': {
                'id': tipo.id,
                'descripcion': tipo.descripcion,
                'es_temporal': tipo.es_temporal,
                'es_principal': tipo.es_principal,
                'es_subunidad': tipo.es_subunidad,
                'color': tipo.color or '',
                'tipo_padre_id': tipo.tipo_padre_id if tipo.tipo_padre else '' 
            }
        })
    
    # Si falla, mandamos los errores del form
    return JsonResponse({'success': False, 'error': "Revise los datos. Es posible que el nombre ya exista."}, status=400)

@require_POST
@login_required
def eliminar_tipo_unidad(request, pk):
    try:
        tipo = get_object_or_404(NTipoUnidadOrganizativa, pk=pk)
        
        # PROTECCIÓN 1: No borrar si tiene subunidades
        if tipo.es_principal:
            hijas = NTipoUnidadOrganizativa.objects.filter(tipo_padre=tipo)
            if hijas.exists():
                return JsonResponse({
                    'success': False, 
                    'error': 'No se puede eliminar esta Unidad Principal porque tiene subunidades que dependen de ella.'
                })
            
        tipo.delete()
        return JsonResponse({'success': True})
        
    except ProtectedError:
        # PROTECCIÓN 2: No borrar si ya está en uso en otra tabla
        return JsonResponse({
            'success': False, 
            'error': 'No se puede eliminar porque hay Unidades Organizativas reales que están usando este Tipo.'
        })
        

# ---------- CRUD NTipoFamilia (Para el Modal) ----------
@csrf_exempt
@require_POST
@login_required
def tipo_familia_create(request):
    try:
        data = json.loads(request.body)
        nombre = data.get('nombre', '').strip()
        tf_id = data.get('id') # Capturamos el ID si existe
        
        if not nombre:
            return JsonResponse({'error': 'El nombre es obligatorio'}, status=400)
            
        if tf_id:
            # Si hay ID, estamos EDITANDO
            obj = get_object_or_404(NTipoFamilia, pk=tf_id)
            obj.nombre = nombre.title()
            obj.save()
        else:
            # Si NO hay ID, estamos CREANDO
            obj = NTipoFamilia.objects.create(nombre=nombre.title())
            
        return JsonResponse({'id': obj.id, 'nombre': obj.nombre})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["DELETE"])
@login_required
def tipo_familia_delete(request, pk):
    try:
        NTipoFamilia.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NTipoFamilia.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)
    except RestrictedError:
        return JsonResponse({'error': 'No se puede eliminar porque está en uso.'}, status=409)