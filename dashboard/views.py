from contratos.models import CAlta, CBaja
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
import json


# Create your views here.
class DashboardView(TemplateView):
    template_name = "pages/dashboard.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        
        # ========== DEFINIR MESES AQUÍ (antes de cualquier uso) ==========
        meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        
        # 1. Consultas Base (Optimizadas)
        activos = CAlta.objects.filter(aspirante__estado='ACTIVO').select_related(
            'aspirante', 'tipo', 'cargo__ncargo', 'cargo__departamento', 'cargo__nivel_preparacion'
        )
        todos_altas = CAlta.objects.all().select_related('aspirante', 'tipo')
        todas_bajas = CBaja.objects.all()

        # Variables directas para las tarjetas
        context['contratos_count'] = activos.count()
        context['dptos_count'] = Departamento.objects.count()
        context['plazas'] = self.get_plazas()

        # 2. Diccionarios y contadores inicializados en 0 (Evita que el JS falle si no hay datos)
        cumpleaneros = []
        avisos_contratos = []
        pre_jubilacion = []
        recontratados = []
        
        cat_ocupacional = {'OPE': 0, 'TEC': 0, 'ADM': 0, 'SER': 0, 'CUA': 0}
        nivel_educ_counts = {}
        nivel_prep_counts = {}
        masa_salarial_dict = {}
        tipos_contrato_counts = {}
        raza_counts = {}
        
        edades_m = [0, 0, 0, 0, 0, 0]
        edades_f = [0, 0, 0, 0, 0, 0]
        hombres = mujeres = 0
        total_salario_empresa = 0
        adiestrados = dias_totales = validos = 0

        # --- BUCLE MAESTRO ---
        for c in activos:
            asp = c.aspirante
            sexo = asp.sexo
            
            # Géneros
            if sexo == 'M': hombres += 1
            elif sexo == 'F': mujeres += 1

            # KPIs
            if c.tipo and getattr(c.tipo, 'es_adiestrado', False): adiestrados += 1
            if getattr(c, 'fecha_alta', None):
                dias_totales += (hoy - c.fecha_alta).days
                validos += 1

            # Tipos de Contrato
            t_desc = c.tipo.descripcion if c.tipo else 'Sin Tipo'
            tipos_contrato_counts[t_desc] = tipos_contrato_counts.get(t_desc, 0) + 1

            # Categoría Ocupacional
            cat = c.cargo.ncargo.cat_ocupacional if c.cargo and getattr(c.cargo, 'ncargo', None) else None
            if cat == 'OPE': cat_ocupacional['OPE'] += 1
            elif cat == 'TEC': cat_ocupacional['TEC'] += 1
            elif cat == 'ADM': cat_ocupacional['ADM'] += 1
            elif cat == 'SER': cat_ocupacional['SER'] += 1
            elif cat in ['CDI', 'CEJ']: cat_ocupacional['CUA'] += 1

            # Niveles Educacional y Preparación
            educ = asp.get_nivel_educ_display() if hasattr(asp, 'get_nivel_educ_display') and asp.nivel_educ else 'Sin Acreditar'
            nivel_educ_counts[educ] = nivel_educ_counts.get(educ, 0) + 1

            prep = c.cargo.nivel_preparacion.nombre if c.cargo and getattr(c.cargo, 'nivel_preparacion', None) else 'No Definido'
            nivel_prep_counts[prep] = nivel_prep_counts.get(prep, 0) + 1

            # Masa Salarial
            dpto = c.cargo.departamento.descripcion if c.cargo and getattr(c.cargo, 'departamento', None) else 'Sin Dpto'
            salario = c.salario_total or 0  
            masa_salarial_dict[dpto] = masa_salarial_dict.get(dpto, 0) + float(salario)
            total_salario_empresa += float(salario)

            # Alertas de Contrato (Solución exacta de DeepSeek)
            if c.tipo and "INDETERMINADO" not in t_desc.upper():
                if hasattr(c, 'fecha_vencimiento') and c.fecha_vencimiento:
                    dias_res = (c.fecha_vencimiento - hoy).days
                    if dias_res <= 45: 
                        avisos_contratos.append({
                            'nombre': f"{asp.nombre} {asp.papellido}", 
                            'dias': dias_res,
                            'tipo': t_desc
                        })

            # Cálculos de CI (Cumpleaños y Edades)
            ci = (asp.doc_identidad or "").strip()
            edad = asp.get_edad

            if len(ci) >= 6 and ci[:6].isdigit():
                try:
                    mm, dd = int(ci[2:4]), int(ci[4:6])
                    f_cumple = date(hoy.year, mm, dd)
                    if f_cumple < hoy: f_cumple = date(hoy.year + 1, mm, dd)
                    dias_faltan = (f_cumple - hoy).days
                    if dias_faltan <= 45: 
                        cumpleaneros.append({'nombre': f"{asp.nombre} {asp.papellido}", 'fecha_str': f"{dd} {meses[mm-1]}", 'dias': dias_faltan, 'sexo': sexo})
                except ValueError: pass

            if edad is not None:
                idx = 0 if edad <= 25 else 1 if edad <= 35 else 2 if edad <= 45 else 3 if edad <= 55 else 4 if edad <= 65 else 5
                if sexo == 'M': edades_m[idx] += 1
                elif sexo == 'F': edades_f[idx] += 1

                nombre_full = f"{asp.nombre} {asp.papellido}"
                cargo_desc = c.cargo.ncargo.descripcion if c.cargo and getattr(c.cargo, 'ncargo', None) else '-'
                if sexo == 'F':
                    if 58 <= edad <= 60: pre_jubilacion.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'F', 'cargo': cargo_desc})
                    elif edad > 60: recontratados.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'F', 'cargo': cargo_desc})
                elif sexo == 'M':
                    if 63 <= edad <= 65: pre_jubilacion.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'M', 'cargo': cargo_desc})
                    elif edad > 65: recontratados.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'M', 'cargo': cargo_desc})

            # I) Distribución por Raza
            raza = asp.get_raza_display() if hasattr(asp, 'get_raza_display') and asp.raza else 'No Definida'
            raza_counts[raza] = raza_counts.get(raza, 0) + 1 # <--- 2. AÑADIR ESTE BLOQUE

        # --- 3. ORDENACIÓN Y EMPAQUETADO ---
        cumpleaneros.sort(key=lambda x: x['dias'])
        avisos_contratos.sort(key=lambda x: x['dias'])
        pre_jubilacion.sort(key=lambda x: x['edad'], reverse=True)
        recontratados.sort(key=lambda x: x['edad'], reverse=True)
        
        # Masa Salarial Top 5 y Tipos de Contrato
        ms_ordenada = sorted(masa_salarial_dict.items(), key=lambda x: x[1], reverse=True)[:5]
        tipos_ordenados = sorted(tipos_contrato_counts.items(), key=lambda x: x[1], reverse=True)

        # Rotación Mensual (Bajas) - AHORA BUSCA EN CBaja
        bajas_mes = sum(1 for b in todas_bajas if getattr(b, 'fecha_baja', None) and b.fecha_baja.month == hoy.month and b.fecha_baja.year == hoy.year)
        total_g = hombres + mujeres

        context['generos'] = {
            'hombres': hombres, 'mujeres': mujeres,
            'porc_hombres': round((hombres/total_g)*100, 1) if total_g else 0,
            'porc_mujeres': round((mujeres/total_g)*100, 1) if total_g else 0
        }
        
        context['resumen_personal'] = {
            'capacitaciones': adiestrados,
            'antiguedad': round((dias_totales / validos) / 365.25, 1) if validos > 0 else 0,
            'rotacion': round((bajas_mes / activos.count()) * 100, 1) if activos.count() > 0 else 0,
            'salario_prom': round(total_salario_empresa / activos.count(), 2) if activos.count() > 0 else 0
        }

        # Listas
        context['cumpleannos'] = cumpleaneros[:5]
        context['avisos_contratos'] = avisos_contratos[:5]
        context['pre_jubilacion'] = pre_jubilacion
        context['recontratados'] = recontratados
        context['cat_ocupacional'] = list(cat_ocupacional.values()) 
        context['edades_m'] = edades_m
        context['edades_f'] = edades_f
        
        # ========== DATOS PARA GRÁFICOS (CORREGIDO: sin json.dumps en listas) ==========
        # Etiquetas (sí van con json.dumps para que queden como strings en JS)
        context['nivel_educ_labels'] = json.dumps(list(nivel_educ_counts.keys()))
        context['nivel_educ_data'] = list(nivel_educ_counts.values())   # Lista normal
        
        context['nivel_prep_labels'] = json.dumps(list(nivel_prep_counts.keys()))
        context['nivel_prep_data'] = list(nivel_prep_counts.values())   # Lista normal
        
        context['ms_labels'] = json.dumps([item[0] for item in ms_ordenada])
        context['ms_data'] = [item[1] for item in ms_ordenada]          # Lista normal
        
        context['tipos_contrato_labels'] = json.dumps([item[0] for item in tipos_ordenados])
        context['tipos_contrato_data'] = [item[1] for item in tipos_ordenados]  # Lista normal

        context['raza_labels'] = json.dumps(list(raza_counts.keys()))
        context['raza_data'] = json.dumps(list(raza_counts.values()))

        # --- 4. GRÁFICO HISTÓRICO ---
        datos_meses = []; datos_altas = []; datos_bajas = []
        for i in range(5, -1, -1):
            mes_target = hoy.month - i
            anno_target = hoy.year
            if mes_target <= 0: mes_target += 12; anno_target -= 1
            datos_meses.append(meses[mes_target - 1])
            
            # Altas busca en CAlta
            datos_altas.append(sum(1 for c in todos_altas if getattr(c, 'fecha_alta', None) and c.fecha_alta.month == mes_target and c.fecha_alta.year == anno_target))
            
            # Bajas busca en CBaja
            datos_bajas.append(sum(1 for b in todas_bajas if getattr(b, 'fecha_baja', None) and b.fecha_baja.month == mes_target and b.fecha_baja.year == anno_target))

        context['graficos'] = {
            'meses': json.dumps(datos_meses),   # Etiquetas van con JSON
            'altas': datos_altas,               # Lista normal
            'bajas': datos_bajas,               # Lista normal
            'altas_total': datos_altas[-1] if datos_altas else 0,
            'bajas_total': datos_bajas[-1] if datos_bajas else 0
        }

        return context

    def get_plazas(self):
        cargos = CargoPlantilla.objects.filter(activo=True)
        t_cubiertas = sum(c.cant_cubierta or 0 for c in cargos)
        t_aprobadas = sum(c.cant_aprobada or 0 for c in cargos)
        t_vacantes = max(t_aprobadas - t_cubiertas, 0)
        totales = t_cubiertas + t_vacantes

        return {
            'totales': totales, 'cubiertas': t_cubiertas, 'vacantes': t_vacantes,
            'porc_cubiertas': round((t_cubiertas / totales) * 100, 2) if totales else 0,
            'porc_vacantes': round((t_vacantes / totales) * 100, 2) if totales else 0
        }