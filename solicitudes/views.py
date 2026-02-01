from django.contrib import messages
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView

from solicitudes.forms import SolicitudCargoForm
from solicitudes.models import SolicitudCargo


class SolicitudCargoListView(ListView):
    model = SolicitudCargo
    template_name = 'pages/solicitudes/cargo/list_solicitud.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = SolicitudCargoForm()
        return context

class SolicitudCargoCreateView(CreateView):
    model = SolicitudCargo
    form_class = SolicitudCargoForm
    template_name = 'pages/solicitudes/cargo/add_solicitud.html'
    success_url = reverse_lazy('list_solicitudes')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        solicitud = form.save(commit=False)
        messages.success(self.request, 'Solicitud guardada exitosamente')
        solicitud.save()
        return super().form_valid(form)

class SolicitudCargoUpdateView(UpdateView):
    model = SolicitudCargo
    template_name = 'TEMPLATE_NAME'
