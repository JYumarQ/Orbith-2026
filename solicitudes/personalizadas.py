"""Solicitudes personalizadas: mensaje directo del Moderador al Administrador.

Decisión de RRHH del 24-10-2026. Nacen sobre todo del aviso de «Editar contrato»
cuando alguien intenta cambiar un campo que solo se cambia con un movimiento de
nómina (UO, departamento, cargo, tipo, motivo, salario, tridente) o la fecha de
contratación: si lo que hay es un ERROR del contrato actual, no un movimiento, se
explica aquí y el Administrador lo corrige.

Reglas:
* Solo el Moderador las envía. El Administrador responde UNA vez y la cierra
  («Atendida» o «Cerrada sin cambios»).
* El Administrador ve todas; el Moderador, las suyas.
* Aviso en la campana al Administrador cuando llega una y al Moderador cuando se
  la responden.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import EstadoPersonalizada, SolicitudPersonalizada
from .permisos import _denegar, acceso_solicitudes, es_administrador, es_moderador, solo_admin


class SolicitudPersonalizadaForm(forms.ModelForm):
    class Meta:
        model = SolicitudPersonalizada
        fields = ('asunto', 'contrato', 'descripcion')
        labels = {
            'asunto': 'Asunto',
            'contrato': 'Trabajador (opcional)',
            'descripcion': 'Explique el problema',
        }
        widgets = {
            'asunto': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 150,
                                             'placeholder': 'Ej.: Cargo mal puesto al contratar'}),
            'contrato': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 6,
                'placeholder': 'Qué está mal, cuál sería el dato correcto y, si lo sabe, '
                               'desde cuándo.'}),
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        from contratos.filtros import contratos_visibles
        campo = self.fields['contrato']
        campo.required = False
        campo.empty_label = 'Ninguno en concreto'
        # Solo los trabajadores de su alcance.
        campo.queryset = (contratos_visibles(usuario).select_related('aspirante')
                          .order_by('aspirante__nombre', 'aspirante__papellido'))
        campo.label_from_instance = lambda c: '%s — %s %s %s' % (
            c.no_expediente, c.aspirante.nombre, c.aspirante.papellido,
            c.aspirante.sapellido or '')


class RespuestaPersonalizadaForm(forms.Form):
    respuesta = forms.CharField(
        label='Respuesta al moderador',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4,
                                     'placeholder': 'Qué se hizo, o por qué no hace falta cambiar nada.'}),
        error_messages={'required': 'Escriba la respuesta para el moderador.'})


def personalizadas_visibles(usuario):
    consulta = SolicitudPersonalizada.objects.select_related(
        'contrato__aspirante', 'unidad', 'respondida_por', 'solicitante')
    if es_administrador(usuario):
        return consulta
    return consulta.filter(solicitante=usuario)


def total_abiertas(usuario):
    return personalizadas_visibles(usuario).filter(estado=EstadoPersonalizada.ABIERTA).count()


@acceso_solicitudes
def lista_personalizadas(request):
    from django.core.paginator import Paginator

    from core.paginacion import filas_por_pagina
    from .filtros import pestanas_con_contadores

    estado = request.GET.get('estado', '')
    consulta = personalizadas_visibles(request.user)
    if estado in EstadoPersonalizada.values:
        consulta = consulta.filter(estado=estado)
    pagina = Paginator(consulta, filas_por_pagina(request)).get_page(request.GET.get('pagina'))
    return render(request, 'pages/solicitudes/list_personalizadas.html', {
        'solicitudes': pagina,
        'page_obj': pagina,
        'pestanas': pestanas_con_contadores(request.user),
        'tab_activa': 'personalizadas',
        'es_admin': es_administrador(request.user),
        'puede_crear': es_moderador(request.user),
        'estado_filtro': estado,
        'querystring': '&estado=%s' % estado if estado else '',
        'estados': EstadoPersonalizada.choices,
    })


@acceso_solicitudes
def crear_personalizada(request):
    if not es_moderador(request.user):
        return _denegar(request, 'Las solicitudes personalizadas las envía el Moderador.')

    if request.method == 'POST':
        formulario = SolicitudPersonalizadaForm(request.POST, usuario=request.user)
        if formulario.is_valid():
            solicitud = formulario.save(commit=False)
            solicitud.solicitante = request.user
            solicitud.solicitante_nombre = (request.user.get_full_name() or request.user.username)[:150]
            solicitud.created_by = request.user
            if solicitud.contrato_id:
                contrato = solicitud.contrato
                solicitud.trabajador_texto = ('%s — %s %s %s' % (
                    contrato.no_expediente, contrato.aspirante.nombre,
                    contrato.aspirante.papellido, contrato.aspirante.sapellido or '')).strip()[:200]
                if contrato.cargo_id and contrato.cargo.departamento_id:
                    solicitud.unidad = contrato.cargo.departamento.unidad_organizativa
            solicitud.save()
            from .avisos import avisar_personalizada_nueva
            avisar_personalizada_nueva(solicitud)
            messages.success(request, 'Solicitud enviada al administrador.')
            return redirect('list_solicitudes_personalizadas')
    else:
        inicial = {}
        contrato = request.GET.get('contrato')
        if contrato and contrato.isdigit():
            inicial['contrato'] = contrato
        if request.GET.get('asunto'):
            inicial['asunto'] = request.GET['asunto'][:150]
        formulario = SolicitudPersonalizadaForm(initial=inicial, usuario=request.user)

    return render(request, 'pages/solicitudes/add_personalizada.html', {'form': formulario})


def _visible(request, pk):
    return get_object_or_404(personalizadas_visibles(request.user), pk=pk)


@acceso_solicitudes
def ver_personalizada(request, pk):
    solicitud = _visible(request, pk)
    return render(request, 'pages/solicitudes/ver_personalizada.html', {
        'solicitud': solicitud,
        'es_admin': es_administrador(request.user),
        'form_respuesta': RespuestaPersonalizadaForm(),
    })


@solo_admin
@require_POST
def responder_personalizada(request, pk):
    solicitud = _visible(request, pk)
    if not solicitud.abierta:
        messages.warning(request, 'Esta solicitud ya estaba respondida.')
        return redirect('ver_solicitud_personalizada', pk=pk)

    formulario = RespuestaPersonalizadaForm(request.POST)
    accion = request.POST.get('accion')
    if accion not in ('atender', 'cerrar') or not formulario.is_valid():
        return render(request, 'pages/solicitudes/ver_personalizada.html', {
            'solicitud': solicitud, 'es_admin': True, 'form_respuesta': formulario})

    solicitud.respuesta = formulario.cleaned_data['respuesta']
    solicitud.estado = (EstadoPersonalizada.ATENDIDA if accion == 'atender'
                        else EstadoPersonalizada.CERRADA)
    solicitud.respondida_por = request.user
    solicitud.fecha_respuesta = timezone.now()
    solicitud.updated_by = request.user
    solicitud.save()
    from .avisos import avisar_personalizada_respondida
    avisar_personalizada_respondida(solicitud)
    messages.success(request, 'Respuesta enviada al moderador.')
    return redirect('list_solicitudes_personalizadas')
