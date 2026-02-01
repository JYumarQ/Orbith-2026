from django.views.generic.edit import FormView
from django.urls import reverse_lazy
from django.contrib import messages
from .models import Configuracion
from .forms import ConfiguracionForm
from nomencladores.models import NSalario, NGrupoEscala, NTridente, NRol, NProvincia, NMunicipio, NHorario, NJornada, \
    NCausaAltaBaja, NCondicionLaboralAnormal, NEspecialidad, NCargo
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from operator import attrgetter

class ParametrosGeneralesView(FormView):
    template_name = "pages/config/config.html"
    form_class = ConfiguracionForm
    
    def get_success_url(self):
        # Obtener la pestaña activa del parámetro en la solicitud o usar 'parametros' por defecto
        tab = self.request.POST.get('active_tab', 'parametros')
        return reverse_lazy('parametros') + f'?tab={tab}'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        grupos_escala = sorted(NGrupoEscala.objects.all(), key=attrgetter('valor_numerico'))
        salarios = []

        for grupo in grupos_escala:
            # Salarios por rol
            dec = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Decisorio').order_by('tridente__tipo')
            fun = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Fundamental').order_by('tridente__tipo')
            apo = NSalario.objects.filter(grupo_escala=grupo, rol__tipo='Apoyo').order_by('tridente__tipo')

            # Salario de cuadro (sin rol ni tridente)
            salario_cuadro = NSalario.objects.filter(
                grupo_escala=grupo,
                rol=None,
                tridente=None
            ).first()

            # Mostrar el grupo si tiene salarios de rol O es un cuadro
            if dec.exists() or fun.exists() or apo.exists() or salario_cuadro:
                salarios.append({
                    'nivel': grupo.nivel,
                    'decisorios': list(dec),
                    'fundamentales': list(fun),
                    'apoyo': list(apo),
                    'cuadro': salario_cuadro,  # Puede ser None
                })

        context['salarios'] = salarios
        context['active_tab'] = self.request.GET.get('tab', 'parametros')
        context['tridentes'] = NTridente.objects.all()
        context['roles'] = NRol.objects.all()
        context['grupos'] = NGrupoEscala.objects.all()
        context['provincias'] = NProvincia.objects.all()
        context['municipios'] = NMunicipio.objects.all()
        context['horarios'] = NHorario.objects.all()
        context['jornadas'] = NJornada.objects.all()
        context['causas'] = NCausaAltaBaja.objects.all()
        context['condiciones'] = NCondicionLaboralAnormal.objects.all()
        context['especialidades'] = NEspecialidad.objects.all()
        context['cargos'] = NCargo.objects.all()
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

