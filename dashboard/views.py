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
            doc = alta.aspirante.doc_identidad
            
            if doc and len(doc) == 11 and doc[-2].isdigit():
                penultimo = int(doc[-2])
                if penultimo % 2 == 0:
                    hombres += 1
                else:
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

        
class InformeEconomiaView(TemplateView):
    
    def get_template_names(self):
        if self.request.htmx:
            return ['pages/informes/partials/tabla_consolidado.html']
        return ['pages/informes/economia_dashboard.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Obtenemos el ID de la UEB si el usuario seleccionó alguna
        ueb_id = self.request.GET.get('ueb', '')
        
        # 2. Fechas SIEMPRE en tiempo real (para dejarlas marcadas en los selectores deshabilitados)
        hoy = date.today()
        context['mes_actual'] = str(hoy.month)
        context['anno_actual'] = str(hoy.year)
        context['ueb_actual'] = str(ueb_id)
        
        context['unidades'] = UnidadOrganizativa.objects.filter(tipo__in=['UEB', 'DG'])
        
        # 3. Calculamos en tiempo real (ya no enviamos mes ni año)
        context['datos_tabla'], context['totales'] = self.calcular_consolidado(ueb_id)
        
        return context

    # -- FUNCIONES UTILITARIAS --
    def es_mujer(self, doc):
        if doc and len(doc) == 11 and doc[-2].isdigit():
            return int(doc[-2]) % 2 != 0
        return False

    def mapear_categoria(self, codigo):
        mapa = {'OPE': 'Obreros', 'TEC': 'Técnico', 'CDI': 'Cuadro', 'CEJ': 'Cuadro', 'SER': 'Servicio', 'ADM': 'Administrativo'}
        return mapa.get(codigo, 'Obreros')

    # -- CÁLCULO EN TIEMPO REAL --
    def calcular_consolidado(self, ueb_id):
        datos = {
            'Obreros': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Técnico': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Cuadro': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Servicio': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Administrativo': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
        }

        # Jerarquía (DG -> DF)
        unidades_ids = []
        if ueb_id:
            unidad_seleccionada = UnidadOrganizativa.objects.filter(pk=ueb_id).first()
            if unidad_seleccionada:
                unidades_ids = [unidad_seleccionada.pk]
                if unidad_seleccionada.tipo == 'DG':
                    hijas_ids = unidad_seleccionada.direcciones_hijas.values_list('pk', flat=True)
                    unidades_ids.extend(hijas_ids)

        # Contar Cargos Aprobados, Cubiertos y Vacantes (Directo de la plantilla actual)
        cargos = CargoPlantilla.objects.filter(activo=True)
        if unidades_ids:
            cargos = cargos.filter(departamento__unidad_organizativa_id__in=unidades_ids)
            
        for cargo in cargos:
            cat = self.mapear_categoria(cargo.ncargo.cat_ocupacional)
            aprobadas = cargo.cant_aprobada or 0
            cubiertas = cargo.cant_cubierta or 0
            vacantes = max(aprobadas - cubiertas, 0)
            
            datos[cat]['aprob'] += aprobadas
            datos[cat]['cub'] += cubiertas
            datos[cat]['vac'] += vacantes

        # Contar Contratos activos para sacar las mujeres, determinados y adiestrados
        # AÑADIDO: 'tipo' en select_related para que la base de datos sea super rápida
        contratos = CAlta.objects.select_related('aspirante', 'cargo__ncargo', 'tipo').all()
        if unidades_ids:
            contratos = contratos.filter(cargo__departamento__unidad_organizativa_id__in=unidades_ids)
            
        for c in contratos:
            # Protegemos el código asegurándonos de que tenga cargo y tipo asignado
            if not c.cargo or not c.tipo: continue 
            cat = self.mapear_categoria(c.cargo.ncargo.cat_ocupacional)
            mujer = self.es_mujer(c.aspirante.doc_identidad)
            
            # Convertimos el nombre del nomenclador a mayúsculas para buscar las palabras clave
            desc_tipo = c.tipo.descripcion.upper()
            
            # Buscamos de forma dinámica:
            if 'INDETERMINADO' in desc_tipo:
                if mujer: datos[cat]['p_muj'] += 1
            elif 'ADIESTRAMIENTO' in desc_tipo:
                datos[cat]['a_tot'] += 1
                if mujer: datos[cat]['a_muj'] += 1
            elif 'DETERMINADO' in desc_tipo:
                datos[cat]['d_tot'] += 1
                if mujer: datos[cat]['d_muj'] += 1

        # Sumar los Totales
        totales = {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0, 't_tot':0, 't_muj':0}
        for cat_name, vals in datos.items():
            vals['t_tot'] = vals['cub'] + vals['d_tot'] + vals['a_tot']
            vals['t_muj'] = vals['p_muj'] + vals['d_muj'] + vals['a_muj']
            for k in totales.keys():
                totales[k] += vals[k]

        return datos, totales
    

class ExportarConsolidadoWordView(InformeEconomiaView):
    def get(self, request, *args, **kwargs):
        ueb_id = request.GET.get('ueb', '')
        
        # Forzamos las fechas en tiempo real para imprimir el Word
        hoy = date.today()
        mes = str(hoy.month)
        anno = str(hoy.year)

        # Calculamos los datos
        datos, totales = self.calcular_consolidado(ueb_id)

        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'informes_economia', 'consolidado_template.docx')
        doc = DocxTemplate(template_path)
        
        nombre_ueb = "Empresa Eléctrica Camagüey"
        if ueb_id:
            ueb_obj = UnidadOrganizativa.objects.filter(pk=ueb_id).first()
            if ueb_obj:
                nombre_ueb = ueb_obj.descripcion

        context = {
            'datos': datos,
            'totales': totales,
            'mes': mes,
            'anno': anno,
            'ueb': nombre_ueb
        }
        doc.render(context)
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="Consolidado_{mes}_{anno}.docx"'
        doc.save(response)
        
        return response
    

class ExportarConsolidadoPDFView(InformeEconomiaView):
    def get(self, request, *args, **kwargs):
        ueb_id = request.GET.get('ueb', '')
        
        hoy = date.today()
        mes = str(hoy.month)
        anno = str(hoy.year)

        # Usamos tu misma matemática exacta
        datos, totales = self.calcular_consolidado(ueb_id)

        nombre_ueb = "Empresa Eléctrica Camagüey"
        if ueb_id:
            ueb_obj = UnidadOrganizativa.objects.filter(pk=ueb_id).first()
            if ueb_obj:
                nombre_ueb = ueb_obj.descripcion

        context = {
            'datos': datos,
            'totales': totales,
            'mes': mes,
            'anno': anno,
            'ueb': nombre_ueb
        }

        # 1. Cargamos el HTML que creamos
        template = get_template('pages/reportes/consolidado_pdf.html')
        html = template.render(context)
        
        # 2. Preparamos el navegador para recibir un PDF
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Consolidado_{mes}_{anno}.pdf"'
        
        # 3. Convertimos el HTML a PDF usando xhtml2pdf
        pisa_status = pisa.CreatePDF(html, dest=response)
        
        if pisa_status.err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
            
        return response
    

class InformeTrabajadoresUEBView(TemplateView):
    
    template_name = "pages/informes/informe_ueb.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        context['mes_actual'] = str(hoy.month)
        context['anno_actual'] = str(hoy.year)

        datos_uebs, total_general, total_mujeres = self.calcular_resumen_uebs()
        
        context['datos_uebs'] = datos_uebs
        context['total_general'] = total_general
        context['total_mujeres'] = total_mujeres
        
        return context

    def es_mujer(self, doc):
        if doc and len(doc) == 11 and doc[-2].isdigit():
            return int(doc[-2]) % 2 != 0
        return False

    def calcular_resumen_uebs(self):
        # 1. Buscamos todas las UEB creadas en el sistema ordenadas alfabéticamente
        unidades = UnidadOrganizativa.objects.filter(tipo__in=['UEB', 'DG']).order_by('descripcion')
        
        datos_uebs = []
        total_general = 0
        total_mujeres = 0
        
        # 2. Obtenemos todos los contratos activos (optimizando la consulta a la BD)
        contratos = CAlta.objects.select_related('aspirante', 'cargo__departamento__unidad_organizativa').all()
        
        # 3. Recorremos cada UEB dinámicamente
        for ueb in unidades:
            unidades_ids = [ueb.pk]
            if ueb.tipo == 'DG':
                hijas_ids = ueb.direcciones_hijas.values_list('pk', flat=True)
                unidades_ids.extend(hijas_ids)
                
            # Filtramos los contratos que pertenecen a esta unidad
            contratos_ueb = [c for c in contratos if c.cargo and c.cargo.departamento.unidad_organizativa_id in unidades_ids]
            
            total_ueb = len(contratos_ueb)
            mujeres_ueb = sum(1 for c in contratos_ueb if self.es_mujer(c.aspirante.doc_identidad))
            
            # Guardamos la fila para la tabla del Word y del HTML
            datos_uebs.append({
                'nombre': ueb.descripcion,
                'total': total_ueb,
                'mujeres': mujeres_ueb
            })
            
            # Sumamos a los acumulados del documento
            total_general += total_ueb
            total_mujeres += mujeres_ueb
            
        return datos_uebs, total_general, total_mujeres


class ExportarResumenUEBWordView(InformeTrabajadoresUEBView):
    def get(self, request, *args, **kwargs):
        hoy = date.today()
        mes = str(hoy.month)
        anno = str(hoy.year)

        # Calculamos los datos
        datos_uebs, total_general, total_mujeres = self.calcular_resumen_uebs()

        # Apuntamos a la nueva plantilla que guardaste
        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'informes_economia', 'resumen_ueb_template.docx')
        doc = DocxTemplate(template_path)
        
        # Inyectamos exactamente las variables que le pusiste a las celdas del Word
        context = {
            'uebs': datos_uebs,
            'total_general': total_general,
            'total_mujeres': total_mujeres,
            'mes': mes,
            'anno': anno
        }
        doc.render(context)
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="Resumen_Trabajadores_UEB_{mes}_{anno}.docx"'
        doc.save(response)
        
        return response