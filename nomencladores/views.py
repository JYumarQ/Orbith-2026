from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import NCargo, NProvincia, NMunicipio, NHorario, NJornada, NCausaAltaBaja, NCondicionLaboralAnormal
from .forms import NCargoForm
from django.urls import reverse_lazy
from django.contrib import messages, admin
from django.db import transaction
from nomencladores.models import NSalario, NRol, NTridente, NGrupoEscala, NEspecialidad
from .forms import RegistrarSalariosForm
from django.http import JsonResponse
import json
from django.db.models.deletion import RestrictedError
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator


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
            sigla = ABR_MUNICIPIOS.get(m.nombre, m.nombre[:3].upper())
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

# NCARGO
class NCargoListView(ListView):
    model = NCargo
    template_name = "pages/catalogos/ncargo/list_ncargo.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = NCargoForm()
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
@transaction.atomic
def crear_salarios_por_grupo(request):
    form = RegistrarSalariosForm(request.POST or None)
    roles = NRol.objects.all()
    tridentes = NTridente.objects.all()

    if request.method == 'POST' and form.is_valid():
        grupo_escala = form.cleaned_data['grupo_escala']
        es_para_cuadro = request.POST.get('es_para_cuadro') == 'on'

        try:
            # Procesar salario de cuadro si está marcado
            if es_para_cuadro:
                monto = request.POST.get('monto_cuadro', '0').strip()
                
                # Validar y convertir monto
                if not monto or not monto.replace('.', '', 1).isdigit():
                    raise ValueError("Monto de cuadro inválido")
                
                monto = float(monto)
                
                # Crear o actualizar salario de cuadro
                NSalario.objects.update_or_create(
                    grupo_escala=grupo_escala,
                    rol=None,
                    tridente=None,
                    defaults={'monto': monto}
                )
                messages.success(request, f"Salario de cuadro {grupo_escala.nivel} registrado correctamente.")
                
                # Crear salario para cada combinación de rol y tridente con monto 0
                for rol in roles:
                    for tridente in tridentes:
                        field_name = f'monto_{rol.id}_{tridente.id}'
                        monto_str = request.POST.get(field_name, '').strip()
                        
                        # Si no se proporciona un monto para la combinación, se crea con monto 0
                        if not monto_str:
                            monto = 0
                        else:
                            # Si se proporciona un monto, validamos y lo usamos
                            if not monto_str.replace('.', '', 1).isdigit():
                                raise ValueError(f"Valor inválido para {rol.tipo} - {tridente.tipo}")
                            monto = float(monto_str)
                        
                        # Crear o actualizar salario
                        NSalario.objects.update_or_create(
                            grupo_escala=grupo_escala,
                            rol=rol,
                            tridente=tridente,
                            defaults={'monto': monto}
                        )
                messages.success(request, f"Salarios para {grupo_escala.nivel} registrados correctamente.")

            # Procesar salarios normales si NO es para cuadro
            else:
                for rol in roles:
                    for tridente in tridentes:
                        field_name = f'monto_{rol.id}_{tridente.id}'
                        monto_str = request.POST.get(field_name, '0').strip()
                        
                        # Saltar campos vacíos
                        if not monto_str:
                            continue
                            
                        # Validar y convertir monto
                        if not monto_str.replace('.', '', 1).isdigit():
                            raise ValueError(f"Valor inválido para {rol.tipo} - {tridente.tipo}")
                            
                        monto = float(monto_str)
                        
                        # Crear o actualizar salario
                        NSalario.objects.update_or_create(
                            grupo_escala=grupo_escala,
                            rol=rol,
                            tridente=tridente,
                            defaults={'monto': monto}
                        )
                messages.success(request, f"Salarios para {grupo_escala.nivel} registrados correctamente.")
            
            return redirect(reverse_lazy('parametros') + '?tab=salario')
        
        except ValueError as e:
            messages.error(request, f"Error: {str(e)}")
        except Exception as e:
            messages.error(request, f"Error inesperado: {str(e)}")
    
    return render(request, 'pages/catalogos/nsalario/add_salario.html', {
        'form': form,
        'roles': roles,
        'tridentes': tridentes
    })

def obtener_grupo(request, id):
    grupo = get_object_or_404(NGrupoEscala, id=id)
    return JsonResponse({'es_cuadro': grupo.es_cuadro})

def tabla_salarios_modal(request):
    grupo_id = request.GET.get('grupo')
    grupo = get_object_or_404(NGrupoEscala, id=grupo_id)
    roles = NRol.objects.all()
    tridentes = NTridente.objects.all()
    return render(request, 'modals/tabla_rol_tridente.html', {
        'roles': roles,
        'tridentes': tridentes
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
@require_POST
def rol_create(request):
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NRol.objects.create(tipo=tipo)
    return JsonResponse({'id': obj.id, 'tipo': obj.tipo})

@csrf_exempt
@require_http_methods(["PUT"])
def rol_update(request, pk):
    obj = NRol.objects.get(pk=pk)
    data = json.loads(request.body)
    tipo = data.get('tipo', '').strip()
    if not tipo:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.tipo = tipo
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
    es_cuadro = data.get('es_cuadro', False)

    if not nivel:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    try:
        obj = NGrupoEscala.objects.create(nivel=nivel.upper(), es_cuadro=es_cuadro)
        return JsonResponse({'id': obj.id, 'nivel': obj.nivel, 'es_cuadro': obj.es_cuadro})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
@require_http_methods(["PUT"])
def grupo_update(request, pk):
    obj = NGrupoEscala.objects.get(pk=pk)
    data = json.loads(request.body)
    nivel = data.get('nivel', '').strip()
    es_cuadro = data.get('es_cuadro', False)

    if not nivel:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)

    try:
        obj.nivel = nivel.upper()
        obj.es_cuadro = es_cuadro
        obj.save()
        return JsonResponse({'id': obj.id, 'nivel': obj.nivel, 'es_cuadro': obj.es_cuadro})
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
@csrf_exempt
@require_POST
def provincia_create(request):
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NProvincia.objects.create(nombre=nombre.title())
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre})

@csrf_exempt
@require_http_methods(["PUT"])
def provincia_update(request, pk):
    obj = NProvincia.objects.get(pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.nombre = nombre.title()
    obj.save()
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre})

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
    if not nombre or not provincia_id:
        return JsonResponse({'error': 'Campos obligatorios'}, status=400)
    provincia = get_object_or_404(NProvincia, pk=provincia_id)
    obj = NMunicipio.objects.create(nombre=nombre.title(), provincia=provincia)
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre, 'provincia_id': obj.provincia_id})

@csrf_exempt
@require_http_methods(["PUT"])
def municipio_update(request, pk):
    obj = NMunicipio.objects.get(pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.nombre = nombre.title()
    obj.save()
    return JsonResponse({'id': obj.id, 'nombre': obj.nombre})

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

    return JsonResponse({'id': obj.id,
                         'descripcion': obj.descripcion,
                         'hora_inicio': obj.hora_inicio.strftime('%H:%M'),
                         'hora_fin': obj.hora_fin.strftime('%H:%M')})

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
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    descripcion = data.get('descripcion', '').strip()
    tarifa = float(data.get('tarifa_hora', 0))
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj = NCondicionLaboralAnormal.objects.create(
        nombre=nombre.title(),
        descripcion=descripcion or None,
        tarifa_hora=tarifa
    )
    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'descripcion': obj.descripcion or '',
        'tarifa_hora': str(obj.tarifa_hora)
    })

@csrf_exempt
@require_http_methods(["PUT"])
def condicion_update(request, pk):
    obj = get_object_or_404(NCondicionLaboralAnormal, pk=pk)
    data = json.loads(request.body)
    nombre = data.get('nombre', '').strip()
    descripcion = data.get('descripcion', '').strip()
    tarifa = float(data.get('tarifa_hora', 0))
    if not nombre:
        return JsonResponse({'error': 'Campo obligatorio'}, status=400)
    obj.nombre = nombre.title()
    obj.descripcion = descripcion or None
    obj.tarifa_hora = tarifa
    obj.save()
    return JsonResponse({
        'id': obj.id,
        'nombre': obj.nombre,
        'descripcion': obj.descripcion or '',
        'tarifa_hora': str(obj.tarifa_hora)
    })

@csrf_exempt
@require_http_methods(["DELETE"])
def condicion_delete(request, pk):
    try:
        NCondicionLaboralAnormal.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NCondicionLaboralAnormal.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

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
    activo = data.get('activo', True)

    if not descripcion or not cat_ocupacional or not grupo_escala_id:
        return JsonResponse({'error': 'Complete todos los campos obligatorios'}, status=400)

    try:
        grupo = NGrupoEscala.objects.get(pk=grupo_escala_id)
        obj = NCargo.objects.create(
            descripcion=descripcion.title(),
            cat_ocupacional=cat_ocupacional,
            grupo_escala=grupo,
            salario_basico=float(salario_basico),
            activo=activo
        )
        return JsonResponse({
            'id': obj.id,
            'descripcion': obj.descripcion,
            'cat_ocupacional': obj.get_cat_ocupacional_display(),
            'cat_ocupacional_value': obj.cat_ocupacional,
            'grupo_escala': obj.grupo_escala.nivel,
            'salario_basico': str(obj.salario_basico),
            'activo': obj.activo
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
        activo = data.get('activo', True)

        if not descripcion or not cat_ocupacional or not grupo_escala_id:
            return JsonResponse({'error': 'Complete todos los campos obligatorios'}, status=400)

        grupo = NGrupoEscala.objects.get(pk=grupo_escala_id)
        obj.descripcion = descripcion.title()
        obj.cat_ocupacional = cat_ocupacional
        obj.grupo_escala = grupo
        obj.salario_basico = float(salario_basico)
        obj.activo = activo
        obj.save()

        return JsonResponse({
            'id': obj.id,
            'descripcion': obj.descripcion,
            'cat_ocupacional': obj.get_cat_ocupacional_display(),
            'cat_ocupacional_value': obj.cat_ocupacional,
            'grupo_escala': obj.grupo_escala.nivel,
            'salario_basico': str(obj.salario_basico),
            'activo': obj.activo
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
        NCargo.objects.get(pk=pk).delete()
        return JsonResponse({'success': True})
    except NCargo.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

@login_required
def search_cargos(request):
    # Obtener texto de búsqueda
    query = request.GET.get('search_cargo', '').strip()
    page_number = request.GET.get('page', 1)

    # QueryBase ordenada
    qs = NCargo.objects.all().order_by('descripcion')

    # Filtrado por 'descripcion' (Nombre del Cargo según tu models.py)
    if query:
        qs = qs.filter(descripcion__icontains=query)

    # Paginación (Usamos 8 para coincidir con tu NCargoListView)
    paginator = Paginator(qs, 8)
    page_obj = paginator.get_page(page_number)

    # Renderizar solo la tabla (Partial)
    return render(request, 'pages/catalogos/ncargo/partials/ncargo_list_partial.html', {
        'page_obj': page_obj,
        'search_url': 'search_cargos', # Para mantener la paginación con búsqueda
        'current_search': query
    })