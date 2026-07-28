# 1. Librerías Estándar de Python
import os
import calendar
from datetime import date, datetime

# 2. Librerías y Módulos de Django
from django.conf import settings
from django.contrib import messages
from django.db.models import Sum  # <-- AQUÍ ESTÁ EL QUE NECESITAMOS
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import get_template
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from django.views.generic import TemplateView
# 3. Librerías de Terceros
from docxtpl import DocxTemplate
from xhtml2pdf import pisa

# 4. Modelos de tus Propias Aplicaciones
from configuracion.models import Configuracion
from contratos.models import CAlta
from nomencladores.models import NTipoFamilia, NFamiliaCargo, NCargo
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from .models import PlanMensualRegistro

# Create your views here.
class InformeEconomiaView(TemplateView):
    
    def get_template_names(self):
        if self.request.htmx:
            return ['pages/informes/partials/tabla_consolidado.html']
        return ['pages/informes/consolidado_ftrabajo.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Obtenemos el ID de la UEB si el usuario seleccionó alguna
        ueb_id = self.request.GET.get('ueb', '')
        
        # 2. Fechas SIEMPRE en tiempo real
        from datetime import date # Asegúrate de tener este import
        hoy = date.today()
        context['mes_actual'] = str(hoy.month)
        context['anno_actual'] = str(hoy.year)
        context['ueb_actual'] = str(ueb_id)
        
        # LIMPIEZA: Trae Unidades Principales, Normales y Subunidades Independientes
        context['unidades'] = UnidadOrganizativa.objects.select_related('tipo').filter(padre__isnull=True).order_by('orden_informe')
        
        # 3. Calculamos en tiempo real
        context['datos_tabla'], context['totales'] = self.calcular_consolidado(ueb_id)
        
        return context


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

        # Jerarquía Dinámica
        unidades_ids = []
        if ueb_id:
            unidad_seleccionada = UnidadOrganizativa.objects.select_related('tipo').filter(pk=ueb_id).first()
            if unidad_seleccionada:
                unidades_ids = [unidad_seleccionada.pk]
                # Si la unidad seleccionada es de tipo Principal, sumamos todas sus hijas
                if unidad_seleccionada.tipo and unidad_seleccionada.tipo.es_principal:
                    hijas_ids = UnidadOrganizativa.objects.filter(padre=unidad_seleccionada).values_list('pk', flat=True)
                    unidades_ids.extend(hijas_ids)

        # Contar Cargos Aprobados, Cubiertos y Vacantes (Directo de la plantilla actual)
        cargos = CargoPlantilla.objects.filter(activo=True)
        if unidades_ids:
            cargos = cargos.filter(departamento__unidad_organizativa_id__in=unidades_ids)
            
        for cargo in cargos:
            cat = self.mapear_categoria(cargo.ncargo.cat_ocupacional)
            aprobadas = cargo.cant_aprobada or 0
            cubiertas = cargo.cant_cubierta_real
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
            mujer = (c.aspirante.sexo == 'F')
            
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
        from datetime import date
        hoy = date.today()
        context['mes_actual'] = str(hoy.month)
        context['anno_actual'] = str(hoy.year)

        # Llamada correcta al método de la clase
        datos_uebs, total_general, total_mujeres = self.calcular_resumen_uebs()
        
        context['datos_uebs'] = datos_uebs
        context['total_general'] = total_general
        context['total_mujeres'] = total_mujeres
        
        return context


    # Reemplaza la función calcular_resumen_uebs completa por esta:
    def calcular_resumen_uebs(self):
        unidades = UnidadOrganizativa.objects.select_related('tipo').filter(padre__isnull=True).order_by('orden_informe')
        datos_uebs = []
        total_general = 0; total_mujeres = 0
        
        contratos = CAlta.objects.select_related('aspirante', 'cargo__departamento__unidad_organizativa__tipo').all()
        
        for ueb in unidades:
            unidades_ids = [ueb.pk]
            if ueb.tipo and ueb.tipo.es_principal:
                hijas_ids = UnidadOrganizativa.objects.filter(padre=ueb).values_list('pk', flat=True)
                unidades_ids.extend(hijas_ids)
                
            contratos_ueb = [c for c in contratos if c.cargo and c.cargo.departamento and c.cargo.departamento.unidad_organizativa_id in unidades_ids]
            
            total_ueb = len(contratos_ueb)
            mujeres_ueb = sum(1 for c in contratos_ueb if c.aspirante.sexo == 'F')
            
            datos_uebs.append({
                'nombre': ueb.descripcion,
                'es_principal': ueb.tipo.es_principal if ueb.tipo else False,
                'es_subunidad': ueb.tipo.es_subunidad if ueb.tipo else False,
                'total': total_ueb,
                'mujeres': mujeres_ueb
            })
            total_general += total_ueb; total_mujeres += mujeres_ueb
            
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
    

# --- NUEVO INFORME: PUESTOS CLAVES ---

class InformePuestosClaveView(TemplateView):
    template_name = 'pages/informes/informe_puestos_clave.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Filtros
        ueb_id = self.request.GET.get('ueb', '')
        tipo_id = self.request.GET.get('tipo_familia', '')
        mes = self.request.GET.get('mes', str(date.today().month))
        anno = self.request.GET.get('anno', str(date.today().year))
        
        # 2. Tipos de Familia
        tipos_familia = NTipoFamilia.objects.all().order_by('nombre')
        if not tipo_id:
            tipo_id = 'puestos_clave'
            
        # 3. Estructuras
        datos_familias = []
        stats = {'aprobada': 0, 'cubierta': 0, 'vacante': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porcentaje': 0}

        unidades_ids = []
        if ueb_id:
            unidad_obj = UnidadOrganizativa.objects.select_related('tipo').filter(pk=ueb_id).first()
            if unidad_obj:
                unidades_ids = [unidad_obj.pk]
                if unidad_obj.tipo and unidad_obj.tipo.es_principal:
                    hijas_ids = UnidadOrganizativa.objects.filter(padre=unidad_obj).values_list('pk', flat=True)
                    unidades_ids.extend(hijas_ids)

        # 4. Lógica de Agrupación con Subtotales
        # ================================================
        # CASO 1: FILTRO "PUESTOS CLAVE"
        # ================================================
        if tipo_id == 'puestos_clave':
            # Obtenemos todos los NCargos marcados como Puesto Clave
            ncargos_qs = NCargo.objects.filter(puesto_clave=True).order_by('descripcion')
            
            # Creamos una "familia virtual" para agruparlos
            virtual_family_name = '⭐ Puestos Clave'
            f_stats = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}
            puestos_list = []
            
            for ncargo in ncargos_qs:
                # Filtramos las plazas de este cargo (sin necesidad de filtro por puesto_clave, ya lo sabemos)
                cqs = CargoPlantilla.objects.filter(ncargo=ncargo, activo=True)
                if unidades_ids:
                    cqs = cqs.filter(departamento__unidad_organizativa_id__in=unidades_ids)
                    
                if not cqs.exists():
                    continue
                    
                aprob = sum(c.cant_aprobada for c in cqs)
                cub = sum(c.cant_cubierta_real for c in cqs)
                vac = max(aprob - cub, 0)
                
                contratos = CAlta.objects.filter(cargo__in=cqs, aspirante__estado='ACTIVO').select_related('tipo', 'aspirante')
                
                c_det = 0
                c_muj = 0
                c_adiest = 0
                
                for c in contratos:
                    desc_tipo = c.tipo.descripcion.upper() if c.tipo else ""
                    if c.aspirante.sexo == 'F':
                        c_muj += 1
                    if "INDETERMINADO" in desc_tipo:
                        continue
                    elif "DETERMINADO" in desc_tipo:
                        c_det += 1
                    elif "ADIESTRAMIENTO" in desc_tipo:
                        c_adiest += 1
                        
                puestos_list.append({
                    'codigo': ncargo.pk,
                    'nombre': ncargo.descripcion,
                    'aprob': aprob, 'cub': cub, 'vac': vac, 
                    'porc': int((cub / aprob * 100)) if aprob > 0 else 0,
                    'det': c_det, 'muj': c_muj, 'adiest': c_adiest
                })
                
                f_stats['aprob'] += aprob
                f_stats['cub'] += cub
                f_stats['vac'] += vac
                f_stats['det'] += c_det
                f_stats['muj'] += c_muj
                f_stats['adiest'] += c_adiest

            if puestos_list:
                f_stats['porc'] = int((f_stats['cub'] / f_stats['aprob'] * 100)) if f_stats['aprob'] > 0 else 0
                datos_familias.append({
                    'nombre': virtual_family_name,
                    'puestos': puestos_list,
                    'subtotales': f_stats
                })
                stats['aprobada'] += f_stats['aprob']
                stats['cubierta'] += f_stats['cub']
                stats['vacante'] += f_stats['vac']
                stats['det'] += f_stats['det']
                stats['muj'] += f_stats['muj']
                stats['adiest'] += f_stats['adiest']

        # ================================================
        # CASO 2: FILTRO POR TIPO DE FAMILIA (Código original)
        # ================================================
        else:
            # Convertimos a entero para la consulta, manejando posible error
            try:
                tipo_id_int = int(tipo_id)
            except (ValueError, TypeError):
                tipo_id_int = None
                
            if tipo_id_int:
                familias = NFamiliaCargo.objects.filter(tipo_familia_id=tipo_id_int).prefetch_related('cargos')
                
                for familia in familias:
                    puestos_list = []
                    f_stats = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}
                    
                    for ncargo in familia.cargos.all():
                        # Mantenemos el filtro de puesto_clave=True (solo plazas clave dentro de esta familia)
                        cqs = CargoPlantilla.objects.filter(ncargo=ncargo, activo=True, ncargo__puesto_clave=True)
                        if unidades_ids:
                            cqs = cqs.filter(departamento__unidad_organizativa_id__in=unidades_ids)
                            
                        if not cqs.exists():
                            continue
                            
                        aprob = sum(c.cant_aprobada for c in cqs)
                        cub = sum(c.cant_cubierta_real for c in cqs)
                        vac = max(aprob - cub, 0)
                        
                        contratos = CAlta.objects.filter(cargo__in=cqs, aspirante__estado='ACTIVO').select_related('tipo', 'aspirante')
                        
                        c_det = 0
                        c_muj = 0
                        c_adiest = 0
                        
                        for c in contratos:
                            desc_tipo = c.tipo.descripcion.upper() if c.tipo else ""
                            if c.aspirante.sexo == 'F':
                                c_muj += 1
                            if "INDETERMINADO" in desc_tipo:
                                continue
                            elif "DETERMINADO" in desc_tipo:
                                c_det += 1
                            elif "ADIESTRAMIENTO" in desc_tipo:
                                c_adiest += 1
                                
                        puestos_list.append({
                            'codigo': ncargo.pk,
                            'nombre': ncargo.descripcion,
                            'aprob': aprob, 'cub': cub, 'vac': vac, 
                            'porc': int((cub / aprob * 100)) if aprob > 0 else 0,
                            'det': c_det, 'muj': c_muj, 'adiest': c_adiest
                        })
                        
                        f_stats['aprob'] += aprob
                        f_stats['cub'] += cub
                        f_stats['vac'] += vac
                        f_stats['det'] += c_det
                        f_stats['muj'] += c_muj
                        f_stats['adiest'] += c_adiest

                    if puestos_list:
                        f_stats['porc'] = int((f_stats['cub'] / f_stats['aprob'] * 100)) if f_stats['aprob'] > 0 else 0
                        
                        datos_familias.append({
                            'nombre': familia.nombre,
                            'puestos': puestos_list,
                            'subtotales': f_stats
                        })
                        
                        stats['aprobada'] += f_stats['aprob']
                        stats['cubierta'] += f_stats['cub']
                        stats['vacante'] += f_stats['vac']
                        stats['det'] += f_stats['det']
                        stats['muj'] += f_stats['muj']
                        stats['adiest'] += f_stats['adiest']

        if stats['aprobada'] > 0:
            stats['porcentaje'] = int((stats['cubierta'] / stats['aprobada']) * 100)

        dt = datetime.now()
        meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        fecha_es = f"{dias[dt.weekday()]}, {dt.day:02d} de {meses[dt.month - 1]} de {dt.year} | {dt.strftime('%I:%M %p')}"

        context.update({
            'datos_familias': datos_familias,
            'fecha_generacion': fecha_es,
            'stats': stats,
            'tipos_familia': tipos_familia,
            'tipo_actual': tipo_id,
            # Filtramos el combo para no mostrar las subunidades sueltas, solo contenedores o independientes
            'unidades': UnidadOrganizativa.objects.select_related('tipo').filter(padre__isnull=True).order_by('orden_informe'),
            'ueb_actual': ueb_id,
            'mes_actual': mes,
            'anno_actual': anno,
        })
        return context


class ExportarPuestosClaveWordView(InformePuestosClaveView):
    def get(self, request, *args, **kwargs):
        # Obtenemos la data agrupada por familias directamente del contexto general
        context = self.get_context_data(**kwargs)
        
        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'informes_economia', 'puestos_clave_template.docx')
        
        try:
            doc = DocxTemplate(template_path)
            doc.render(context)
            
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            filename = f'Puestos_Clave_{context.get("mes_actual")}_{context.get("anno_actual")}.docx'
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarPuestosClavePDFView(InformePuestosClaveView):
    def get(self, request, *args, **kwargs):
        # 1. Obtenemos la data de la vista principal
        context = self.get_context_data(**kwargs)
        
        # 2. Inyección del Logo con Ruta Física Absoluta
        from configuracion.models import Configuracion # Ajusta a tu app
        config = Configuracion.objects.first()
        context['config'] = config
        context['nombre_empresa'] = config.nombre_empresa if config else "Empresa Eléctrica"

        # 3. Renderizar PDF
        template = get_template('pages/reportes/puestos_clave_pdf.html')
        html = template.render(context)
        
        response = HttpResponse(content_type='application/pdf')
        filename = f'Puestos_Clave_{context.get("mes_actual")}_{context.get("anno_actual")}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        pisa_status = pisa.CreatePDF(html, dest=response)
        if pisa_status.err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
            
        return response
    

#Nuevo Informe:
class InformeMisionesView(TemplateView):
    template_name = "pages/informes/informe_misiones.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from datetime import date
        hoy = date.today()
        context['mes_actual'] = str(hoy.month)
        context['anno_actual'] = str(hoy.year)

        # 1. Traer solo los contratos en misión
        # Asumiendo que el campo se llama 'mision' (Boolean) y 'pais' (Char)
        contratos = CAlta.objects.filter(mision=True).select_related(
            'aspirante', 
            'cargo__ncargo__grupo_escala', 
            'cargo__departamento__unidad_organizativa'
        )

        # 2. Variables de conteo
        total_misiones = contratos.count()
        importe_total = 0.00  # Queda en 0 hasta que la empresa lo defina
        
        desglose = {
            'Obreros': 0,
            'Servicios': 0,
            'Administrativos': 0,
            'Técnicos': 0,
            'Cuadros': 0
        }

        # 3. Agrupación por UEB (ESTRUCTURA COMPATIBLE CON TU HTML)
        datos_por_ueb = {} 
        orden_map = {}     

        for c in contratos:
            ueb_obj = c.cargo.departamento.unidad_organizativa if c.cargo and c.cargo.departamento else None
            ueb_nombre = ueb_obj.descripcion if ueb_obj else "Sin Unidad"
            orden = ueb_obj.orden_informe if ueb_obj and ueb_obj.orden_informe else 999
            
            cat_sigla = c.cargo.ncargo.cat_ocupacional if c.cargo and c.cargo.ncargo else ""
            if cat_sigla == 'OPE': desglose['Obreros'] += 1
            elif cat_sigla == 'SER': desglose['Servicios'] += 1
            elif cat_sigla == 'ADM': desglose['Administrativos'] += 1
            elif cat_sigla == 'TEC': desglose['Técnicos'] += 1
            elif cat_sigla in ['CDI', 'CEJ']: desglose['Cuadros'] += 1

            # Si es la primera vez que vemos esta unidad, inicializamos como LISTA
            if ueb_nombre not in datos_por_ueb:
                datos_por_ueb[ueb_nombre] = []
                orden_map[ueb_nombre] = orden

            # Guardamos el diccionario directamente en la lista (esto es lo que tu HTML espera)
            datos_por_ueb[ueb_nombre].append({
                'expediente': c.no_expediente,
                'nombre': f"{c.aspirante.nombre} {c.aspirante.papellido} {c.aspirante.sapellido or ''}".strip(),
                'cargo': c.cargo.ncargo.descripcion if c.cargo and c.cargo.ncargo else "-",
                'cat_letra': cat_sigla[0] if cat_sigla else "-", 
                'g_escala': c.cargo.ncargo.grupo_escala.nivel if c.cargo and c.cargo.ncargo and c.cargo.ncargo.grupo_escala else "-",
                'pais': getattr(c, 'pais', '-'), 'dias': 0, 'importe': 0.00
            })

        # Ordenamos las llaves según el mapa de orden y reconstruimos
        sorted_keys = sorted(orden_map.keys(), key=lambda k: orden_map[k])
        uebs_ordenadas = {k: datos_por_ueb[k] for k in sorted_keys}

        context['total_misiones'] = total_misiones
        context['importe_total'] = importe_total
        context['desglose'] = desglose
        context['uebs'] = uebs_ordenadas # Ahora es {Nombre: [lista_trabajadores]}
        return context
    
class RegistroDiarioView(TemplateView):
    template_name = "pages/informes/registro_diario.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from datetime import date
        hoy = date.today()
        mes_actual = self.request.GET.get('mes', str(hoy.month))
        anno_actual = self.request.GET.get('anno', str(hoy.year))
        
        ueb_filtro = self.request.GET.get('ueb', '')
        familia_filtro = self.request.GET.get('tipo_familia', '')

        # 1. Traer contratos activos
        contratos = CAlta.objects.select_related('aspirante', 'cargo__ncargo').all()

        # --- LÓGICA DE UNIDADES Y SUBUNIDADES (Padres e Hijas) ---
        unidades_ids = []
        if ueb_filtro:
            # Añadimos la unidad seleccionada (que puede ser padre o hija)
            unidades_ids.append(ueb_filtro)
            
            # Buscamos si tiene hijas usando el campo 'padre_id' que me mostraste en tu modelo
            hijas_ids = UnidadOrganizativa.objects.filter(padre_id=ueb_filtro).values_list('codigo_interno', flat=True)
            if hijas_ids:
                unidades_ids.extend(list(hijas_ids))

        # --- APLICAR FILTROS A LOS CONTRATOS ---
        if unidades_ids:
            # Filtramos los contratos cuyo departamento pertenezca a la unidad padre O a sus hijas
            contratos = contratos.filter(cargo__departamento__unidad_organizativa_id__in=unidades_ids)
        if familia_filtro:
            contratos = contratos.filter(cargo__ncargo__familia_id=familia_filtro)

        # 2. Diccionario de contadores
        # OPE=Obreros, TEC=Técnicos, ADM=Administrativos, SER=Servicios, CDI/CEJ=Cuadros
        datos = {
            'Obreros': {'tot': 0, 'muj': 0},
            'Técnicos': {'tot': 0, 'muj': 0},
            'Administrativos': {'tot': 0, 'muj': 0},
            'Servicios': {'tot': 0, 'muj': 0},
            'Cuadros': {'tot': 0, 'muj': 0},
            'Misiones': {'tot': 0, 'muj': 0}
        }

        for c in contratos:
            cat = c.cargo.ncargo.cat_ocupacional if c.cargo and c.cargo.ncargo else ""
            es_mujer = c.aspirante.sexo == 'F'

            # Contar Misiones
            if c.mision:
                datos['Misiones']['tot'] += 1
                if es_mujer: datos['Misiones']['muj'] += 1

            # Contar por Categoría
            llave = None
            if cat == 'OPE': llave = 'Obreros'
            elif cat == 'TEC': llave = 'Técnicos'
            elif cat == 'ADM': llave = 'Administrativos'
            elif cat == 'SER': llave = 'Servicios'
            elif cat in ['CDI', 'CEJ']: llave = 'Cuadros'

            if llave:
                datos[llave]['tot'] += 1
                if es_mujer: datos[llave]['muj'] += 1

       # --- 3. Buscar el Plan Editable (PlanMensualRegistro) ---
        
        # Intentar buscar un plan manual guardado previamente para este filtro
        plan_guardado = PlanMensualRegistro.objects.filter(
            mes=mes_actual,
            anno=anno_actual,
            ueb_id=ueb_filtro,
            familia_id=familia_filtro
        ).first()

        if plan_guardado:
            # Si existe en BD, usamos ese
            valor_plan = plan_guardado.valor
        else:
            # Si no existe, calculamos el de CargoPlantilla por defecto
            plazas_query = CargoPlantilla.objects.filter(activo=True)
            if unidades_ids:
                plazas_query = plazas_query.filter(departamento__unidad_organizativa_id__in=unidades_ids)
            if familia_filtro:
                plazas_query = plazas_query.filter(ncargo__familia_id=familia_filtro)
                
            valor_plan = plazas_query.aggregate(total=Sum('cant_aprobada'))['total'] or 0

        # Enviar al contexto
        context['mes_actual'] = mes_actual
        context['anno_actual'] = anno_actual
        context['ueb_actual'] = ueb_filtro
        context['tipo_actual'] = familia_filtro
        context['datos'] = datos
        context['plan_editable'] = valor_plan
        # Para los combos (Ajusta NFamiliaCargo a tu modelo real)
        context['unidades'] = UnidadOrganizativa.objects.select_related('tipo').filter(padre__isnull=True).order_by('orden_informe')
        # context['tipos_familia'] = NFamiliaCargo.objects.all() 

        return context

# Vista para que JavaScript guarde el plan con Doble Clic sin recargar
class GuardarPlanDiarioView(View):
    def post(self, request, *args, **kwargs):
        import json
        data = json.loads(request.body)
        
        plan, created = PlanMensualRegistro.objects.update_or_create(
            mes=data.get('mes'),
            anno=data.get('anno'),
            ueb_id=data.get('ueb', ''),
            familia_id=data.get('familia', ''),
            defaults={'valor': int(data.get('valor', 0))}
        )
        return JsonResponse({'status': 'ok', 'nuevo_valor': plan.valor})\
        
class InformeMotivosContratoView(TemplateView):
    template_name = "pages/informes/informe_motivos_contrato.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        
        # 1. CAPTURAR EL FILTRO DE LA URL
        ueb_id = self.request.GET.get('ueb', '')
        
        # Consulta base
        contratos_qs = CAlta.objects.filter(
            aspirante__estado='ACTIVO',
            tipo__requiere_motivo=True
        )

        # Lógica de cascada: Si hay filtro, sumar las hijas si es Unidad Principal
        if ueb_id:
            unidad_seleccionada = UnidadOrganizativa.objects.select_related('tipo').filter(pk=ueb_id).first()
            if unidad_seleccionada:
                unidades_ids = [unidad_seleccionada.pk]
                if unidad_seleccionada.tipo and unidad_seleccionada.tipo.es_principal:
                    hijas_ids = UnidadOrganizativa.objects.filter(padre=unidad_seleccionada).values_list('pk', flat=True)
                    unidades_ids.extend(hijas_ids)
                contratos_qs = contratos_qs.filter(cargo__departamento__unidad_organizativa_id__in=unidades_ids)

        # 2. ORDENAR POR ORDEN_INFORME EN VEZ DE DESCRIPCIÓN
        contratos = contratos_qs.select_related(
            'aspirante',
            'cargo__ncargo__grupo_escala',
            'cargo__departamento__unidad_organizativa__tipo',
            'tipo',
            'motivo'
        ).order_by(
            'tipo__descripcion',
            'motivo__descripcion',
            'cargo__departamento__unidad_organizativa__orden_informe', # <-- CAMBIADO AQUÍ
            'aspirante__nombre'
        )

        total_contratos = 0
        total_mujeres = 0
        total_hombres = 0
        vencen_critico = 0
        vencen_alerta = 0
        vencen_vigente = 0
        cat_t = cat_o = cat_s = cat_a = cat_c = 0 
        conteo_motivos = {} 
        
        datos_agrupados = {}

        for c in contratos:
            total_contratos += 1
            
            if c.aspirante.sexo == 'F': total_mujeres += 1
            elif c.aspirante.sexo == 'M': total_hombres += 1
                
            cat = c.cargo.ncargo.cat_ocupacional if c.cargo and c.cargo.ncargo else None
            if cat == 'TEC': cat_t += 1
            elif cat == 'OPE': cat_o += 1
            elif cat == 'SER': cat_s += 1
            elif cat == 'ADM': cat_a += 1
            elif cat in ['CDI', 'CEJ']: cat_c += 1
            
            if c.dias_restantes is not None:
                if c.dias_restantes <= 15: vencen_critico += 1
                elif c.dias_restantes <= 30: vencen_alerta += 1
                else: vencen_vigente += 1
            
            tipo_desc = c.tipo.descripcion if c.tipo else "Sin Tipo Asignado"
            motivo_desc = c.motivo.descripcion if c.motivo else "Sin Motivo Asignado"
            
            ueb_obj = c.cargo.departamento.unidad_organizativa if c.cargo and c.cargo.departamento else None
            ueb_desc = ueb_obj.descripcion if ueb_obj else "Sin Unidad Organizativa"
            ueb_color = ueb_obj.tipo.color if ueb_obj and ueb_obj.tipo and ueb_obj.tipo.color else "#697a8d"
            
            # 3. EXTRAER LAS BANDERAS PARA EL HTML
            es_p = ueb_obj.tipo.es_principal if ueb_obj and ueb_obj.tipo else False
            es_s = ueb_obj.tipo.es_subunidad if ueb_obj and ueb_obj.tipo else False
            
            conteo_motivos[motivo_desc] = conteo_motivos.get(motivo_desc, 0) + 1
            
            if tipo_desc not in datos_agrupados:
                datos_agrupados[tipo_desc] = {'total': 0, 'motivos': {}}
            datos_agrupados[tipo_desc]['total'] += 1

            if motivo_desc not in datos_agrupados[tipo_desc]['motivos']:
                datos_agrupados[tipo_desc]['motivos'][motivo_desc] = {'total': 0, 'uebs': {}}
            datos_agrupados[tipo_desc]['motivos'][motivo_desc]['total'] += 1

            if ueb_desc not in datos_agrupados[tipo_desc]['motivos'][motivo_desc]['uebs']:
                datos_agrupados[tipo_desc]['motivos'][motivo_desc]['uebs'][ueb_desc] = {
                    'color': ueb_color,
                    'es_p': es_p,  # <-- ENVIAMOS A HTML
                    'es_s': es_s,  # <-- ENVIAMOS A HTML
                    'contratos': []
                }
                
            datos_agrupados[tipo_desc]['motivos'][motivo_desc]['uebs'][ueb_desc]['contratos'].append(c)

        conteo_motivos_ordenado = dict(sorted(conteo_motivos.items(), key=lambda item: item[1], reverse=True))

        mayor_motivo_nombre = "Sin Datos"
        mayor_motivo_count = 0
        mayor_motivo_porc = 0
        
        if conteo_motivos_ordenado:
            mayor_motivo_nombre = list(conteo_motivos_ordenado.keys())[0]
            mayor_motivo_count = conteo_motivos_ordenado[mayor_motivo_nombre]
            mayor_motivo_porc = int((mayor_motivo_count / total_contratos) * 100) if total_contratos > 0 else 0

        lista_motivos = []
        for m_nom, m_count in conteo_motivos_ordenado.items():
            m_porc = int((m_count / total_contratos) * 100) if total_contratos > 0 else 0
            lista_motivos.append({'nombre': m_nom, 'count': m_count, 'porc': m_porc})

        lista_categorias = [
            {'nombre': '[C] Cuadros', 'count': cat_c},
            {'nombre': '[T] Técnicos', 'count': cat_t},
            {'nombre': '[A] Administrativos', 'count': cat_a},
            {'nombre': '[O] Obreros', 'count': cat_o},
            {'nombre': '[S] Servicios', 'count': cat_s},
        ]
        lista_categorias.sort(key=lambda x: x['count'], reverse=True)

        colores_jerarquia = ['#E63946', '#F4A261', '#E9C46A', '#2A9D8F', '#A8DADC']
        current_color_idx = 0

        for i, item in enumerate(lista_categorias):
            if i > 0 and item['count'] < lista_categorias[i-1]['count']:
                current_color_idx = min(current_color_idx + 1, 4)
            item['color'] = colores_jerarquia[current_color_idx]
            item['porc'] = int((item['count'] / total_contratos * 100)) if total_contratos else 0

        porc_mujeres = round((total_mujeres / total_contratos * 100) if total_contratos else 0, 1)
        porc_hombres = round((total_hombres / total_contratos * 100) if total_contratos else 0, 1)

        context.update({
            'datos_agrupados': datos_agrupados,
            'total_contratos': total_contratos,
            'total_mujeres': total_mujeres,
            'total_hombres': total_hombres,
            'porc_mujeres': porc_mujeres,
            'porc_hombres': porc_hombres,
            'categorias_ordenadas': lista_categorias,
            'lista_motivos': lista_motivos,
            'vencen_critico': vencen_critico,
            'vencen_alerta': vencen_alerta,
            'vencen_vigente': vencen_vigente,
            'mayor_motivo_nombre': mayor_motivo_nombre,
            'mayor_motivo_count': mayor_motivo_count,
            'mayor_motivo_porc': mayor_motivo_porc,
            'mes_actual': hoy.strftime("%B").capitalize(),
            'anno_actual': hoy.year,
            # 4. ENVIAR LAS UNIDADES Y EL FILTRO ACTUAL AL TEMPLATE
            'unidades': UnidadOrganizativa.objects.select_related('tipo').filter(padre__isnull=True).order_by('orden_informe'),
            'ueb_actual': ueb_id,
        })
        
        return context