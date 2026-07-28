from django.views.generic.edit import FormView
from django.views.generic import TemplateView
from django.urls import reverse_lazy
from django.contrib import messages
from .models import Configuracion
from .forms import ConfiguracionForm
from nomencladores.models import NSalario, NGrupoEscala, NTridente, NRol, NProvincia, NMunicipio, NHorario, NJornada, \
    NCausaAltaBaja, NCondicionLaboralAnormal, NEspecialidad, NCargo, NFamiliaCargo, NNivelPreparacion, NTipoContrato, NMotivoContrato, NTipoUnidadOrganizativa, NTipoFamilia, NNocturnidad
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from operator import attrgetter
from django.http import JsonResponse
from django.core.paginator import Paginator

class ParametrosGeneralesView(FormView):
    template_name = "pages/config/config.html"
    form_class = ConfiguracionForm
    
    def get_success_url(self):
        tab = self.request.POST.get('active_tab', 'parametros')
        return reverse_lazy('parametros') + f'?tab={tab}'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        grupos_escala = sorted(NGrupoEscala.objects.all(), key=attrgetter('valor_numerico'))
        salarios = []

        for grupo in grupos_escala:
            dec = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Decisorio').order_by('tridente__tipo')
            fun = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Fundamental').order_by('tridente__tipo')
            apo = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Apoyo').order_by('tridente__tipo')
            salario_cuadro = NSalario.objects.filter(grupo_escala=grupo, rol=None, tridente=None).first()

            if dec.exists() or fun.exists() or apo.exists() or salario_cuadro:
                salarios.append({
                    'nivel': grupo.nivel,
                    'grupo_id': grupo.id,
                    'decisorios': list(dec),
                    'fundamentales': list(fun),
                    'apoyo': list(apo),
                    'cuadro': salario_cuadro,
                })

        # (La sección de familias fue movida a FamiliasCargoView)

        context['salarios'] = salarios
        context['active_tab'] = self.request.GET.get('tab', 'parametros')
        context['tipos_unidades'] = NTipoUnidadOrganizativa.objects.all()
        context['tridentes'] = NTridente.objects.all()
        context['roles'] = NRol.objects.all()
        grupos_todos = sorted(NGrupoEscala.objects.all(), key=attrgetter('valor_numerico'))
        page_number = self.request.GET.get('page_grupos', 1)
        paginator = Paginator(grupos_todos, 5)
        context['grupos'] = paginator.get_page(page_number)
        context['grupos_completos'] = grupos_todos
        context['provincias'] = NProvincia.objects.all()
        context['municipios'] = NMunicipio.objects.all()
        context['horarios'] = NHorario.objects.all()
        context['jornadas'] = NJornada.objects.all()
        context['causas'] = NCausaAltaBaja.objects.all()
        context['condiciones'] = NCondicionLaboralAnormal.objects.all()
        context['especialidades'] = NEspecialidad.objects.all()
        context['niveles_preparacion'] = NNivelPreparacion.objects.all()
        context['tipos_contrato'] = NTipoContrato.objects.all().order_by('descripcion')
        context['motivos_contrato'] = NMotivoContrato.objects.all().order_by('descripcion')
        context['tipos_familia'] = NTipoFamilia.objects.all().order_by('nombre')
        context['cargos'] = NCargo.objects.all().order_by('descripcion')
        context['nocturnidades'] = NNocturnidad.objects.all().order_by('codigo')
        context['config'] = Configuracion.objects.first()
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        instance = Configuracion.objects.first()
        if instance:
            kwargs['instance'] = instance
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Configuracion guardada correctamente')
        return super().form_valid(form)

@csrf_exempt
@require_POST
def actualizar_salario(request):
    try:
        data = json.loads(request.body)
        salario_id = data.get("id")
        nuevo_monto = data.get("monto")

        if not salario_id or nuevo_monto is None:
            return JsonResponse({"error": "Datos incompletos."}, status=400)

        salario = NSalario.objects.get(id=salario_id)
        salario.monto = nuevo_monto
        salario.save()

        # Devolver la URL con el parámetro de pestaña activa
        return JsonResponse({
            "success": True,
            "redirect_url": reverse_lazy('parametros') + "?tab=salario"
        })

    except NSalario.DoesNotExist:
        return JsonResponse({"error": "Salario no encontrado."}, status=404)

    except Exception as e:
        print("ERROR al actualizar salario:", str(e))  # Muy útil para ver qué está fallando
        return JsonResponse({"error": "Error interno del servidor."}, status=500)

class FamiliasCargoView(TemplateView):
    template_name = "pages/config/partials/familias.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        tipos_familia = NTipoFamilia.objects.all().order_by('nombre')
        # Obtenemos el tipo desde el GET o usamos el primero por defecto
        tipo_id_get = self.request.GET.get('tipo_id')
        
        if tipo_id_get:
            tipo_actual = tipos_familia.filter(id=tipo_id_get).first()
        else:
            tipo_actual = tipos_familia.first()
            
        familias = []
        cargos_pendientes = []
        total_cargos = NCargo.objects.count()
        cargos_asignados = 0

        if tipo_actual:
            familias = NFamiliaCargo.objects.filter(tipo_familia=tipo_actual).prefetch_related('cargos').order_by('-id')
            cargos_pendientes = NCargo.objects.exclude(familias__tipo_familia=tipo_actual).order_by('descripcion')
            cargos_asignados = total_cargos - cargos_pendientes.count()

        context['tipos_familia'] = tipos_familia
        context['tipo_actual'] = tipo_actual
        context['familias'] = familias
        context['cargos_sin_familia'] = cargos_pendientes
        context['total_cargos'] = total_cargos       
        context['cargos_asignados'] = cargos_asignados
        return context