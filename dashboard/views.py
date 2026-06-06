from contratos.models import CAlta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
#from .models import Objeto
from django.urls import reverse_lazy
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
import os
from django.conf import settings
from django.http import HttpResponse
from docxtpl import DocxTemplate
import calendar
from datetime import date
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.views.generic import TemplateView
from nomencladores.models import NTipoFamilia, NFamiliaCargo
from configuracion.models import Configuracion
from datetime import datetime


# Create your views here.
class DashboardView(TemplateView):
    template_name = "pages/dashboard.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['contratos'] = CAlta.objects.all()
        context['dptos'] = Departamento.objects.all()
        context['plazas'] = self.get_plazas()
        context['generos'] = self.get_generos()
        return context
    
    #?UTIL
    def get_plazas(self):
        cargos = CargoPlantilla.objects.filter(activo=True)
        t_cubiertas = 0
        t_vacantes = 0
        
        for cargo in cargos:
            cubiertas = cargo.cant_cubierta or 0
            aprobadas = cargo.cant_aprobada or 0
            vacantes = max(aprobadas - cubiertas, 0)

            t_cubiertas += cubiertas
            t_vacantes += vacantes

        totales = t_cubiertas + t_vacantes
        p_cubiertas = round((t_cubiertas / totales) * 100, 2) if totales else 0
        p_vacantes = round((t_vacantes / totales) * 100, 2) if totales else 0

        return {
            'totales': totales,
            'cubiertas': t_cubiertas,
            'vacantes': t_vacantes,
            'porc_cubiertas': p_cubiertas,
            'porc_vacantes': p_vacantes
    }

    def get_generos(self):
        altas = CAlta.objects.select_related('aspirante').all()
        
        hombres = 0
        mujeres = 0
        
        for alta in altas:
            if alta.aspirante.sexo == 'M':
                hombres += 1
            elif alta.aspirante.sexo == 'F':
                mujeres += 1

        total = hombres + mujeres
        porc_hombres = round((hombres / total) * 100, 2) if total > 0 else 0
        porc_mujeres = round((mujeres / total) * 100, 2) if total > 0 else 0

        return {
            'hombres': hombres,
            'mujeres': mujeres,
            'porc_hombres': porc_hombres,
            'porc_mujeres': porc_mujeres
        }

        
