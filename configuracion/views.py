from django.views.generic.edit import FormView
from django.views.generic import TemplateView
from django.urls import reverse_lazy
from django.contrib import messages
from .models import Configuracion
from .forms import ConfiguracionForm
from nomencladores.models import NSalario, NGrupoEscala, NTridente, NRol, NProvincia, NMunicipio, \
    NCausaAltaBaja, NCondicionLaboralAnormal, NEspecialidad, NCargo, NFamiliaCargo, NNivelPreparacion, NTipoContrato, NMotivoContrato, NTipoUnidadOrganizativa, NTipoFamilia, NNocturnidad
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
from operator import attrgetter
from django.http import JsonResponse
from django.core.paginator import Paginator

def escala_salarial():
    """La tabla de Parámetros → Escala salarial, construida desde los nomencladores
    (opción C, decisión del 27-10-2026).

    Antes tenía escritos a mano los tres roles y colocaba los importes por POSICIÓN:
    al faltar un tridente, los demás se corrían de columna. Ahora las columnas salen
    de los roles (en su orden: Decisorio, Fundamental, Apoyo, o el que fije el
    Administrador) y de los tridentes (I, II, III), y cada importe va en su celda.

    Cada celda dice además su estado: `ok` (tiene importe), `falta` (el rol
    corresponde al grupo según su ficha pero no hay importe: un contrato así sale
    «Sin salario») o `no_aplica` (la ficha del grupo no lleva ese rol, como XXIV y
    XXV, que solo llevan Decisorio). Solo LEE: no cambia ningún dato.

    Tres consultas en total; la versión anterior hacía unas cinco por grupo.
    """
    roles = list(NRol.objects.all())
    tridentes = list(NTridente.objects.all())
    montos = {(s.grupo_escala_id, s.rol_id, s.tridente_id): s.monto for s in NSalario.objects.all()}

    filas = []
    for grupo in NGrupoEscala.objects.prefetch_related('roles'):
        del_grupo = {r.pk for r in grupo.roles.all()} if grupo.tiene_rol else set()
        celdas = []
        for rol in roles:
            for tridente in tridentes:
                monto = montos.get((grupo.pk, rol.pk, tridente.pk))
                if rol.pk not in del_grupo and monto is None:
                    estado = 'no_aplica'
                else:
                    estado = 'falta' if monto is None else 'ok'
                celdas.append({'estado': estado, 'monto': monto})
        cuadro = montos.get((grupo.pk, None, None))
        if cuadro is None:
            estado_cuadro = 'falta' if grupo.es_cuadro else 'no_aplica'
        else:
            estado_cuadro = 'ok'
        # Como antes: solo los grupos que ya tienen escala (los demás se crean con
        # «Nuevo Salario»).
        if cuadro is not None or any(c['monto'] is not None for c in celdas):
            filas.append({'nivel': grupo.nivel, 'grupo_id': grupo.pk, 'celdas': celdas,
                          'cuadro': {'estado': estado_cuadro, 'monto': cuadro}})
    return {'salarios': filas, 'escala_roles': roles, 'escala_tridentes': tridentes}


class ParametrosGeneralesView(FormView):
    template_name = "pages/config/config.html"
    form_class = ConfiguracionForm
    
    def get_success_url(self):
        tab = self.request.POST.get('active_tab', 'parametros')
        return reverse_lazy('parametros') + f'?tab={tab}'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(escala_salarial())

        # (La sección de familias fue movida a FamiliasCargoView)

        context['active_tab'] = self.request.GET.get('tab', 'parametros')

        # Abreviaturas estándar de los municipios cubanos. El panel Territorial
        # las usa para PROPONER la sigla al escribir el nombre, en su propia
        # casilla. Que nadie tenga que teclearla es lo que evita que acabe
        # tecleada en la casilla equivocada.
        from nomencladores.views import ABR_MUNICIPIOS
        context['abreviaturas_municipios'] = ABR_MUNICIPIOS
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
        # `horarios` y `jornadas` ya no se envían: las tarjetas de Horarios y
        # Jornadas se retiraron del acordeón «Tiempo de Trabajo». Los modelos
        # NHorario/NJornada y su API se eliminaron después por completo — el
        # tiempo de trabajo se gestiona en Pre-Nómina → Calendario.
        context['causas'] = NCausaAltaBaja.objects.all()
        context['condiciones'] = NCondicionLaboralAnormal.objects.all()
        context['especialidades'] = NEspecialidad.objects.all()
        context['niveles_preparacion'] = NNivelPreparacion.objects.all()
        context['tipos_contrato'] = NTipoContrato.objects.all()
        context['motivos_contrato'] = NMotivoContrato.objects.all()
        context['tipos_familia'] = NTipoFamilia.objects.all()
        context['cargos'] = NCargo.objects.all().order_by('descripcion')
        context['nocturnidades'] = NNocturnidad.objects.all()
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

@require_POST
def actualizar_salario(request):
    try:
        data = json.loads(request.body)
        salario_id = data.get("id")
        nuevo_monto = data.get("monto")

        if not salario_id or nuevo_monto is None:
            return JsonResponse({"error": "Datos incompletos."}, status=400)

        salario = NSalario.objects.get(id=salario_id)
        # Auditoría: un evento por grupo con la escala completa, igual que las
        # vistas de edición de la escala (ver `nomencladores/views.py`).
        from nomencladores.views import _auditar_escala, _escala_legible
        antes = _escala_legible(salario.grupo_escala)
        salario.monto = nuevo_monto
        salario.save()
        _auditar_escala(salario.grupo_escala, antes)

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
        
        tipos_familia = NTipoFamilia.objects.all()
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
            familias = NFamiliaCargo.objects.filter(tipo_familia=tipo_actual).prefetch_related('cargos')
            cargos_pendientes = NCargo.objects.exclude(familias__tipo_familia=tipo_actual).order_by('descripcion')
            cargos_asignados = total_cargos - cargos_pendientes.count()

        context['tipos_familia'] = tipos_familia
        context['tipo_actual'] = tipo_actual
        context['familias'] = familias
        context['cargos_sin_familia'] = cargos_pendientes
        context['total_cargos'] = total_cargos       
        context['cargos_asignados'] = cargos_asignados
        return context