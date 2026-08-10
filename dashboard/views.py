from contratos.models import CAlta, CBaja
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
#from .models import Objeto
from django.urls import reverse_lazy
from strorganizativa.models import CargoPlantilla, UnidadOrganizativa
import os
from django.conf import settings
from django.http import HttpResponse
from docxtpl import DocxTemplate
import calendar
from datetime import date, timedelta
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.views.generic import TemplateView
from datetime import datetime
import json

from .filtros import resolver_filtros

# Cortes por defecto de la Pirámide de Edades (única fuente de verdad: de aquí
# salen tanto los buckets del bucle maestro como las categorías del eje X del
# gráfico — ver `_cortes_edad_desde_request` y `_categorias_edad`).
CORTES_EDAD_DEFECTO = [25, 35, 45, 55, 65]
EDAD_MIN_RAZONABLE = 16
EDAD_MAX_RAZONABLE = 90


def _cortes_edad_desde_request(request):
    """Parsea `?cortes=25,35,45,55,65` de forma estricta y todo-o-nada.

    Si cualquier token no es un entero, algún valor cae fuera del rango
    laboral razonable, o la lista no es estrictamente creciente, se descarta
    la entrada COMPLETA y se usan los cortes por defecto — nunca se corrige
    parcialmente (p.ej. quitando solo el valor inválido).
    """
    crudo = (request.GET.get('cortes') or '').strip()
    if not crudo:
        return list(CORTES_EDAD_DEFECTO)

    tokens = [t.strip() for t in crudo.split(',') if t.strip()]
    if not tokens:
        return list(CORTES_EDAD_DEFECTO)

    cortes = []
    for t in tokens:
        if not t.lstrip('-').isdigit():
            return list(CORTES_EDAD_DEFECTO)
        cortes.append(int(t))

    if any(c < EDAD_MIN_RAZONABLE or c > EDAD_MAX_RAZONABLE for c in cortes):
        return list(CORTES_EDAD_DEFECTO)

    if any(cortes[i] >= cortes[i + 1] for i in range(len(cortes) - 1)):
        return list(CORTES_EDAD_DEFECTO)

    return cortes


def _categorias_edad(cortes):
    """Etiquetas de bucket a partir de los cortes: ['≤25','26-35',...,'66+']."""
    categorias = [f"≤{cortes[0]}"]
    for i in range(len(cortes) - 1):
        categorias.append(f"{cortes[i] + 1}-{cortes[i + 1]}")
    categorias.append(f"{cortes[-1] + 1}+")
    return categorias


def _bucket_edad(edad, cortes):
    """Índice de bucket para `edad` según la lista de cortes (búsqueda lineal,
    la cantidad de cortes es siempre pequeña)."""
    for i, corte in enumerate(cortes):
        if edad <= corte:
            return i
    return len(cortes)


# Create your views here.
class DashboardView(TemplateView):
    template_name = "pages/dashboard.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        
        # ========== DEFINIR MESES AQUÍ (antes de cualquier uso) ==========
        meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

        # ========== FILTROS GLOBALES (UO / Departamento) ==========
        # `resolver_filtros` ya valida los ids pedidos contra el alcance real
        # del usuario (ver dashboard/filtros.py) — nunca se confía en lo que
        # llegue crudo por querystring.
        uo_ids, depto_ids, filtro_ctx = resolver_filtros(self.request)
        context.update(filtro_ctx)

        def _filtrar_por_uo_depto(qs, campo_departamento):
            """`campo_departamento` es la ruta ORM hasta Departamento
            (p.ej. 'cargo__departamento') a partir de la cual se cuelga
            `__unidad_organizativa_id` / `_id`."""
            if depto_ids:
                qs = qs.filter(**{f"{campo_departamento}_id__in": depto_ids})
            elif uo_ids:
                qs = qs.filter(**{f"{campo_departamento}__unidad_organizativa_id__in": uo_ids})
            return qs

        # 1. Consultas Base (Optimizadas)
        activos = CAlta.objects.filter(aspirante__estado='ACTIVO').select_related(
            'aspirante', 'tipo', 'cargo__ncargo', 'cargo__departamento', 'cargo__nivel_preparacion'
        )
        activos = _filtrar_por_uo_depto(activos, 'cargo__departamento')

        todos_altas = CAlta.objects.all().select_related('aspirante', 'tipo')
        todos_altas = _filtrar_por_uo_depto(todos_altas, 'cargo__departamento')

        todas_bajas = CBaja.objects.all().select_related('causa_baja')
        todas_bajas = _filtrar_por_uo_depto(todas_bajas, 'cargo__departamento')

        # Variables directas para las tarjetas
        context['contratos_count'] = activos.count()
        # Estructura: cuenta Unidades Organizativas de primer nivel (padre=None).
        # Una UO padre cuenta 1, sus subunidades (padre no nulo) no se cuentan aparte.
        # No depende del filtro: es un dato de la estructura organizativa, no de
        # la plantilla filtrada.
        context['uo_count'] = UnidadOrganizativa.objects.filter(padre__isnull=True).count()
        context['plazas'] = self.get_plazas(uo_ids, depto_ids)

        # Nuevas Altas / Nuevas Bajas (ventana móvil de 30 días, distinta del
        # histórico mensual de más abajo). Las altas se combinan con CBaja.fecha_alta
        # porque CAlta se borra al causar baja (histórico inmutable): sin esto, quien
        # fue contratado y ya se fue dentro de la ventana desaparecería del conteo.
        hace_30 = hoy - timedelta(days=30)
        context['altas_30d'] = (
            _filtrar_por_uo_depto(CAlta.objects.filter(fecha_alta__range=(hace_30, hoy)), 'cargo__departamento').count()
            + _filtrar_por_uo_depto(CBaja.objects.filter(fecha_alta__range=(hace_30, hoy)), 'cargo__departamento').count()
        )
        context['bajas_30d'] = _filtrar_por_uo_depto(
            CBaja.objects.filter(fecha_baja__range=(hace_30, hoy)), 'cargo__departamento'
        ).count()

        # 2. Diccionarios y contadores inicializados en 0 (Evita que el JS falle si no hay datos)
        cumpleaneros = []
        avisos_contratos = []
        pre_jubilacion = []
        recontratados = []
        jubilados_recontratados = []

        cat_ocupacional = {'OPE': 0, 'TEC': 0, 'ADM': 0, 'SER': 0, 'CUA': 0}
        nivel_educ_counts = {}
        nivel_prep_counts = {}
        tipos_contrato_counts = {}
        raza_counts = {}
        reg_militar_counts = {}

        # Pirámide de Edades: cortes validados (o los de defecto) son la ÚNICA
        # fuente de verdad, tanto para el bucketing de aquí abajo como para las
        # categorías del eje X que recibe el template (ver _categorias_edad).
        cortes_edad = _cortes_edad_desde_request(self.request)
        context['edades_categorias'] = json.dumps(_categorias_edad(cortes_edad))
        context['edades_cortes_str'] = ','.join(str(c) for c in cortes_edad)
        n_buckets = len(cortes_edad) + 1
        edades_m = [0] * n_buckets
        edades_f = [0] * n_buckets
        hombres = mujeres = 0
        total_salario_empresa = 0

        # --- BUCLE MAESTRO ---
        for c in activos:
            asp = c.aspirante
            sexo = asp.sexo
            
            # Géneros
            if sexo == 'M': hombres += 1
            elif sexo == 'F': mujeres += 1

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

            # Registro Militar
            reg = c.get_reg_militar_display() if c.reg_militar else 'No Definido'
            reg_militar_counts[reg] = reg_militar_counts.get(reg, 0) + 1

            # Salario Escala Promedio
            salario = c.salario_total or 0
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

            nombre_full = f"{asp.nombre} {asp.papellido}"

            if c.jubilado_recontratado:
                cargo_desc_jr = c.cargo.ncargo.descripcion if c.cargo and getattr(c.cargo, 'ncargo', None) else '-'
                jubilados_recontratados.append({
                    'nombre': nombre_full, 'edad': edad, 'sexo': sexo, 'cargo': cargo_desc_jr
                })

            if edad is not None:
                idx = _bucket_edad(edad, cortes_edad)
                if sexo == 'M': edades_m[idx] += 1
                elif sexo == 'F': edades_f[idx] += 1

                cargo_desc = c.cargo.ncargo.descripcion if c.cargo and getattr(c.cargo, 'ncargo', None) else '-'
                # `dias_hasta_jubilacion` centraliza (en `bolsa/models.py`) el mismo
                # criterio de edad por sexo que antes estaba en línea aquí: no-None y
                # <=0 significa "ya alcanzó la edad mínima de pre-jubilación pero no ha
                # superado la ventana", exactamente el rango que antes comprobaban las
                # condiciones 58<=edad<=60 / 63<=edad<=65.
                if asp.dias_hasta_jubilacion is not None and asp.dias_hasta_jubilacion <= 0:
                    pre_jubilacion.append({'nombre': nombre_full, 'edad': edad, 'sexo': sexo, 'cargo': cargo_desc})
                elif sexo == 'F' and edad > 60:
                    recontratados.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'F', 'cargo': cargo_desc})
                elif sexo == 'M' and edad > 65:
                    recontratados.append({'nombre': nombre_full, 'edad': edad, 'sexo': 'M', 'cargo': cargo_desc})

            # I) Distribución por Raza
            raza = asp.get_raza_display() if hasattr(asp, 'get_raza_display') and asp.raza else 'No Definida'
            raza_counts[raza] = raza_counts.get(raza, 0) + 1 # <--- 2. AÑADIR ESTE BLOQUE

        # --- 3. ORDENACIÓN Y EMPAQUETADO ---
        cumpleaneros.sort(key=lambda x: x['dias'])
        avisos_contratos.sort(key=lambda x: x['dias'])
        pre_jubilacion.sort(key=lambda x: x['edad'], reverse=True)
        recontratados.sort(key=lambda x: x['edad'], reverse=True)
        jubilados_recontratados.sort(key=lambda x: (x['edad'] is None, x['edad']), reverse=True)

        # Top 5 Causas de Baja y Tipos de Contrato
        causas_baja_dict = {}
        for b in todas_bajas:
            causa = b.causa_baja.descripcion if b.causa_baja else 'Sin Causa'
            causas_baja_dict[causa] = causas_baja_dict.get(causa, 0) + 1
        causas_baja_ordenada = sorted(causas_baja_dict.items(), key=lambda x: x[1], reverse=True)[:5]

        tipos_ordenados = sorted(tipos_contrato_counts.items(), key=lambda x: x[1], reverse=True)

        total_g = hombres + mujeres

        context['generos'] = {
            'hombres': hombres, 'mujeres': mujeres,
            'porc_hombres': round((hombres/total_g)*100, 1) if total_g else 0,
            'porc_mujeres': round((mujeres/total_g)*100, 1) if total_g else 0
        }

        context['salario_prom'] = round(total_salario_empresa / activos.count(), 2) if activos.count() > 0 else 0

        # Listas
        context['cumpleannos'] = cumpleaneros[:5]
        context['avisos_contratos'] = avisos_contratos[:5]
        context['pre_jubilacion'] = pre_jubilacion
        context['recontratados'] = recontratados
        context['jubilados_recontratados'] = jubilados_recontratados
        context['cat_ocupacional'] = list(cat_ocupacional.values()) 
        context['edades_m'] = edades_m
        context['edades_f'] = edades_f
        
        # ========== DATOS PARA GRÁFICOS (CORREGIDO: sin json.dumps en listas) ==========
        # Etiquetas (sí van con json.dumps para que queden como strings en JS)
        context['nivel_educ_labels'] = json.dumps(list(nivel_educ_counts.keys()))
        context['nivel_educ_data'] = list(nivel_educ_counts.values())   # Lista normal
        
        context['nivel_prep_labels'] = json.dumps(list(nivel_prep_counts.keys()))
        context['nivel_prep_data'] = list(nivel_prep_counts.values())   # Lista normal

        context['tipos_contrato_labels'] = json.dumps([item[0] for item in tipos_ordenados])
        context['tipos_contrato_data'] = [item[1] for item in tipos_ordenados]  # Lista normal

        context['raza_labels'] = json.dumps(list(raza_counts.keys()))
        context['raza_data'] = json.dumps(list(raza_counts.values()))

        context['reg_militar_labels'] = json.dumps(list(reg_militar_counts.keys()))
        context['reg_militar_data'] = list(reg_militar_counts.values())

        context['causas_baja_labels'] = json.dumps([item[0] for item in causas_baja_ordenada])
        context['causas_baja_data'] = [item[1] for item in causas_baja_ordenada]

        # --- 4. GRÁFICO HISTÓRICO ---
        # Un solo recorrido de `todos_altas` y `todas_bajas` (ya materializados en
        # memoria por el bucle maestro / el conteo de causas de baja de arriba),
        # agrupando por (año, mes) en un diccionario. Antes se recorrían las dos
        # listas completas una vez POR CADA uno de los 6 meses (O(6·N)); el bucle
        # de abajo ahora solo hace lookups O(1) en los diccionarios ya agrupados.
        altas_por_mes = {}
        for c in todos_altas:
            if c.fecha_alta:
                clave = (c.fecha_alta.year, c.fecha_alta.month)
                altas_por_mes[clave] = altas_por_mes.get(clave, 0) + 1
        for b in todas_bajas:
            if b.fecha_alta:
                clave = (b.fecha_alta.year, b.fecha_alta.month)
                altas_por_mes[clave] = altas_por_mes.get(clave, 0) + 1

        bajas_por_mes = {}
        for b in todas_bajas:
            if b.fecha_baja:
                clave = (b.fecha_baja.year, b.fecha_baja.month)
                bajas_por_mes[clave] = bajas_por_mes.get(clave, 0) + 1

        datos_meses = []; datos_altas = []; datos_bajas = []
        for i in range(5, -1, -1):
            mes_target = hoy.month - i
            anno_target = hoy.year
            if mes_target <= 0: mes_target += 12; anno_target -= 1
            datos_meses.append(meses[mes_target - 1])

            # Altas: CAlta.fecha_alta (activos actuales) + CBaja.fecha_alta (quienes ya
            # se fueron). Necesario porque CAlta se borra al causar baja (histórico
            # inmutable, ver contratos/models.py) — sin CBaja.fecha_alta se subestiman
            # las altas de meses donde alguien fue contratado y ya no está activo hoy.
            # No hay doble conteo: cada contrato vive en una sola de las dos tablas.
            datos_altas.append(altas_por_mes.get((anno_target, mes_target), 0))

            # Bajas busca en CBaja
            datos_bajas.append(bajas_por_mes.get((anno_target, mes_target), 0))

        context['graficos'] = {
            'meses': json.dumps(datos_meses),   # Etiquetas van con JSON
            'altas': datos_altas,               # Lista normal
            'bajas': datos_bajas,               # Lista normal
            'altas_total': datos_altas[-1] if datos_altas else 0,
            'bajas_total': datos_bajas[-1] if datos_bajas else 0
        }

        return context

    def get_plazas(self, uo_ids=None, depto_ids=None):
        cargos = CargoPlantilla.objects.filter(activo=True)
        if depto_ids:
            cargos = cargos.filter(departamento_id__in=depto_ids)
        elif uo_ids:
            cargos = cargos.filter(departamento__unidad_organizativa_id__in=uo_ids)
        t_cubiertas = sum(c.cant_cubierta or 0 for c in cargos)
        t_aprobadas = sum(c.cant_aprobada or 0 for c in cargos)
        t_vacantes = max(t_aprobadas - t_cubiertas, 0)
        # "totales" es la plantilla APROBADA (el template la muestra como "Aprob"),
        # no cubiertas+vacantes: con sobrecupo (cant_cubierta > cant_aprobada) esa
        # suma se colaba silenciosamente igual a cubiertas, inflando el badge
        # "Aprob" y forzando porc_cubiertas a un 100% falso que escondía el
        # sobrecupo. Con totales=aprobadas, porc_cubiertas puede superar el 100%
        # cuando hay sobrecupo, que es la cifra matemáticamente correcta.
        totales = t_aprobadas

        return {
            'totales': totales, 'cubiertas': t_cubiertas, 'vacantes': t_vacantes,
            'porc_cubiertas': round((t_cubiertas / totales) * 100, 2) if totales else 0,
            'porc_vacantes': round((t_vacantes / totales) * 100, 2) if totales else 0
        }