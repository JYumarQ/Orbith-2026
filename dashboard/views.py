from contratos.models import CAlta, CBaja
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
#from .models import Objeto
from django.urls import reverse_lazy
from strorganizativa.models import CargoPlantilla
import os
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q, F, Value, CharField, IntegerField
from django.db.models.functions import Concat
from django.http import HttpResponse, JsonResponse
from docxtpl import DocxTemplate
import calendar
from datetime import date, timedelta
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.views.generic import TemplateView
from datetime import datetime
import json

from .filtros import _filtrar_por_uo, resolver_filtros
from informe_inteligente.motor import EdadExacta
from notificaciones.filtros import filtrar_advertencias, filtrar_recordatorios
from notificaciones.models import Notificacion
from subsanacion.constantes import CRITICIDADES

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


def _rango_semana(offset_semanas=0):
    """(lunes, domingo) de la semana actual desplazada `offset_semanas`.

    Mismo criterio que usa Informe Inteligente para su operador "semana"
    (`informe_inteligente/motor.py::_construir_q_de_filtro`, lunes=weekday() 0),
    pero replicado en vez de importado: allá vive mezclado con la construcción
    de un `Q` de 7 combinaciones mes/día para filtrar por recurrencia anual
    (un caso de uso distinto); aquí solo hace falta el rango de fechas en sí.
    """
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday()) + timedelta(weeks=offset_semanas)
    domingo = lunes + timedelta(days=6)
    return lunes, domingo


def advertencias_json(request):
    """Recalcula solo la tarjeta Advertencias (mismo alcance de UO y misma
    reutilización de `filtrar_advertencias` que `DashboardView`) para que el
    selector de severidad se pueda aplicar por fetch, sin recargar el resto
    del Dashboard.
    """
    uo_ids, _ = resolver_filtros(request)
    advertencias, ctx_advertencias = filtrar_advertencias(request, request.user)
    if uo_ids:
        advertencias = [a for a in advertencias if a.unidad_id in uo_ids]

    return JsonResponse({
        'advertencias': [
            {'titulo': a.titulo, 'severidad_display': a.get_severidad_display()}
            for a in advertencias[:8]
        ],
        'total': len(advertencias),
        'severidad': ctx_advertencias['severidades_actuales'],
    })


def piramide_edades_json(request):
    """Recalcula solo la Pirámide de Edades (respetando el mismo alcance de UO
    y cortes que `DashboardView`) para que la tarjeta se pueda refrescar por
    fetch, sin recargar el resto del Dashboard.
    """
    uo_ids, _ = resolver_filtros(request)
    cortes = _cortes_edad_desde_request(request)

    activos = CAlta.objects.filter(aspirante__estado='ACTIVO').select_related('aspirante')
    activos = _filtrar_por_uo(activos, 'cargo__departamento', uo_ids)

    n_buckets = len(cortes) + 1
    edades_m = [0] * n_buckets
    edades_f = [0] * n_buckets
    for c in activos:
        edad = c.aspirante.get_edad
        if edad is None:
            continue
        idx = _bucket_edad(edad, cortes)
        if c.aspirante.sexo == 'M':
            edades_m[idx] += 1
        elif c.aspirante.sexo == 'F':
            edades_f[idx] += 1

    return JsonResponse({
        'edades_m': edades_m,
        'edades_f': edades_f,
        'categorias': _categorias_edad(cortes),
        'cortes': ','.join(str(c) for c in cortes),
    })


def antiguedad_html(request):
    """Tarjeta 'Antigüedad': lista de contratos ACTIVOS ordenada por más
    antiguo primero (fecha_alta_entidad ascendente), con el mismo alcance de
    UO/rol que el resto del Dashboard (ver dashboard/filtros.py) y un
    buscador único que filtra a la vez por nombre+apellidos, CI y No.
    Expediente (mismo criterio que `contratos/views.py::search_contratos`).

    Las bajas no tienen antigüedad (si el trabajador es recontratado, su
    antigüedad vuelve a contar desde cero en el nuevo contrato — ver
    fecha_alta_entidad en contratos/models.py), así que esta tarjeta solo
    considera contratos de aspirantes en estado ACTIVO.
    """
    uo_ids, _ = resolver_filtros(request)
    query = (request.GET.get('q') or '').strip()
    page_num = request.GET.get('page', 1)

    qs = CAlta.objects.filter(aspirante__estado='ACTIVO').select_related(
        'aspirante', 'cargo', 'cargo__departamento'
    )
    qs = _filtrar_por_uo(qs, 'cargo__departamento', uo_ids)

    qs = qs.annotate(
        antiguedad=EdadExacta(F('fecha_alta_entidad'), output_field=IntegerField()),
        nombre_completo=Concat(
            'aspirante__nombre', Value(' '),
            'aspirante__papellido', Value(' '),
            'aspirante__sapellido',
            output_field=CharField(),
        ),
    )

    if query:
        qs = qs.filter(
            Q(no_expediente__icontains=query) |
            Q(nombre_completo__icontains=query) |
            Q(aspirante__doc_identidad__icontains=query)
        )

    qs = qs.order_by(F('fecha_alta_entidad').asc(nulls_last=True))

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(page_num)

    return render(request, 'pages/dashboard/partials/antiguedad_tabla.html', {
        'page_obj': page_obj,
        'paginator': paginator,
        'query': query,
    })


# Create your views here.
class DashboardView(TemplateView):
    template_name = "pages/dashboard.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        
        # ========== DEFINIR MESES AQUÍ (antes de cualquier uso) ==========
        meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

        # ========== FILTRO GLOBAL (Unidad Organizativa) ==========
        # `resolver_filtros` ya valida los ids pedidos contra el alcance real
        # del usuario (ver dashboard/filtros.py) — nunca se confía en lo que
        # llegue crudo por querystring. Ya no existe selección manual de
        # Departamento: seleccionar una UO selecciona automáticamente todos
        # sus Departamentos (`uo_count`/`depto_count` ya vienen resueltos en
        # el contexto de filtro).
        uo_ids, filtro_ctx = resolver_filtros(self.request)
        context.update(filtro_ctx)

        def _filtrar(qs, campo_departamento):
            return _filtrar_por_uo(qs, campo_departamento, uo_ids)

        # 1. Consultas Base (Optimizadas)
        activos = CAlta.objects.filter(aspirante__estado='ACTIVO').select_related(
            'aspirante', 'aspirante__especialidad', 'aspirante__municipio',
            'tipo', 'cargo__ncargo', 'cargo__departamento'
        )
        activos = _filtrar(activos, 'cargo__departamento')

        todos_altas = CAlta.objects.all().select_related('aspirante', 'tipo')
        todos_altas = _filtrar(todos_altas, 'cargo__departamento')

        todas_bajas = CBaja.objects.all().select_related('causa_baja')
        todas_bajas = _filtrar(todas_bajas, 'cargo__departamento')

        # Variables directas para las tarjetas
        context['contratos_count'] = activos.count()
        context['plazas'] = self.get_plazas(uo_ids)

        # Nuevas Altas / Nuevas Bajas (ventana móvil de 30 días, distinta del
        # histórico mensual de más abajo). Las altas se combinan con CBaja.fecha_alta
        # porque CAlta se borra al causar baja (histórico inmutable): sin esto, quien
        # fue contratado y ya se fue dentro de la ventana desaparecería del conteo.
        hace_30 = hoy - timedelta(days=30)
        context['altas_30d'] = (
            _filtrar(CAlta.objects.filter(fecha_alta__range=(hace_30, hoy)), 'cargo__departamento').count()
            + _filtrar(CBaja.objects.filter(fecha_alta__range=(hace_30, hoy)), 'cargo__departamento').count()
        )
        context['bajas_30d'] = _filtrar(
            CBaja.objects.filter(fecha_baja__range=(hace_30, hoy)), 'cargo__departamento'
        ).count()

        # 2. Diccionarios y contadores inicializados en 0 (Evita que el JS falle si no hay datos)
        cumpleaneros = []
        pre_jubilacion = []
        recontratados = []
        jubilados_recontratados = []

        cat_ocupacional = {'OPE': 0, 'TEC': 0, 'ADM': 0, 'SER': 0, 'CUA': 0}
        nivel_educ_counts = {}
        nivel_educ_codigos = {}
        tipos_contrato_counts = {}
        raza_counts = {}
        raza_codigos = {}
        especialidad_counts = {}   # {(id, nombre): cantidad}
        municipio_counts = {}      # {(id, nombre): cantidad}
        grado_cientifico_counts = {'MC': 0, 'DC': 0, 'NINGUNO': 0}

        # Cumpleaños por semana (lunes-domingo, mismo criterio que Informe
        # Inteligente — ver `_rango_semana`). Se comparan por (mes, día) para
        # ignorar el año, igual que la recurrencia anual de un cumpleaños.
        lunes_actual, domingo_actual = _rango_semana(0)
        lunes_prox, domingo_prox = _rango_semana(1)

        def _dias_de_semana(lunes):
            """`{(mes, día): índice_de_orden}` de los 7 días de la semana que
            empieza en `lunes`, para poder ordenar cronológicamente dentro de
            la semana además de comparar por (mes, día)."""
            return {
                ((lunes + timedelta(days=i)).month, (lunes + timedelta(days=i)).day): i
                for i in range(7)
            }

        dias_semana_actual = _dias_de_semana(lunes_actual)
        dias_semana_prox = _dias_de_semana(lunes_prox)
        cumpleanos_semana_actual = []
        cumpleanos_semana_prox = []

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

            # Nivel Educacional (con código crudo paralelo, para el filtro de
            # Contratos al hacer clic en la leyenda — ver sección 6/7 del plan)
            if asp.nivel_educ:
                educ = asp.get_nivel_educ_display()
                nivel_educ_codigos[educ] = asp.nivel_educ
            else:
                educ = 'Sin Acreditar'
            nivel_educ_counts[educ] = nivel_educ_counts.get(educ, 0) + 1

            # Especialidad (aspirante, no cargo) — Top 5 + Otros, ver empaquetado
            esp_id = asp.especialidad_id
            esp_nombre = asp.especialidad.nombre if asp.especialidad else 'Sin Definir'
            clave_esp = (esp_id, esp_nombre)
            especialidad_counts[clave_esp] = especialidad_counts.get(clave_esp, 0) + 1

            # Municipio (Aspirante.municipio es obligatorio, sin bucket "Sin Definir")
            clave_mun = (asp.municipio_id, asp.municipio.nombre)
            municipio_counts[clave_mun] = municipio_counts.get(clave_mun, 0) + 1

            # Grado Científico: 3 categorías fijas (Master/Doctor/Ninguno)
            if asp.grado_cientifico == 'MC':
                grado_cientifico_counts['MC'] += 1
            elif asp.grado_cientifico == 'DC':
                grado_cientifico_counts['DC'] += 1
            else:
                grado_cientifico_counts['NINGUNO'] += 1

            # Salario Escala Promedio
            salario = c.salario_total or 0
            total_salario_empresa += float(salario)

            # Cálculos de CI (Cumpleaños "Cercanos" — lógica intocada) y Edades
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

            # Cumpleaños por semana (Semana actual / Próxima semana): usa
            # `fecha_nacimiento` (ya calculado desde el CI al guardar el
            # aspirante) en vez de reparsear el CI, comparando solo (mes, día)
            # para ignorar el año — misma idea que Informe Inteligente.
            if asp.fecha_nacimiento:
                clave_dia = (asp.fecha_nacimiento.month, asp.fecha_nacimiento.day)
                dato_cumple = {'nombre': f"{asp.nombre} {asp.papellido}",
                                'fecha_str': f"{asp.fecha_nacimiento.day} {meses[asp.fecha_nacimiento.month - 1]}",
                                'sexo': sexo}
                if clave_dia in dias_semana_actual:
                    cumpleanos_semana_actual.append({**dato_cumple, 'orden': dias_semana_actual[clave_dia]})
                if clave_dia in dias_semana_prox:
                    cumpleanos_semana_prox.append({**dato_cumple, 'orden': dias_semana_prox[clave_dia]})

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

            # I) Distribución por Raza (con código crudo paralelo, ver Nivel Educacional arriba)
            if asp.raza:
                raza = asp.get_raza_display()
                raza_codigos[raza] = asp.raza
            else:
                raza = 'No Definida'
            raza_counts[raza] = raza_counts.get(raza, 0) + 1

        # --- 3. ORDENACIÓN Y EMPAQUETADO ---
        cumpleaneros.sort(key=lambda x: x['dias'])
        cumpleanos_semana_actual.sort(key=lambda x: x['orden'])
        cumpleanos_semana_prox.sort(key=lambda x: x['orden'])
        pre_jubilacion.sort(key=lambda x: x['edad'], reverse=True)
        recontratados.sort(key=lambda x: x['edad'], reverse=True)
        jubilados_recontratados.sort(key=lambda x: (x['edad'] is None, x['edad']), reverse=True)

        # Recordatorios: mismos datos que la pestaña Notificaciones → Recordatorios
        # (sub "Sistema", `filtrar_recordatorios`, que ya calcula prioridad/color y
        # deduplica destinatarios), acotados por la UO del Dashboard igual que
        # Advertencias. Antes esta tarjeta solo mostraba un conteo; ahora enseña los
        # 10 más urgentes (ya vienen ordenados por `fecha_objetivo` ascendente).
        from notificaciones.views import _color_prioridad
        recordatorios, _ctx_recordatorios = filtrar_recordatorios(
            self.request, self.request.user, origen=Notificacion.Origen.SISTEMA)
        if uo_ids:
            recordatorios = [r for r in recordatorios if r.unidad_id in uo_ids]
        for r in recordatorios:
            r.prioridad = _color_prioridad(r.fecha_objetivo)
        context['recordatorios_total'] = len(recordatorios)
        context['recordatorios'] = recordatorios[:10]

        # Advertencias: reutiliza tal cual `filtrar_advertencias` (alcance por
        # usuario/rol, filtro de severidad ya validado contra request.GET) y
        # se acota además por la UO del Dashboard.
        advertencias, ctx_advertencias = filtrar_advertencias(self.request, self.request.user)
        if uo_ids:
            advertencias = [a for a in advertencias if a.unidad_id in uo_ids]
        context['advertencias_total'] = len(advertencias)
        context['advertencias'] = advertencias[:8]
        context['severidades_disponibles'] = CRITICIDADES
        context['severidad_actual'] = ctx_advertencias['severidades_actuales']

        # Top 5 Causas de Baja y Tipos de Contrato
        causas_baja_dict = {}
        for b in todas_bajas:
            causa = b.causa_baja.descripcion if b.causa_baja else 'Sin Causa'
            causas_baja_dict[causa] = causas_baja_dict.get(causa, 0) + 1
        causas_baja_ordenada = sorted(causas_baja_dict.items(), key=lambda x: x[1], reverse=True)[:5]

        tipos_ordenados = sorted(tipos_contrato_counts.items(), key=lambda x: x[1], reverse=True)

        def _top5_mas_otros(counts_por_clave):
            """`counts_por_clave`: `{(id, nombre): cantidad}`. Devuelve
            `(labels, data, ids)` con las 5 categorías más numerosas y el
            resto agrupado en 'Otros' (id `None`, no navegable desde la
            leyenda)."""
            ordenado = sorted(counts_por_clave.items(), key=lambda kv: kv[1], reverse=True)
            top5, resto = ordenado[:5], ordenado[5:]
            labels = [nombre for (_id, nombre), _cant in top5]
            data = [cant for _clave, cant in top5]
            ids = [_id for (_id, _nombre), _cant in top5]
            if resto:
                labels.append('Otros')
                data.append(sum(cant for _clave, cant in resto))
                ids.append(None)
            return labels, data, ids

        total_g = hombres + mujeres

        context['generos'] = {
            'hombres': hombres, 'mujeres': mujeres,
            'porc_hombres': round((hombres/total_g)*100, 1) if total_g else 0,
            'porc_mujeres': round((mujeres/total_g)*100, 1) if total_g else 0
        }

        context['salario_prom'] = round(total_salario_empresa / activos.count(), 2) if activos.count() > 0 else 0

        # Listas
        context['cumpleannos'] = cumpleaneros[:5]
        context['cumpleanos_semana_actual'] = cumpleanos_semana_actual
        context['cumpleanos_semana_prox'] = cumpleanos_semana_prox
        context['pre_jubilacion'] = pre_jubilacion
        context['recontratados'] = recontratados
        context['jubilados_recontratados'] = jubilados_recontratados
        context['cat_ocupacional'] = list(cat_ocupacional.values())
        context['cat_ocupacional_codigos'] = json.dumps(list(cat_ocupacional.keys()))
        context['edades_m'] = edades_m
        context['edades_f'] = edades_f

        # ========== DATOS PARA GRÁFICOS (CORREGIDO: sin json.dumps en listas) ==========
        # Etiquetas (sí van con json.dumps para que queden como strings en JS)
        context['nivel_educ_labels'] = json.dumps(list(nivel_educ_counts.keys()))
        context['nivel_educ_data'] = list(nivel_educ_counts.values())   # Lista normal
        context['nivel_educ_codigos'] = json.dumps([nivel_educ_codigos.get(k, '') for k in nivel_educ_counts.keys()])

        context['tipos_contrato_labels'] = json.dumps([item[0] for item in tipos_ordenados])
        context['tipos_contrato_data'] = [item[1] for item in tipos_ordenados]  # Lista normal

        context['raza_labels'] = json.dumps(list(raza_counts.keys()))
        context['raza_data'] = json.dumps(list(raza_counts.values()))
        context['raza_codigos'] = json.dumps([raza_codigos.get(k, '') for k in raza_counts.keys()])

        # Especialidad / Municipio: Top 5 + Otros
        esp_labels, esp_data, esp_ids = _top5_mas_otros(especialidad_counts)
        context['especialidad_labels'] = json.dumps(esp_labels)
        context['especialidad_data'] = esp_data
        context['especialidad_codigos'] = json.dumps(esp_ids)

        mun_labels, mun_data, mun_ids = _top5_mas_otros(municipio_counts)
        context['municipio_labels'] = json.dumps(mun_labels)
        context['municipio_data'] = mun_data
        context['municipio_codigos'] = json.dumps(mun_ids)

        # Grado Científico: 3 categorías fijas, sin Top-N
        context['grado_cientifico_labels'] = json.dumps(['Master', 'Doctor', 'Ninguno'])
        context['grado_cientifico_data'] = [
            grado_cientifico_counts['MC'], grado_cientifico_counts['DC'], grado_cientifico_counts['NINGUNO']
        ]
        context['grado_cientifico_codigos'] = json.dumps(['MC', 'DC', 'NINGUNO'])

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

    def get_plazas(self, uo_ids=None):
        # `en_plantilla=True`: las plazas fuera de la plantilla aprobada existen
        # y tienen gente, pero no son plantilla y no deben inflar las tarjetas.
        cargos = CargoPlantilla.objects.filter(activo=True, en_plantilla=True)
        if uo_ids:
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