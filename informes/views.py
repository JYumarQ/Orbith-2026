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

# 3. Librerías de Terceros
from docxtpl import DocxTemplate
from xhtml2pdf import pisa

# 4. Modelos de tus Propias Aplicaciones
from configuracion.models import Configuracion
from contratos.models import CAlta
from nomencladores.models import NTipoFamilia, NFamiliaCargo
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
        
        # CORRECCIÓN: Filtramos por la descripción del nomenclador
        context['unidades'] = UnidadOrganizativa.objects.filter(tipo__descripcion__in=['UEB', 'DG'])
        
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

        # Jerarquía (DG -> DF)
        unidades_ids = []
        if ueb_id:
            unidad_seleccionada = UnidadOrganizativa.objects.filter(pk=ueb_id).first()
            if unidad_seleccionada:
                unidades_ids = [unidad_seleccionada.pk]
                if unidad_seleccionada.tipo.descripcion == 'DG':
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


    def calcular_resumen_uebs(self):
        # 1. CORRECCIÓN: Filtramos por el campo descripción del nomenclador
        unidades = UnidadOrganizativa.objects.filter(
            tipo__descripcion__in=['UEB', 'DG']
        ).order_by('descripcion')
        
        datos_uebs = []
        total_general = 0
        total_mujeres = 0
        
        # 2. Optimizamos la consulta cargando también el 'tipo' de la unidad
        contratos = CAlta.objects.select_related(
            'aspirante', 
            'cargo__departamento__unidad_organizativa__tipo'
        ).all()
        
        # 3. Recorremos cada UEB
        for ueb in unidades:
            unidades_ids = [ueb.pk]
            
            # CORRECCIÓN: Comparamos la descripción, no el objeto
            if ueb.tipo.descripcion == 'DG':
                hijas_ids = ueb.direcciones_hijas.values_list('pk', flat=True)
                unidades_ids.extend(hijas_ids)
                
            contratos_ueb = [
                c for c in contratos 
                if c.cargo and c.cargo.departamento.unidad_organizativa_id in unidades_ids
            ]
            
            total_ueb = len(contratos_ueb)
            mujeres_ueb = sum(1 for c in contratos_ueb if c.aspirante.sexo == 'F')
            
            datos_uebs.append({
                'nombre': ueb.descripcion,
                'total': total_ueb,
                'mujeres': mujeres_ueb
            })
            
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
        if not tipo_id and tipos_familia.exists():
            tipo_id = tipos_familia.first().pk
            
        # 3. Estructuras
        datos_familias = []
        stats = {'aprobada': 0, 'cubierta': 0, 'vacante': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porcentaje': 0}

        unidades_ids = []
        if ueb_id:
            unidad_obj = UnidadOrganizativa.objects.filter(pk=ueb_id).first()
            if unidad_obj:
                unidades_ids = [unidad_obj.pk]
                if unidad_obj.tipo.descripcion == 'DG':
                    unidades_ids.extend(unidad_obj.direcciones_hijas.values_list('pk', flat=True))

        # 4. Lógica de Agrupación con Subtotales
        if tipo_id:
            familias = NFamiliaCargo.objects.filter(tipo_familia_id=tipo_id).prefetch_related('cargos')
            
            for familia in familias:
                puestos_list = []
                # Inicializamos subtotales para esta familia específica
                f_stats = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}
                
                for ncargo in familia.cargos.all():
                    # Solo plazas marcadas como PUESTO CLAVE
                    cqs = CargoPlantilla.objects.filter(ncargo=ncargo, activo=True, ncargo__puesto_clave=True)
                    if unidades_ids:
                        cqs = cqs.filter(departamento__unidad_organizativa_id__in=unidades_ids)
                        
                    if not cqs.exists():
                        continue
                        
                    aprob = sum(c.cant_aprobada for c in cqs)
                    cub = sum(c.cant_cubierta_real for c in cqs)
                    vac = max(aprob - cub, 0)
                    
                    # Contratos vinculados (Determinados, Adiestramiento, Mujeres)
                    contratos = CAlta.objects.filter(cargo__in=cqs, aspirante__estado='ACTIVO').select_related('tipo', 'aspirante')
                    
                    c_det = 0
                    c_muj = 0
                    c_adiest = 0
                    
                    for c in contratos:
                        desc_tipo = c.tipo.descripcion.upper() if c.tipo else ""
                        
                        # 1. Lógica de Género (Leyendo directamente el campo 'sexo' del modelo Aspirante)
                        if c.aspirante.sexo == 'F':
                            c_muj += 1
                        
                        # 2. Lógica de Contratos (CORREGIDA para evitar solapamiento)
                        if "INDETERMINADO" in desc_tipo:
                            continue # No sumamos los indeterminados a las columnas de "Determinados"
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
                    
                    # Acumular Subtotales de Familia (Corregido el error de Pylance)
                    f_stats['aprob'] += aprob
                    f_stats['cub'] += cub
                    f_stats['vac'] += vac
                    f_stats['det'] += c_det
                    f_stats['muj'] += c_muj
                    f_stats['adiest'] += c_adiest

                if puestos_list:
                    # Calcular % de la familia
                    f_stats['porc'] = int((f_stats['cub'] / f_stats['aprob'] * 100)) if f_stats['aprob'] > 0 else 0
                    
                    datos_familias.append({
                        'nombre': familia.nombre,
                        'puestos': puestos_list,
                        'subtotales': f_stats # <-- Enviamos los totales de la fila azul
                    })
                    
                    # Acumular KPIs Globales
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
            'tipo_actual': int(tipo_id) if tipo_id else '',
            'unidades': UnidadOrganizativa.objects.all(),
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

        # 3. Agrupación por UEB
        datos_por_ueb = {}

        for c in contratos:
            # Determinar Unidad
            ueb_nombre = c.cargo.departamento.unidad_organizativa.descripcion if c.cargo and c.cargo.departamento else "Sin Unidad"
            
            # Determinar Categoría y Contar
            cat_sigla = c.cargo.ncargo.cat_ocupacional if c.cargo and c.cargo.ncargo else ""
            
            if cat_sigla == 'OPE':
                desglose['Obreros'] += 1
            elif cat_sigla == 'SER':
                desglose['Servicios'] += 1
            elif cat_sigla == 'ADM':
                desglose['Administrativos'] += 1
            elif cat_sigla == 'TEC':
                desglose['Técnicos'] += 1
            elif cat_sigla in ['CDI', 'CEJ']:
                desglose['Cuadros'] += 1

            if ueb_nombre not in datos_por_ueb:
                datos_por_ueb[ueb_nombre] = []

            # Agregar trabajador a su respectiva UEB
            datos_por_ueb[ueb_nombre].append({
                'expediente': c.no_expediente,
                'nombre': f"{c.aspirante.nombre} {c.aspirante.papellido} {c.aspirante.sapellido or ''}".strip(),
                'cargo': c.cargo.ncargo.descripcion if c.cargo and c.cargo.ncargo else "-",
                'cat_letra': cat_sigla[0] if cat_sigla else "-", # T, A, O, S, C
                'g_escala': c.cargo.ncargo.grupo_escala.nivel if c.cargo and c.cargo.ncargo and c.cargo.ncargo.grupo_escala else "-",
                'pais': getattr(c, 'pais', '-'), # Leemos el país
                'dias': 0,
                'importe': 0.00
            })

        context['total_misiones'] = total_misiones
        context['importe_total'] = importe_total
        context['desglose'] = desglose
        context['uebs'] = datos_por_ueb

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
        # OPE=Obreros, TEC=Técnicos, ADM=Administrativos, SER=Servicios, CDI/CEJ=Dirigentes
        datos = {
            'Obreros': {'tot': 0, 'muj': 0},
            'Técnicos': {'tot': 0, 'muj': 0},
            'Administrativos': {'tot': 0, 'muj': 0},
            'Servicios': {'tot': 0, 'muj': 0},
            'Dirigentes': {'tot': 0, 'muj': 0},
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
            elif cat in ['CDI', 'CEJ']: llave = 'Dirigentes'

            if llave:
                datos[llave]['tot'] += 1
                if es_mujer: datos[llave]['muj'] += 1

        # --- 3. Buscar el Plan Real de Plazas Aprobadas (Plantilla Oficial) ---
        plazas_query = CargoPlantilla.objects.filter(activo=True)

        # Aplicamos la MISMA lista de unidades (padre + hijas) para sumar las plazas
        if unidades_ids:
            plazas_query = plazas_query.filter(departamento__unidad_organizativa_id__in=unidades_ids)
        if familia_filtro:
            plazas_query = plazas_query.filter(ncargo__familia_id=familia_filtro)

        # Sumamos la columna 'cant_aprobada' de todas las plazas agrupadas
        valor_plan = plazas_query.aggregate(total=Sum('cant_aprobada'))['total'] or 0

        # Enviar al contexto
        context['mes_actual'] = mes_actual
        context['anno_actual'] = anno_actual
        context['ueb_actual'] = ueb_filtro
        context['tipo_actual'] = familia_filtro
        context['datos'] = datos
        context['plan_editable'] = valor_plan
        # Para los combos (Ajusta NFamiliaCargo a tu modelo real)
        context['unidades'] = UnidadOrganizativa.objects.all()
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
        return JsonResponse({'status': 'ok', 'nuevo_valor': plan.valor})