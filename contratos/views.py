from typing import override, Any
from django.http import response, HttpResponseRedirect, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.generic import ListView, CreateView, DeleteView, UpdateView, View, FormView
from django.conf import settings
from core.mixins import AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin
from bolsa.models import Aspirante
from .models import CAlta, CBaja, TMovimiento, salario_de_escala_para
from .tarifas import calcular_tarifas, parametros_de_tarifa, salario_de_combinacion
from .forms import CAltaForm
from strorganizativa.jerarquia import ordenar_con_jerarquia
from strorganizativa.models import Departamento, CargoPlantilla, UnidadOrganizativa
from usuarios.alcance import tiene_alcance_acotado
from nomencladores.models import NSalario, NCausaAltaBaja, NRol, NProvincia, NTipoContrato, NCargo
from django.urls import reverse_lazy, reverse
from configuracion.models import Configuracion
from django.template.loader import get_template
from django.db.models import Q, ProtectedError, Value
from django.db.models.functions import Concat
from django.db import transaction
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from .forms import CAltaForm, MovimientoForm
from .cronologia import (bloquear_historico, ultimo_evento, validar_fecha_evento,
                         validar_fecha_no_futura)
from docxtpl import DocxTemplate, RichText
from io import BytesIO
import os
import logging
import traceback
import sys
import json
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from django.http import HttpResponse, Http404
from datetime import datetime
from .forms import ExportarContratoWordForm
from usuarios.mixins import RequiereEdicionMixin, requiere_edicion
from auditoria.models import AccionAuditoria
from auditoria import registro_automatico
from core.busqueda import interpretar, normalizar, sin_acentos, solo_digitos_sin_ceros
from core.nombres_descarga import documento_de_trabajador, nombre_de_informe, nombre_de_persona
from .filtros import (anotar_movimientos_del_periodo, aplicar_filtros, altas_que_causaron_baja,
                      anotar_recontratado, contratos_visibles, marcar_recontratados, personas_de)
from .annos_servicio import annos_y_pago
# Convierte el guardado en una solicitud cuando quien envía el formulario es un Moderador;
# devuelve None para el Administrador, que sigue guardando directamente.
from solicitudes.integracion import interceptar
from solicitudes.models import AccionSolicitud



logger = logging.getLogger(__name__)

CAT_MAP = {
    'TEC': 'T',
    'ADM': 'A',
    'SER': 'S',
    'OPE': 'O',
    'CDI': 'C',
    'CEJ': 'C',
}
#?ONTRATO
def _cascadas_de_filtro(request):
    """Municipio y especialidad dependen de otro desplegable (provincia y nivel
    educacional) y se cargaban vacíos y DESACTIVADOS aunque la lista llegara con
    ellos en la URL (p. ej. desde el «Ver más» de la Dashboard): la primera carga
    salía filtrada, pero al buscar o cambiar de página el filtro se perdía
    (24-10-2026). Aquí se preparan sus opciones para que salgan marcados."""
    from nomencladores.models import NEspecialidad, NMunicipio

    provincia = (request.GET.get('provincia') or '').strip()
    municipio = (request.GET.get('municipio') or '').strip()
    if not provincia.isdigit() and municipio.isdigit():
        provincia = str(NMunicipio.objects.filter(pk=municipio).values_list('provincia_id', flat=True).first() or '')
    nivel = request.GET.get('nivel_educ') or ''
    especialidad = (request.GET.get('especialidad') or '').strip()
    if nivel == 'NS':
        especialidades = NEspecialidad.objects.filter(educ_superior=True)
    elif nivel == 'TM':
        especialidades = NEspecialidad.objects.filter(educ_superior=False)
    elif especialidad.isdigit():
        especialidades = NEspecialidad.objects.filter(pk=especialidad)
    else:
        especialidades = NEspecialidad.objects.none()
    return {
        'filtro_provincia': provincia if provincia.isdigit() else '',
        'municipios_filtro': (NMunicipio.objects.filter(provincia_id=provincia).order_by('nombre')
                              if provincia.isdigit() else []),
        'especialidades_filtro': especialidades.order_by('nombre'),
    }


class ContratoListView(ListView):
    model = CAlta
    template_name = "pages/contrato/list_contrato.html"

    def get_queryset(self):
        """Precarga las relaciones que recorre la plantilla de filas.

        `partials/filter_contratos_list.html` baja por `c.aspirante`,
        `c.cargo.departamento.unidad_organizativa`, `c.cargo.ncargo.grupo_escala`,
        `c.cargo.rol` y `c.tridente`. Sin esto Django resolvía cada salto
        con una consulta suelta por fila: la vista disparaba 95 consultas (36 de
        ellas repetidas) con apenas 51 empleados.

        `aplicar_filtros()` aplica los mismos filtros de `?raza=`/`?nivel_educ=`/
        etc. que ya usa `search_contratos` — sin esto, un enlace externo (p.ej.
        desde el Dashboard) con un filtro en la URL no filtraba nada hasta que
        el usuario tocaba un `<select>`, porque la carga inicial no leía la
        querystring.
        """
        qs = super().get_queryset().filter(
            pk__in=contratos_visibles(self.request.user).values_list('pk', flat=True))
        # La fecha mínima de la Baja de cada fila y si es una recontratación, en la
        # misma consulta.
        qs = anotar_recontratado(CAlta.con_fecha_ultimo_movimiento(qs))
        qs = anotar_movimientos_del_periodo(self.request, qs)
        return aplicar_filtros(self.request, qs.select_related(
            'aspirante',
            'tipo',
            'motivo',
            'cargo__rol',
            'tridente',
            'cargo',
            'cargo__ncargo',
            'cargo__ncargo__grupo_escala',
            'cargo__rol',
            'cargo__departamento',
            'cargo__departamento__unidad_organizativa',
        ))

    def get_paginate_by(self, queryset):
        # Paginación común: las filas por página del usuario (core/paginacion.py).
        from core.paginacion import filas_por_pagina
        return filas_por_pagina(self.request)

    ordering = ['-fecha_alta']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Triángulos de problemas de cada fila de la página (Fase 2).
        from subsanacion.indicadores import marcar, problemas_por_contrato
        filas = list(context['object_list'])
        context['object_list'] = marcar(filas, problemas_por_contrato(filas), 'contrato')
        context['filtro_problemas'] = self.request.GET.get('problemas', '')
        context['form'] = CAltaForm()
        context['search_url'] = 'search_contrato'
        context['causas_baja'] = NCausaAltaBaja.objects.filter(alta=False)
        context['provincias_list'] = NProvincia.objects.all()
        context['niveles_educ'] = Aspirante._meta.get_field('nivel_educ').choices
        context['categorias_ocupacionales'] = NCargo._meta.get_field('cat_ocupacional').choices
        context['tipos_contrato_list'] = NTipoContrato.objects.all().order_by('descripcion')

        # Preselección visual de los filtros al llegar con una querystring ya
        # armada (p.ej. desde un gráfico del Dashboard) — la tabla ya viene
        # filtrada por `get_queryset()`, esto solo hace que el `<select>`
        # correspondiente se muestre marcado.
        context['filtro_provincia'] = self.request.GET.get('provincia', '')
        context['filtro_municipio'] = self.request.GET.get('municipio', '')
        context['filtro_nivel_educ'] = self.request.GET.get('nivel_educ', '')
        context['filtro_especialidad'] = self.request.GET.get('especialidad', '')
        context['filtro_sexo'] = self.request.GET.get('sexo', '')
        context['filtro_raza'] = self.request.GET.get('raza', '')
        context['filtro_grado_cientifico'] = self.request.GET.get('grado_cientifico', '')
        context['filtro_cat_ocupacional'] = self.request.GET.get('cat_ocupacional', '')
        context['filtro_tipo'] = self.request.GET.get('tipo', '')
        context['filtro_alta_desde'] = self.request.GET.get('alta_desde', '')
        context['filtro_alta_hasta'] = self.request.GET.get('alta_hasta', '')
        context['filtro_recontratado'] = self.request.GET.get('recontratado', '')
        context['filtro_baja_anterior_desde'] = self.request.GET.get('baja_anterior_desde', '')
        context['filtro_baja_anterior_hasta'] = self.request.GET.get('baja_anterior_hasta', '')
        context['filtro_jubilado'] = self.request.GET.get('jubilado', '')
        context.update(_cascadas_de_filtro(self.request))
        context['altas_con_baja_total'] = _total_altas_con_baja(self.request)
        context['marcar_recontratados'] = marcar_recontratados(self.request)

        # --- Filtros de estructura: unidad, departamento y cargo ---
        #
        # Los tres usan el selector de fichas compartido, así que admiten varios
        # valores y se marcan comparando textos (`pk|stringformat:"s" in ...`).
        #
        # Solo se ofrece lo que el usuario puede ver: `contratos_visibles()` ya
        # acota el listado por rol, y ofrecer en el desplegable una unidad fuera
        # de su alcance sería un filtro que siempre devuelve vacío.
        usuario_actual = self.request.user
        if tiene_alcance_acotado(usuario_actual):
            unidades_permitidas = UnidadOrganizativa.objects.filter(
                pk__in=usuario_actual.unidades.values_list('pk', flat=True))
        else:
            unidades_permitidas = UnidadOrganizativa.objects.all()

        context['unidades_filtro'] = ordenar_con_jerarquia(
            unidades_permitidas.select_related('padre'))
        departamentos = list(
            Departamento.objects
            .filter(unidad_organizativa__in=unidades_permitidas)
            .select_related('unidad_organizativa')
            .order_by('unidad_organizativa__orden_informe', 'descripcion'))
        # El selector busca también por el nombre del padre: escribir «Oficina
        # Central» deja visibles sus departamentos. Departamento no tiene campo
        # `padre` —su superior es `unidad_organizativa`—, así que se le pone al
        # vuelo, solo para pintar. No se guarda nada.
        for departamento in departamentos:
            departamento.padre = departamento.unidad_organizativa
        context['departamentos_filtro'] = departamentos
        # Por NOMENCLADOR de cargo: «Especialista B» existe una vez por
        # departamento, y quien filtra por un cargo quiere verlos todos.
        context['cargos_filtro'] = (
            NCargo.objects
            .filter(cargoplantilla__departamento__unidad_organizativa__in=unidades_permitidas)
            .distinct()
            .order_by('descripcion'))

        context['filtro_unidad'] = self.request.GET.getlist('unidad')
        context['filtro_departamento'] = self.request.GET.getlist('departamento')
        context['filtro_cargo'] = self.request.GET.getlist('cargo')

        return context
    

class MovimientoNominaListView(ListView):
    model = CAlta
    # Usaremos la nueva ruta de plantilla que acordamos
    template_name = "pages/movimientos/list_movimientos.html"
    ordering = ['-fecha_alta']
    # Pie común de las tablas con enlaces (base/partials/tabla_paginacion_enlaces.html),
    # que usa `?pagina=N`.
    page_kwarg = 'pagina'

    def get_paginate_by(self, queryset):
        # Filas por página del usuario, comunes a todas las tablas (core/paginacion.py).
        from core.paginacion import filas_por_pagina
        return filas_por_pagina(self.request)

    def get_queryset(self):
        # FILTRO CLAVE: Solo mostramos los marcados como "En Proceso"
        return CAlta.objects.filter(en_proceso_movimiento=True).order_by('-fecha_alta')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pasamos search_url por si quieres implementar búsqueda aquí también en el futuro
        # (Por ahora reutilizaremos lógica básica o lo dejaremos simple)
        context['titulo'] = "Movimientos de Nómina Pendientes"
        return context


# --- Función de apoyo para entender los Grupos Escala ---
def nivel_romano_a_int(romano):
    mapa = {'I': 1, 'V': 5, 'X': 10, 'L': 50}
    res, prev = 0, 0
    for c in reversed(romano.upper()):
        val = mapa.get(c, 0)
        if val < prev: res -= val
        else: res += val
        prev = val
    return res


def cargar_roles(request):
    cargo_id = request.GET.get('cargo')
    roles_disponibles = []
    
    if cargo_id:
        try:
            cargo = CargoPlantilla.objects.select_related('ncargo').get(pk=cargo_id)
            grupo = cargo.ncargo.grupo_escala
            categoria = cargo.ncargo.cat_ocupacional
            nivel_num = nivel_romano_a_int(grupo.nivel) # Leemos el número del grupo
            
            # 1. LA LIMPIEZA (Tu código original): Buscar en NSalario qué roles tienen dinero (> 0)
            salarios_con_fondo = NSalario.objects.filter(
                grupo_escala=grupo, 
                monto__gt=0
            ).values_list('rol_id', flat=True).distinct()
            
            # Convertimos a Set para manipular fácil
            ids_validos = set(salarios_con_fondo)
            
            # Buscamos los IDs de los roles clave
            rol_cuadro_obj = NRol.objects.filter(tipo__iexact="Cuadro").first()
            rol_decisorio_obj = NRol.objects.filter(tipo__iexact="Decisorio").first()
            
            id_cuadro = rol_cuadro_obj.id if rol_cuadro_obj else None
            id_decisorio = rol_decisorio_obj.id if rol_decisorio_obj else None
            
            # 2. LA CATEGORÍA (Tu código original)
            if id_cuadro:
                # Si ES directivo, nos aseguramos que vea la opción "Cuadro"
                if categoria in ['CDI', 'CEJ']:
                    ids_validos.add(id_cuadro)
                else:
                    if id_cuadro in ids_validos:
                        ids_validos.remove(id_cuadro)

            # 3. EL PORTERO INTELIGENTE: Reglas estrictas de los Grupos Escala
            
            # Regla Grupos I al XIX: PROHIBIDO Cuadro (Incluso si es CDI/CEJ lo quitamos)
            if nivel_num <= 19:
                if id_cuadro and id_cuadro in ids_validos:
                    ids_validos.remove(id_cuadro)
                    
            # Regla Grupos XX y XXI: Permite todos (No quitamos nada)
            elif 20 <= nivel_num <= 21:
                pass
                
            # Regla Grupos XXII al XXIV: SOLO Cuadro o Decisorio (Destruimos Apoyo y Fundamental)
            elif 22 <= nivel_num <= 24:
                permitidos = set()
                if id_cuadro and id_cuadro in ids_validos: 
                    permitidos.add(id_cuadro)
                if id_decisorio and id_decisorio in ids_validos: 
                    permitidos.add(id_decisorio)
                ids_validos = permitidos 
                
            # Regla Grupo XXV: SOLO Cuadro
            elif nivel_num == 25:
                permitidos = set()
                if id_cuadro and id_cuadro in ids_validos: 
                    permitidos.add(id_cuadro)
                ids_validos = permitidos

            # 4. Query Final
            if ids_validos:
                roles_disponibles = NRol.objects.filter(id__in=ids_validos).order_by('tipo')
            else:
                roles_disponibles = NRol.objects.none()

        except Exception as e:
            logger.exception("Error cargando roles para el cargo %s: %s", cargo_id, e)
            pass
            
    return render(request, 'pages/contrato/partials/options_roles.html', {'roles': roles_disponibles})

def obtener_datos_previos(request):
    """
    Busca datos previos en CAlta (Activos) O CBaja (Histórico de Bajas)
    para recuperar No. Expediente y Registro Militar.
    """
    aspirante_id = request.GET.get('aspirante_id')
    if not aspirante_id:
        return JsonResponse({'existe': False})

    # 1. Buscar primero en Bajas (lo más probable si se está recontratando)
    baja_reciente = CBaja.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_baja').first()
    
    if baja_reciente:
        return JsonResponse({
            'existe': True,
            'no_expediente': baja_reciente.no_expediente,
            'reg_militar': baja_reciente.reg_militar
        })

    # 2. Si no está en bajas, buscar en Activos (casos raros de pluriempleo o errores)
    alta_reciente = CAlta.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_alta').first()
    
    if alta_reciente:
        return JsonResponse({
            'existe': True,
            'no_expediente': alta_reciente.no_expediente,
            'reg_militar': alta_reciente.reg_militar
        })

    # 3. No se encontró nada
    return JsonResponse({'existe': False})

#: Prefijos del buscador de Contratos (ver `core/busqueda.py`). `COD:` es de
#: Subsanación: aquí no filtra y el buscador avisa (`busqueda_prefijos.js`).
PREFIJOS_CONTRATOS = ('E', 'N', 'CI', 'CA', 'U')


def _aplicar_busqueda_contratos(qs, texto):
    """Texto libre (expediente, nombre o carnet) y prefijos, sin distinguir acentos."""
    busqueda = interpretar(texto)
    qs = qs.alias(_nombre=sin_acentos(Concat(
        'aspirante__nombre', Value(' '), 'aspirante__papellido', Value(' '),
        'aspirante__sapellido')))

    for palabra in busqueda.libre.split():
        qs = qs.filter(
            Q(no_expediente__icontains=palabra)
            | Q(_nombre__contains=normalizar(palabra))
            | Q(aspirante__doc_identidad__icontains=palabra))

    for valor in busqueda.valores('E'):
        numero = solo_digitos_sin_ceros(valor)
        qs = (qs.filter(no_expediente__regex=r'^0*%s$' % numero) if numero is not None
              else qs.filter(no_expediente__iexact=valor.strip()))
    for valor in busqueda.valores('N'):
        for palabra in valor.split():
            qs = qs.filter(_nombre__contains=normalizar(palabra))
    for valor in busqueda.valores('CI'):
        qs = qs.filter(aspirante__doc_identidad__startswith=valor.replace(' ', ''))
    if busqueda.valores('CA'):
        qs = qs.alias(_cargo=sin_acentos('cargo__ncargo__descripcion'))
        for valor in busqueda.valores('CA'):
            qs = qs.filter(_cargo__contains=normalizar(valor))
    if busqueda.valores('U'):
        qs = qs.alias(_unidad=sin_acentos(
            'cargo__departamento__unidad_organizativa__descripcion'))
        for valor in busqueda.valores('U'):
            qs = qs.filter(_unidad__contains=normalizar(valor))
    return qs


def _total_altas_con_baja(request):
    """Cifra del aviso «Hay N contratados en este período que ya fueron dados de
    baja» (0 si no se filtra por fecha de alta: el aviso no sale)."""
    qs = altas_que_causaron_baja(request)
    return personas_de(qs) if qs is not None else 0


def altas_con_baja_html(request):
    """Ventana del aviso: quién entró en el período y ya causó baja (solo consulta)."""
    qs = altas_que_causaron_baja(request)
    todas = [] if qs is None else qs.select_related(
        'aspirante', 'causa_baja', 'cargo__ncargo',
        'cargo__departamento__unidad_organizativa').order_by('fecha_alta', 'fecha_baja')
    # Una fila por persona (la última), con cuántas veces entró en el período.
    por_persona = {}
    for baja in todas:
        if baja.aspirante_id in por_persona:
            por_persona[baja.aspirante_id].veces += 1
            baja.veces = por_persona[baja.aspirante_id].veces
        else:
            baja.veces = 1
        por_persona[baja.aspirante_id] = baja
    return render(request, 'pages/contrato/partials/altas_con_baja.html',
                  {'bajas': sorted(por_persona.values(), key=lambda b: (b.fecha_alta, b.fecha_baja))})


def _contratos_de_la_lista(request, *relaciones_extra):
    """Los contratos de la lista con sus filtros, su búsqueda y su orden, ya como
    lista. La usan la tabla (`search_contratos`) y la sábana de Excel
    (`exportar_contratos_excel`): así lo que se exporta es EXACTAMENTE lo que se
    ve, filtros y orden incluidos (decisión de RRHH del 24-10-2026)."""
    # 1. Obtener parámetros de filtros
    query = request.GET.get('filter_contrato', '').strip()

    # 2. QuerySet Base con el Grafo Relacional expandido (Corrección N+1),
    # acotado al alcance del usuario (ver contratos/filtros.py::contratos_visibles)
    qs = contratos_visibles(request.user).select_related(
        'aspirante',
        'cargo',
        'cargo__departamento',
        'cargo__ncargo',
        'cargo__ncargo__grupo_escala',
        'cargo__rol',
        'tridente',
        *relaciones_extra
    ).order_by('-fecha_alta')
    # La fecha mínima de la Baja de cada fila y si es una recontratación, en la
    # misma consulta.
    qs = anotar_movimientos_del_periodo(request, anotar_recontratado(CAlta.con_fecha_ultimo_movimiento(qs)))

    # 3. Aplicar Filtros "Embudo" (mismo criterio que la carga inicial de
    # ContratoListView — ver contratos/filtros.py::aplicar_filtros)
    qs = aplicar_filtros(request, qs)

    # 4. Buscador Inteligente (Concatenación)
    if query:
        qs = _aplicar_busqueda_contratos(qs, query)

    # 5. ORDENAMIENTO COMPLETO EN EL SERVIDOR (Todas las páginas)
    sort_col = request.GET.get('sort', '')
    order = request.GET.get('order', 'asc')
    
    # Convertimos el QuerySet a una Lista. Aquí se ejecuta la única consulta SQL.
    contratos_list = list(qs)
    
    if sort_col:
        reverse_sort = (order == 'desc')
        
        if sort_col == 'expediente':
            contratos_list.sort(key=lambda x: int(x.no_expediente) if x.no_expediente.isdigit() else 0, reverse=reverse_sort)
        elif sort_col == 'nombre':
            contratos_list.sort(key=lambda x: f"{x.aspirante.nombre} {x.aspirante.papellido} {x.aspirante.sapellido}".lower(), reverse=reverse_sort)
        elif sort_col == 'area':
            contratos_list.sort(key=lambda x: x.cargo.departamento.descripcion.lower() if x.cargo and x.cargo.departamento else "", reverse=reverse_sort)
        elif sort_col == 'cat':
            contratos_list.sort(key=lambda x: getattr(x.cargo.ncargo, 'get_cat_ocupacional_display')() if x.cargo and hasattr(x.cargo, 'ncargo') else "", reverse=reverse_sort)
        elif sort_col == 'grupo':
            def get_grupo_val(c):
                nivel = c.cargo.ncargo.grupo_escala.nivel if c.cargo and c.cargo.ncargo and hasattr(c.cargo.ncargo, 'grupo_escala') and c.cargo.ncargo.grupo_escala else ""
                return nivel_romano_a_int(nivel)
            contratos_list.sort(key=get_grupo_val, reverse=reverse_sort)
        elif sort_col == 'rol':
            jerarquia = {"APOYO": 1, "FUNDAMENTAL": 2, "DECISORIO": 3, "CUADRO": 4}
            def get_rol_val(c):
                r = c.cargo.rol if c.cargo else None
                rol_str = r.tipo.upper() if r else "CUADRO"
                return jerarquia.get(rol_str, 0)
            contratos_list.sort(key=get_rol_val, reverse=reverse_sort)
        elif sort_col == 'tridente':
            contratos_list.sort(key=lambda x: x.tridente.tipo if x.tridente else "", reverse=reverse_sort)
        elif sort_col == 'salario':
            # Usamos el salario ya cacheado en la fila (se recalcula en cada save del
            # contrato). Antes se llamaba a calcular_salario_escala() por cada registro,
            # lo que suponía una consulta a NSalario por fila del listado completo.
            contratos_list.sort(key=lambda x: x.salario_actual or 0, reverse=reverse_sort)

    return contratos_list


def search_contratos(request):
    contratos_list = _contratos_de_la_lista(request)

    # 6. Paginación SOBRE la lista ya ordenada (común: core/paginacion.py)
    from core.paginacion import paginar
    page_obj = paginar(request, contratos_list)

    # Triángulos de problemas de cada fila de la página (Fase 2).
    from subsanacion.indicadores import marcar, problemas_por_contrato
    filas = list(page_obj)
    filas = marcar(filas, problemas_por_contrato(filas), 'contrato')

    return render(request, 'pages/contrato/partials/filter_contratos_list.html', {
        'object_list': filas,
        'page_obj': page_obj,
        'paginator': page_obj.paginator,
        'search_url': 'search_contrato',
        'altas_con_baja_total': _total_altas_con_baja(request),
        'marcar_recontratados': marcar_recontratados(request),
    })




def validar_datos_contrato(request):
    expediente = request.GET.get('no_expediente', None)
    data = {
        'expediente_existe': False
    }
    if expediente:
        # Verifica si existe algún contrato con ese No. Expediente
        if CAlta.objects.filter(no_expediente=expediente).exists():
            data['expediente_existe'] = True
            
    return JsonResponse(data)

@requiere_edicion
def solicitar_movimiento_nomina(request, pk):
    """
    Alterna el estado de 'En Proceso de Movimiento' de un contrato.
    """
    if request.method == "POST":
        try:
            contrato = get_object_or_404(CAlta, pk=pk)
            
            # Leemos el parámetro enviado por JS
            es_cancelacion = request.POST.get('cancelar') == 'true'
            
            if es_cancelacion:
                contrato.en_proceso_movimiento = False
                mensaje = 'Movimiento cancelado. El contrato regresó a su estado normal.'
            else:
                contrato.en_proceso_movimiento = True
                mensaje = 'Contrato enviado a la bandeja de movimientos pendientes.'

            contrato.save()

            if not es_cancelacion:
                from progreso.servicios import completar_tarea
                completar_tarea(request.user, 'primer_movimiento_cedido')
                from ranking.models import Actividad
                from ranking.servicios import registrar_actividad
                registrar_actividad(request.user, Actividad.ENVIO_MOVIMIENTO, detalle=contrato)

            return JsonResponse({'success': True, 'message': mensaje})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    
    return JsonResponse({'success': False, 'message': 'Método no permitido.'}, status=405)

# orbith/contratos/views.py

def validar_plazas_cargo(request):
    cargo_id = request.GET.get('cargo_id', None)
    tipo_id = request.GET.get('tipo_id', None)
    data = {
        'plazas_agotadas': False,
        'mensaje': ''
    }
    
    if cargo_id:
        try:
            cargo = CargoPlantilla.objects.select_related('ncargo').get(pk=cargo_id)
            
            # 1. Evaluamos la regla de negocio del Tipo de Contrato
            if tipo_id:
                try:
                    tipo_contrato = NTipoContrato.objects.get(pk=tipo_id)
                    # Si el contrato NO ocupa plaza (Ej: Adiestrado, Determinado), damos luz verde directa
                    if not tipo_contrato.ocupa_plaza:
                        return JsonResponse(data)
                except NTipoContrato.DoesNotExist:
                    pass
        
            # Un cargo fuera de la plantilla aprobada no tiene plazas oficiales
            # que ofrecer: no es que estén agotadas, es que no existen.
            if not cargo.en_plantilla:
                data['plazas_agotadas'] = True
                data['mensaje'] = (
                    f"El Cargo '{cargo.ncargo.descripcion}' está fuera de la plantilla "
                    f"aprobada, por lo que no admite contratos que ocupen plaza."
                )
                return JsonResponse(data)

            if cargo.cant_cubierta_real >= cargo.cant_aprobada:
                data['plazas_agotadas'] = True
                data['mensaje'] = f"El Cargo '{cargo.ncargo.descripcion}' no tiene plazas oficiales disponibles ({cargo.cant_cubierta_real}/{cargo.cant_aprobada})"
                
        except CargoPlantilla.DoesNotExist:
            pass
            
    return JsonResponse(data)
            
    

def cargar_departamentos(request):
    unidad_id = request.GET.get('unidad')
    departamentos = Departamento.objects.none()
    
    if unidad_id:
        try:
            departamentos = Departamento.objects.filter(unidad_organizativa_id=unidad_id).order_by('descripcion')
        except (ValueError, TypeError):
            pass

    return render(request, 'pages/contrato/partials/options_generico.html', {'opciones': departamentos})

def cargar_cargos(request):
    dpto_id = request.GET.get('departamento')
    cargos = CargoPlantilla.objects.none()
    
    if dpto_id:
        try:
            # Filtramos cargos del departamento
            cargos = CargoPlantilla.objects.filter(departamento_id=dpto_id).select_related('ncargo').order_by('ncargo__descripcion')
        except (ValueError, TypeError):
            pass
            
    return render(request, 'pages/contrato/partials/options_cargos.html', {'cargos': cargos})



def historico_trabajador(request, aspirante_id):

    try:
        aspirante = Aspirante.objects.get(pk=aspirante_id)
        
        # 1. Buscamos primero en contratos activos
        contrato_data = CAlta.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_alta').first()
        
        # 2. Si no hay contrato activo (está de baja), buscamos en el historial de bajas para recuperar el expediente vitalicio
        if not contrato_data:
            contrato_data = CBaja.objects.filter(aspirante_id=aspirante_id).order_by('-fecha_alta').first()
            
        exp_num = contrato_data.no_expediente if contrato_data else "---"
        encabezado = {
            'nombre_completo': f"{aspirante.nombre} {aspirante.papellido} {aspirante.sapellido}",
            'ci': aspirante.doc_identidad,
            'id': aspirante.id, 
            'expediente': exp_num
        }
    except Aspirante.DoesNotExist:
        return JsonResponse({'data': [], 'encabezado': {'nombre_completo': 'Desconocido', 'ci': ''}})

    def fmt_dinero(valor):
        try: return f"{float(valor):.2f}"
        except: return "0.00"

    hitos = []

    # Traemos de una sola vez todos los movimientos implicados y los resolvemos en
    # memoria. Antes se lanzaba una consulta por cada hito (obtener_id_movimiento) y
    # otra más por cada contrato para localizar su primer movimiento.
    # El OR cubre los dos filtros que usaba el código original: unos buscaban por
    # aspirante y otros por contrato (que puede tener el aspirante a NULL).
    movs_todos = list(
        TMovimiento.objects
        .filter(Q(aspirante_id=aspirante_id) | Q(contrato__aspirante_id=aspirante_id))
        .order_by('fecha_efectiva')
    )
    movimientos_aspirante = [m for m in movs_todos if str(m.aspirante_id) == str(aspirante_id)]
    movs_por_pk = {m.pk: m for m in movs_todos}

    # Índice por (expediente, tipo, fecha). Antes se indexaba solo por
    # (expediente, tipo) y se quedaba con el MÁS RECIENTE de ese tipo — con
    # expedientes reutilizados en varias recontrataciones, todos los ciclos
    # antiguos de "Alta Inicial"/"Baja" de un mismo expediente terminaban
    # apuntando al mismo TMovimiento (el del ciclo más reciente), aunque fueran
    # eventos distintos en fechas distintas. Se añade la fecha a la clave para
    # que cada ciclo encuentre SU PROPIO movimiento, no el de otro ciclo.
    #
    # Se construye desde `movs_todos` (no `movimientos_aspirante`): los TMovimiento
    # de tipo 'Alta Inicial'/'Baja' a veces solo están enlazados vía `contrato`
    # (con `aspirante_id` a NULL en el propio TMovimiento), así que quedaban fuera
    # de `movimientos_aspirante` y su fila del histórico se guardaba con id=None
    # -> el botón "Exportar Movimiento" nunca se habilitaba para esas filas
    # aunque el movimiento sí existiera.
    indice_por_tipo_fecha = {}
    for m in movs_todos:
        indice_por_tipo_fecha[(m.no_expediente, m.tipo_movimiento, m.fecha_efectiva)] = m.pk

    def obtener_id_movimiento(expediente, tipo_busqueda, fecha):
        """Busca el TMovimiento de un ciclo concreto por su fecha exacta."""
        return indice_por_tipo_fecha.get((expediente, tipo_busqueda, fecha))

    def primer_movimiento_real(expediente=None, contrato=None):
        """Movimiento más antiguo del contrato/expediente, ignorando el alta automática.

        movs_todos ya viene ordenado por fecha_efectiva ascendente, así que el primero
        que cumpla el filtro es el equivalente al .order_by('fecha_efectiva').first().
        """
        origen = movs_todos if contrato is not None else movimientos_aspirante
        for m in origen:
            if m.tipo_movimiento == 'Alta Inicial':
                continue
            if contrato is not None and m.contrato_id != contrato.pk:
                continue
            if expediente is not None and m.no_expediente != expediente:
                continue
            return m
        return None

    # --- FUENTE A: Altas Activas ---
    altas_activas = CAlta.objects.filter(aspirante_id=aspirante_id).select_related(
        'cargo__ncargo',
        'cargo__departamento__unidad_organizativa',
    )
    for a in altas_activas:
        # CORRECCIÓN: Ignorar el movimiento fantasma de "Alta Inicial" para buscar el pasado real
        mov_id = obtener_id_movimiento(a.no_expediente, 'Alta Inicial', a.fecha_alta)
        mov_alta_real = movs_por_pk.get(mov_id) if mov_id else None

        # PRIORIDAD 1: si existe el TMovimiento "Alta Inicial" y tiene datos propios,
        # se usan tal cual están guardados. Así, editar ese registro en el admin de
        # Django (o borrarlo, dejando mov_alta_real en None) se refleja de inmediato
        # aquí en vez de reconstruirse en silencio a partir del contrato actual.
        if mov_alta_real and mov_alta_real.cargo_nuevo and mov_alta_real.cargo_nuevo != "---":
            cargo_inicial = mov_alta_real.cargo_nuevo
            unidad_inicial = mov_alta_real.unidad_nueva or "---"
            salario_inicial = mov_alta_real.salario_nuevo
        else:
            primer_mov = primer_movimiento_real(contrato=a)

            if primer_mov and primer_mov.cargo_anterior != "---":
                cargo_inicial = primer_mov.cargo_anterior
                unidad_inicial = primer_mov.unidad_anterior or "---"
                salario_inicial = primer_mov.salario_anterior
            else:
                cargo_inicial = a.cargo.ncargo.descripcion if a.cargo else "---"
                unidad_inicial = a.cargo.departamento.unidad_organizativa.descripcion if (a.cargo and a.cargo.departamento) else "---"
                salario_inicial = a.calcular_salario_escala()

        hitos.append({
            'id': mov_id,
            'fecha_orden': a.fecha_alta,
            'fecha_inicio': a.fecha_alta,
            'evento': 'ALTA_PENDIENTE', 
            'expediente': a.no_expediente,
            'unidad': unidad_inicial,
            'cargo': cargo_inicial,
            'salario': fmt_dinero(salario_inicial),
            'es_baja': False
        })

    # --- FUENTE B: Altas de Contratos Cerrados ---
    altas_viejas = CBaja.objects.filter(aspirante_id=aspirante_id).select_related(
        'cargo__ncargo',
        'cargo__departamento__unidad_organizativa',
    )
    for b in altas_viejas:
        if b.fecha_alta:
            mov_id_alta = obtener_id_movimiento(b.no_expediente, 'Alta Inicial', b.fecha_alta)
            mov_id_baja = obtener_id_movimiento(b.no_expediente, 'Baja', b.fecha_baja)
            mov_alta_real = movs_por_pk.get(mov_id_alta) if mov_id_alta else None

            # Mismo criterio que en FUENTE A: si el TMovimiento "Alta Inicial" existe
            # y tiene datos propios, se usan directamente en vez de reconstruirlos.
            if mov_alta_real and mov_alta_real.cargo_nuevo and mov_alta_real.cargo_nuevo != "---":
                cargo_baja_ini = mov_alta_real.cargo_nuevo
                unidad_baja_ini = mov_alta_real.unidad_nueva or "---"
                salario_baja_ini = mov_alta_real.salario_nuevo
            else:
                # CORRECCIÓN: Igual que arriba, ignoramos "Alta Inicial"
                primer_mov_baja = primer_movimiento_real(expediente=b.no_expediente)

                if primer_mov_baja and primer_mov_baja.cargo_anterior != "---":
                    cargo_baja_ini = primer_mov_baja.cargo_anterior
                    unidad_baja_ini = primer_mov_baja.unidad_anterior or "---"
                    salario_baja_ini = primer_mov_baja.salario_anterior
                else:
                    cargo_baja_ini = b.cargo.ncargo.descripcion if b.cargo else "---"
                    unidad_baja_ini = b.cargo.departamento.unidad_organizativa.descripcion if (b.cargo and b.cargo.departamento) else "---"
                    salario_baja_ini = b.cargo.ncargo.salario_basico if b.cargo else 0

            hitos.append({
                'id': mov_id_alta,
                'fecha_orden': b.fecha_alta,
                'fecha_inicio': b.fecha_alta,
                'evento': 'ALTA_PENDIENTE',
                'expediente': b.no_expediente,
                'unidad': unidad_baja_ini,
                'cargo': cargo_baja_ini,
                'salario': fmt_dinero(salario_baja_ini),
                'es_baja': False
            })
            
            # El evento de BAJA explícito
            hitos.append({
                'id': mov_id_baja,
                'fecha_orden': b.fecha_baja,
                'fecha_inicio': b.fecha_baja,
                'evento': 'Baja',
                'expediente': b.no_expediente,
                'unidad': "---",
                'cargo': "---",
                'salario': "---",
                'es_baja': True
            })

    # --- FUENTE C: Movimientos ---
    # CORRECCIÓN: Filtramos los movimientos que crea el sistema por detrás ('Baja' y 'Alta Inicial')
    # Reutilizamos la lista ya cargada en memoria en lugar de volver a consultar.
    movimientos = [m for m in movimientos_aspirante
                   if m.tipo_movimiento not in ('Baja', 'Alta Inicial')]

    for m in movimientos:
        tipo = "Movimiento Salario"
        if m.unidad_anterior != m.unidad_nueva or m.cargo_anterior != m.cargo_nuevo:
            tipo = "Movimiento Cargo"

        hitos.append({
            'id': m.pk,
            'fecha_orden': m.fecha_efectiva,
            'fecha_inicio': m.fecha_efectiva,
            'evento': tipo,
            'expediente': m.no_expediente,
            'unidad': m.unidad_nueva or "---",
            'cargo': m.cargo_nuevo,
            'salario': fmt_dinero(m.salario_nuevo),
            'es_baja': False
        })

    # --- ORDENACIÓN Y LÓGICA CRONOLÓGICA ---
    hitos.sort(key=lambda x: x['fecha_orden'])

    lista_final = []
    total = len(hitos)
    primer_alta = True
    
    # LA CLAVE: Leer el estado real del trabajador para saber si el último ciclo sigue vivo
    esta_activo_ahora = (aspirante.estado == 'ACTIVO')

    for i in range(total):
        item = hitos[i]
        
        # 1. Definir si es Alta Inicial o Recontratación
        if item['evento'] == 'ALTA_PENDIENTE':
            if primer_alta:
                item['evento'] = 'Alta Inicial'
                primer_alta = False
            else:
                item['evento'] = 'Recontratación'

        # =======================================================
        # 2. CALCULAR FECHA FIN (SOLUCIÓN DEFINITIVA)
        # =======================================================
        if i == total - 1:
            # Es el último evento de la historia:
            if item['es_baja']:
                # Si lo último registrado es una Baja, su estado actual es "En Baja"
                # El color será rojo porque el evento es 'Baja' (text-danger)
                item['fecha_fin'] = "Actualidad"
            else:
                # Si lo último es un contrato, solo es Actualidad si el aspirante está ACTIVO
                item['fecha_fin'] = "Actualidad" if esta_activo_ahora else "Cerrado"
        else:
            proximo = hitos[i+1]
            
            # REGLA A: Contrato (Alta/Mov) seguido por su propia Baja.
            # El contrato termina el mismo día que se emite la baja.
            if not item['es_baja'] and proximo['es_baja'] and item['expediente'] == proximo['expediente']:
                item['fecha_fin'] = proximo['fecha_inicio'].strftime('%d/%m/%Y')
            
            # REGLA B: Baja seguida por Recontratación (o Movimiento seguido por otro Movimiento).
            # El estado anterior termina un día antes de que empiece el nuevo hito.
            else:
                fin_dt = proximo['fecha_inicio'] - timedelta(days=1)
                item['fecha_fin'] = fin_dt.strftime('%d/%m/%Y')

        # 3. Asignar Colores (Solo para la fecha fin)
        colores = {
            'Alta Inicial': 'text-success',      # Verde
            'Recontratación': 'text-primary',    # Azul
            'Movimiento Salario': 'text-gold',   # Dorado
            'Movimiento Cargo': 'text-orange',   # Naranja
            'Baja': 'text-danger'                # Rojo
        }
        item['estado_clase'] = colores.get(item['evento'], 'text-muted')
        
        # Formatear fecha inicio
        item['fecha_inicio_str'] = item['fecha_inicio'].strftime('%d/%m/%Y')
        lista_final.append(item)

    # --- CAMBIOS EXTERNOS (23-10-2026) ---
    # Cambios hechos más arriba del contrato (escala, cargo, unidad, importes…). Se
    # intercalan por fecha DESPUÉS de calcular las fechas de fin: no son estados del
    # contrato, así que no cortan el período de ningún movimiento. Los de «Error
    # humano» y los anulados por una corrección no se muestran (quedan en Auditoría).
    from django.utils import timezone

    from .models import CambioExterno
    for cambio in (CambioExterno.objects
                   .filter(aspirante_id=aspirante_id, error_humano=False, anulado=False)
                   .order_by('fecha')):
        dia = timezone.localtime(cambio.fecha).date()
        lista_final.append({
            'id': None, 'es_cambio_externo': True,
            'evento': 'Cambio externo', 'origen': cambio.get_origen_display(),
            'fecha_orden': dia, 'fecha_inicio': dia,
            'fecha_inicio_str': dia.strftime('%d/%m/%Y'), 'fecha_fin': '',
            'expediente': cambio.no_expediente, 'unidad': '---',
            'cargo': cambio.descripcion, 'descripcion': cambio.descripcion,
            'motivo': cambio.motivo, 'usuario': cambio.usuario_nombre,
            'valor_anterior': cambio.valor_anterior, 'valor_nuevo': cambio.valor_nuevo,
            'salario': '---', 'es_baja': False, 'estado_clase': 'text-secondary',
        })
    # Orden estable: en el mismo día, el movimiento va antes que el cambio externo.
    lista_final.sort(key=lambda x: (x['fecha_orden'], bool(x.get('es_cambio_externo'))))

    return JsonResponse({'data': lista_final, 'encabezado': encabezado})

# --- 2. NUEVA VISTA PARA EXPORTAR HISTORIAL COMPLETO (PDF) ---
class ExportarHistoricoPDFView(View):
    def get(self, request, aspirante_id):
        from django.template.loader import get_template
        from xhtml2pdf import pisa
        
        aspirante = get_object_or_404(Aspirante, pk=aspirante_id)
        config = Configuracion.objects.first()
        
        # Súper truco: Llamamos a tu propia función para reciclar los datos ordenados
        respuesta = historico_trabajador(request, aspirante_id)
        datos_historial = json.loads(respuesta.content)['data']
        # Lo mismo que se ve en pantalla: con o sin los cambios externos.
        if request.GET.get('externos') == '0':
            datos_historial = [d for d in datos_historial if not d.get('es_cambio_externo')]
        
        context = {
            'aspirante': aspirante,
            'config': config,
            'fecha_hoy': datetime.now(),
            'historial': datos_historial
        }
        
        template = get_template('pages/reportes/pdf_historico_trabajador.html')
        html = template.render(context)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="%s"' % nombre_de_informe(
            'HISTORICO', nombre_de_persona(aspirante), extension='pdf')
        
        pisa.CreatePDF(html, dest=response)
        return response

# --- 3. NUEVA VISTA PARA LA CÁPSULA DEL TIEMPO (SOLO LECTURA) ---
def movimiento_detalle_readonly(request, pk):
    movimiento = get_object_or_404(TMovimiento, pk=pk)
    context = {
        'object': movimiento,
        'movimiento': movimiento,
        'aspirante': movimiento.aspirante,
        'is_readonly': True,
        
        # Estas son las variables que el modal busca para la columna DERECHA
        'initial_rol': movimiento.rol_nuevo,
        'initial_grupo': movimiento.grupo_escala_nuevo,
        'initial_cat': movimiento.cat_ocupacional_nuevo,
        'initial_salario_escala': movimiento.salario_nuevo,
    }
    return render(request, 'pages/contrato/movimiento_nomina.html', context)

class ContratoCreateView(RequiereEdicionMixin, CreateView):
    model = CAlta
    form_class = CAltaForm
    template_name = "pages/contrato/add_contrato.html"
    success_url = reverse_lazy('list_aspir')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user  # <-- aquí pasas el usuario
        # El formulario necesita al trabajador para resolver los importes de
        # maestría y doctorado desde su grado científico. Al crear todavía no hay
        # contrato del que sacarlo, así que se pasa desde la URL.
        kwargs['aspirante'] = get_object_or_404(
            Aspirante, doc_identidad=self.kwargs['aspirante_id'])
        return kwargs

    def get_initial(self):
        """El cargo desde el que se abrió el modal, si vino del Gestor de Cargos.

        Llega como `?cargo=<id>`. Se comprueba que exista y esté activo antes de
        proponerlo: la URL se puede escribir a mano, y un id inventado dejaría el
        formulario apuntando a una plaza que no está.
        """
        initial = super().get_initial()
        cargo_id = self.request.GET.get('cargo')
        if cargo_id and str(cargo_id).isdigit():
            cargo = CargoPlantilla.objects.filter(pk=cargo_id, activo=True).first()
            if cargo:
                initial['cargo'] = cargo.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # aspirante_id viene en la URL
        aspirante_id = self.kwargs['aspirante_id']
        context['aspirante'] = get_object_or_404(Aspirante, doc_identidad=aspirante_id)

        # El cargo propuesto, para que la pantalla pueda preseleccionar también
        # su Unidad y su Departamento: el <select> de cargo depende de los dos.
        cargo = None
        cargo_id = self.initial.get('cargo') or self.get_initial().get('cargo')
        if cargo_id:
            cargo = (CargoPlantilla.objects
                     .select_related('departamento__unidad_organizativa')
                     .filter(pk=cargo_id).first())
        context['cargo_propuesto'] = cargo
        return context

    def form_valid(self, form):
        self.object = form.save(commit=False)

        aspirante_id = self.kwargs['aspirante_id']
        self.object.aspirante = get_object_or_404(Aspirante, doc_identidad=aspirante_id)
        
        # --- FASE 1: GUARDAR EN SESIÓN, NO EN BD ---
        # Convertimos los datos críticos del formulario a un diccionario serializable
        contrato_data = form.cleaned_data.copy()

        # 'rol' y 'grupo_escala' son campos de PRESENTACIÓN: CharField de solo lectura
        # que muestran lo que se deduce del cargo. Como son readonly (no disabled) el
        # navegador los envía, y al llegar al wizard el mapeo automático los convierte
        # en 'rol_id' → se intentaría escribir el texto "Fundamental" en una clave
        # foránea. El rol real se asigna desde el cargo al guardar.
        for campo_presentacion in ('rol', 'grupo_escala'):
            contrato_data.pop(campo_presentacion, None)

        from decimal import Decimal # <--- Importación necesaria para detectar los decimales
        
        # Limpiar datos no serializables (fechas, objetos, decimales) para la sesión
        for key, value in contrato_data.items():
            if hasattr(value, 'isoformat'): # Fechas
                contrato_data[key] = value.isoformat()
            elif hasattr(value, 'pk'): # Modelos (ForeignKeys)
                contrato_data[key] = value.pk
            elif isinstance(value, Decimal): # <--- SOLUCIÓN AL ERROR: Convertir Decimales
                contrato_data[key] = str(value) # Lo guardamos como string para no perder precisión
        
        # Almacenamos el borrador
        self.request.session['contrato_borrador'] = contrato_data
        self.request.session['aspirante_borrador'] = aspirante_id
        
        # NO HACEMOS self.object.save()
        
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            from django.urls import reverse
            return JsonResponse({
                'form_is_valid': True,
                'message': 'Borrador guardado. Continuando al movimiento de nómina...',
                # En la Fase 2 crearemos esta URL para el modal del Movimiento, 
                # por ahora usaremos un endpoint temporal o el que vayamos a crear:
                'redirect_to_wizard': reverse('wizard_movimiento_nomina', kwargs={'aspirante_id': aspirante_id}) 
            })
        
        # Evitamos el guardado por defecto de CreateView
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(self.success_url)

    def form_invalid(self, form):
        # 1. Imprimir en consola para depuración
        logger.warning("Errores al crear contrato: %s", form.errors.as_json())

        # 2. RESPUESTA AJAX (Para evitar el crasheo)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            
            # Capturador dinámico de errores para el SweetAlert
            error_mensaje = None
            if 'no_expediente' in form.errors:
                # El error REAL del campo (duplicado, más de 5 dígitos, letras,
                # cero...). Antes cualquiera de ellos se anunciaba como "ya está
                # en uso", lo que despistaba cuando el problema era otro.
                error_mensaje = form.errors['no_expediente'][0]
            elif 'cargo' in form.errors:
                error_mensaje = form.errors['cargo'][0]
            elif 'reg_militar' in form.errors:
                error_mensaje = "El campo Servicio Militar es obligatorio."
            elif form.errors:
                # Si es cualquier otro error, agarramos el primero que encuentre
                primer_campo = list(form.errors.keys())[0]
                error_mensaje = f"Verifique el campo '{primer_campo}': {form.errors[primer_campo][0]}"
            
            # Renderizamos el formulario con los errores pintados (rojo)
            html = render_to_string(
                self.template_name,
                self.get_context_data(form=form),
                request=self.request
            )
            
            # Devolvemos JSON con el HTML y el mensaje para el SweetAlert
            return JsonResponse({
                'form_is_valid': False, 
                'html_form': html,
                'error_popup': error_mensaje  # <--- Este es el dato clave
            })
            
        return super().form_invalid(form)

class ContratoUpdateView(RequiereEdicionMixin, AdvertenciasDelRegistroMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = CAlta
    form_class = CAltaForm
    template_name = "pages/contrato/updt_contrato.html"
    template_name_pagina = "pages/contrato/updt_contrato_pagina.html"
    url_por_defecto = reverse_lazy('list_contrato')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        # --- TU LÓGICA ORIGINAL SE MANTIENE INTACTA ---
        context = super().get_context_data(**kwargs)

        contrato = self.object
        context['aspirante'] = contrato.aspirante

        context['fecha_contratacion_actual'] = contrato.fecha_ultima_accion

        # Salario, tarifa y horas extras con el cálculo ÚNICO de la app (el mismo del
        # Word, los informes y la Pre-Nómina). Antes esta pantalla consultaba la escala
        # por su cuenta: ignoraba el salario Fijo y dejaba vacío el de los cuadros.
        tarifas = calcular_tarifas(contrato.calcular_salario_escala())
        context['initial_salario_escala'] = tarifas['salario'] if tarifas['salario'] is not None else ""
        context['initial_tarifa_horaria'] = tarifas['tarifa'] if tarifas['tarifa'] is not None else ""
        context['initial_tarifa_extras'] = tarifas['extras'] if tarifas['extras'] is not None else ""

        return context

    # --- MÉTODOS AÑADIDOS PARA SOPORTE AJAX ---

    def post(self, request, *args, **kwargs):
        # Para un Moderador esto registra la propuesta y sale: el contrato definitivo no
        # se toca hasta que un Administrador la apruebe. Ver `solicitudes/integracion.py`.
        desvio = interceptar(self, request, AccionSolicitud.EDITAR)
        if desvio is not None:
            return desvio
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        self.object = form.save(commit=False)

        # --- LIMPIEZA AUTOMÁTICA DE TRIDENTE ---
        if self.object.cargo and self.object.cargo.ncargo.es_cuadro:
            self.object.tridente = None
            
        self.object.save()

        # La rama HTMX de abajo cierra el modal en la MISMA página (responde 204,
        # sin recargar), así que un `messages.success()` incondicional ahí quedaría
        # «colgado» en la sesión y podría aparecer en una navegación posterior no
        # relacionada — el guard `hay_origen` solo protege esa rama.
        # La rama AJAX normal, en cambio, SIEMPRE termina en una navegación completa
        # (`window.location.href` en updt_contrato.html), así que el mensaje se
        # genera siempre: se consumirá correctamente en la página siguiente.
        hay_origen = bool(self.request.POST.get('next') or self.request.GET.get('next'))

        # ✅ PARA PETICIONES AJAX NORMALES (esto va ANTES del bloque HTMX)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            from django.http import JsonResponse
            messages.success(self.request, self.mensaje_de_guardado_exitoso('Contrato actualizado correctamente.'))
            return JsonResponse({
                'form_is_valid': True,
                'success_url': str(self.get_success_url())
            })

        # MAGIA HTMX: Respondemos directamente con las órdenes para el frontend
        if self.request.headers.get('HX-Request'):
            import json
            from django.http import HttpResponse
            if hay_origen:
                messages.success(self.request, self.mensaje_de_guardado_exitoso('Contrato actualizado correctamente.'))
            response = HttpResponse(status=204)
            response['HX-Trigger'] = json.dumps({
                'updateContratoList': '',
                'updateCargoList': '',
                'showMessage': {'icon': 'success', 'text': 'Contrato actualizado.'},
                'closeModal': ''
            })
            return response

        messages.success(self.request, self.mensaje_de_guardado_exitoso('Contrato actualizado correctamente.'))
        return super(UpdateView, self).form_valid(form)

    def form_invalid(self, form):
        # RESPUESTA AJAX (ERROR)
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            html = render_to_string(
                self.template_name,
                self.get_context_data(form=form),
                request=self.request
            )
            return JsonResponse({'form_is_valid': False, 'html_form': html})
            
        return super().form_invalid(form)



SALARIO_NO_CALCULADO = (
    'Salario no calculado: no se encontró un salario de escala para la combinación de '
    'cargo, rol y tridente seleccionada. Revise esos datos antes de confirmar el movimiento.')


class ContratoBajaView(RequiereEdicionMixin, DeleteView):
    """Da de BAJA un contrato: lo archiva en la lista de Bajas (`CBaja`), con su
    movimiento de nómina y su evento de Auditoría «Baja». No es borrar un
    contrato: en Contratos no se elimina nada, solo se da de baja.

    Hereda de `DeleteView` solo por `get_object()`; todo el proceso está en
    `post()`. La URL conserva su nombre histórico, `del_contrato`, para no tocar
    las plantillas ni el JavaScript que la usan.
    """
    model = CAlta

    # Solo POST. La baja se pide desde el modal que ya vive en `list_contrato.html`,
    # nunca navegando a esta URL: no hay ninguna pantalla de confirmación propia. Sin
    # esta restricción, `DeleteView` atendía el GET intentando pintar
    # `contratos/calta_confirm_delete.html`, una plantilla que no existe, y respondía
    # con un error 500 en lugar del 405 que corresponde a un método no admitido.
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        # Asegúrate de tener este import arriba del todo en el archivo:
        
        
        # 1. Recuperar el objeto de forma segura
        try:
            contrato: CAlta = self.get_object() # type: ignore
        except CAlta.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'El contrato que intenta eliminar no existe.'}, status=404)

        # 2. Obtener datos del formulario
        fecha_baja_str = request.POST.get('fecha_baja')
        fecha_efectiva_str = request.POST.get('fecha_efectiva')
        causa_id = request.POST.get('causa_baja')
        cobro_sistema = request.POST.get('cobro_sistema_pago') == 'true'
        completar_cargo_val = request.POST.get('completar_cargo') == 'true'
        actividad_manual = request.POST.get('actividad_realizada')
        observaciones_texto = request.POST.get('observaciones', '')


        if not fecha_baja_str or not causa_id:
            return JsonResponse({'success': False, 'message': 'Faltan datos obligatorios: Fecha de Baja o Causa.'}, status=400)

        # 3. Convertir fecha para validar
        try:
            fecha_baja = datetime.strptime(fecha_baja_str, '%Y-%m-%d').date()
            fecha_efectiva = datetime.strptime(fecha_efectiva_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
             return JsonResponse({'success': False, 'message': 'Formato de fecha inválido.'}, status=400)

        # =================================================================
        # VALIDACIÓN CRONOLÓGICA (La Barrera)
        # =================================================================
        
        
        # Regla única del histórico (`contratos/cronologia.py`): la baja no puede ser
        # futura ni caer el mismo día o antes que el último evento de la persona.
        # El documento de la baja tampoco puede estar fechado en el futuro.
        mensaje = (validar_fecha_evento(fecha_baja, contrato.aspirante_id, contrato,
                                        etiqueta='La fecha de baja')
                   or validar_fecha_no_futura(fecha_efectiva, 'La fecha del documento'))
        if mensaje:
            return JsonResponse({'success': False, 'message': mensaje}, status=400)
        # =================================================================

        try:
            # 4. Iniciar Transacción. El registro automático de Auditoría queda en
            # pausa: la baja se audita abajo como UN solo evento (la eliminación
            # del contrato con los datos de la baja), no como los cinco cambios que
            # hace por dentro (movimiento, CBaja, aspirante, plazas y el borrado).
            with transaction.atomic(), registro_automatico.sin_auditoria_automatica():
                # Un evento de la persona cada vez (24-10-2026): con la ficha bloqueada se
                # vuelve a comprobar que el contrato sigue y que la fecha aún vale (otro
                # usuario pudo guardar un movimiento o la misma baja mientras tanto).
                bloquear_historico(contrato.aspirante_id)
                if not CAlta.objects.filter(pk=contrato.pk).exists():
                    return JsonResponse({'success': False, 'message': (
                        'Este contrato ya no está vigente: otro usuario le dio de baja mientras '
                        'tanto. Recargue la lista.')}, status=409)
                mensaje = validar_fecha_evento(fecha_baja, contrato.aspirante_id, contrato,
                                               etiqueta='La fecha de baja')
                if mensaje:
                    return JsonResponse({'success': False, 'message': mensaje}, status=400)

                # A. SALVAR EL HISTORIAL EXISTENTE
                TMovimiento.objects.filter(contrato=contrato).update(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente
                )

                # B. CAPTURAR DATOS PARA EL HISTÓRICO ANTES DE BORRAR
                cargo_ant_str = contrato.cargo.ncargo.descripcion if contrato.cargo else "---"
                unidad_ant_obj = contrato.cargo.departamento.unidad_organizativa if (contrato.cargo and contrato.cargo.departamento) else None
                unidad_ant_str = unidad_ant_obj.descripcion if unidad_ant_obj else "---"
                rol_ant_str = contrato.cargo.rol.tipo if (contrato.cargo and contrato.cargo.rol) else "---"
                tri_ant_str = str(contrato.tridente) if contrato.tridente else "---"
                salario_ant_val = contrato.calcular_salario_escala() or 0

                # C. CREAR EL ÚNICO MOVIMIENTO DE BAJA (Corrigiendo el error de fechas)
                # fecha_baja (Modal) = Fecha Efectiva (Cuando se va)
                # fecha_efectiva (Modal) = Fecha Documento (Cuando se firma)
                movimiento_baja = TMovimiento.objects.create(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente,
                    contrato=None, 
                    fecha_efectiva=fecha_baja,      
                    fecha_solicitud=fecha_efectiva, 
                    tipo_movimiento="Baja",
                    observaciones=observaciones_texto, # <--- AQUÍ GUARDAMOS LA OBSERVACIÓN
                    
                    cargo_anterior=cargo_ant_str,
                    departamento_anterior=contrato.cargo.departamento.descripcion if (contrato.cargo and contrato.cargo.departamento) else "---",
                    grupo_escala_anterior=contrato.cargo.ncargo.grupo_escala.nivel if (contrato.cargo and contrato.cargo.ncargo.grupo_escala) else "---",
                    cat_ocupacional_anterior=contrato.cargo.ncargo.get_cat_ocupacional_display() if contrato.cargo else "---",
                    tipo_salario_anterior=contrato.get_tipo_salario_display() if contrato.tipo_salario else "---",
                    rol_anterior=rol_ant_str,
                    tridente_anterior=tri_ant_str,
                    unidad_anterior=unidad_ant_str,
                    unidad_anterior_fk=unidad_ant_obj,
                    salario_anterior=salario_ant_val,
                    # «Otros» congelado al darse de baja (24-10-2026).
                    otros_anterior=contrato.importe_otros,

                    cargo_nuevo="---",
                    salario_nuevo=0,
                    unidad_nueva="---"
                )
                
                # D. Crear registro histórico en CBaja
                CBaja.objects.create(
                    aspirante=contrato.aspirante,
                    no_expediente=contrato.no_expediente,
                    tipo=contrato.tipo,
                    cargo=contrato.cargo,
                    reg_militar=contrato.reg_militar,
                    profesional=contrato.profesional,
                    fecha_baja=fecha_baja,
                    causa_baja_id=causa_id,
                    fecha_alta=contrato.fecha_alta,
                    # La entrada real a la empresa, que `fecha_alta` (la del contrato)
                    # no representa en quien ha sido recontratado. Es lo que necesita
                    # la columna «Años en la Organización» del modelo de bajas.
                    fecha_alta_entidad=contrato.fecha_alta_entidad,
                    fecha_documento=fecha_efectiva,
                    tridente=contrato.tridente,
                    cobro_sistema_pago=cobro_sistema,
                    actividad_realizada=actividad_manual,
                    observaciones=observaciones_texto,
                    completar_cargo=completar_cargo_val
                )

                # E. Capturar el cargo antes de borrar el contrato
                cargo_obj = None
                if contrato.tipo and contrato.tipo.ocupa_plaza and contrato.cargo:
                    cargo_obj = contrato.cargo

                # Cambiar estado del aspirante a BAJA
                if contrato.aspirante:
                    contrato.aspirante.estado = 'BAJA'
                    contrato.aspirante.save()

                # F. Borrar contrato
                foto_contrato = registro_automatico.fotografia(contrato)
                contrato_pk = contrato.pk
                contrato.delete()

                causa = NCausaAltaBaja.objects.filter(pk=causa_id).first()
                registro_automatico.registrar(
                    contrato, AccionAuditoria.BAJA,
                    object_id=contrato_pk, antes=foto_contrato,
                    despues={
                        'Causa de baja': str(causa) if causa else '—',
                        'Fecha de baja': fecha_baja.strftime('%d/%m/%Y'),
                        'Fecha del documento': fecha_efectiva.strftime('%d/%m/%Y'),
                        'Cobro por el sistema de pago': 'Sí' if cobro_sistema else 'No',
                        'Completar cargo': 'Sí' if completar_cargo_val else 'No',
                        'Actividad realizada': actividad_manual or '—',
                        'Observaciones': observaciones_texto or '—',
                    })

                # G. Refrescar el número oficial en la Base de Datos
                if cargo_obj:
                    cargo_obj.refrescar_conteo_plazas()

            # Usamos el PK del único movimiento creado (ruta explícita de TMovimiento)
            pdf_url = reverse('imprimir_movimiento', kwargs={'pk': movimiento_baja.pk})

            from progreso.servicios import completar_tarea
            completar_tarea(request.user, 'primera_baja')
            from ranking.models import Actividad
            from ranking.servicios import registrar_actividad
            registrar_actividad(request.user, Actividad.BAJA, detalle=contrato)

            return JsonResponse({
                'success': True,
                'message': 'Contrato dado de baja y archivado correctamente.',
                'pdf_url': pdf_url
            })

        except Exception as e:
            # Captura cualquier error (Integridad, Modelo, etc.) y evita el crash del servidor
            logger.exception("Error al dar baja al contrato %s: %s", kwargs.get('pk'), e)
            return JsonResponse({
                'success': False, 
                'message': f'Error interno al procesar la baja: {str(e)}'
            }, status=500)
#*REPORTES

        


class MovimientoUpdateView(RequiereEdicionMixin, ModalOPaginaCompletaMixin, VolverAlOrigenMixin, UpdateView):
    model = CAlta
    form_class = MovimientoForm
    template_name = "pages/contrato/movimiento_nomina.html"
    template_name_pagina = "pages/contrato/movimiento_nomina_pagina.html"
    url_por_defecto = reverse_lazy('list_movimientos')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contrato = self.object
        context['contrato_actual'] = contrato
        context['aspirante'] = contrato.aspirante
        
        if contrato.cargo:
            # Usamos el método centralizado. ¡Ya no hay lógica duplicada!
            salario_base = contrato.calcular_salario_escala()
            context['salario_actual'] = salario_base # Pasa el número real al template

            context['initial_grupo'] = contrato.cargo.ncargo.grupo_escala
            context['initial_cat'] = contrato.cargo.ncargo.get_cat_ocupacional_display()
            context['initial_rol'] = contrato.cargo.rol.tipo if contrato.cargo.rol else "-"
            
            if salario_base:
                tarifas = calcular_tarifas(salario_base)
                context['initial_salario_escala'] = tarifas['salario']
                context['initial_tarifa_horaria'] = tarifas['tarifa'] if tarifas['tarifa'] is not None else ""
                context['initial_tarifa_extras'] = tarifas['extras'] if tarifas['extras'] is not None else ""
        
        # Último evento del histórico de la persona, para el JavaScript (la fecha
        # nueva tiene que ser estrictamente posterior). El servidor lo vuelve a
        # comprobar al guardar con la misma regla (`contratos/cronologia.py`).
        fecha_limite = ultimo_evento(contrato.aspirante_id, contrato)
        if fecha_limite:
            context['fecha_limite_js'] = fecha_limite.strftime('%Y-%m-%d')

        return context
    
    # ... (form_valid y form_invalid se quedan igual) ...
    # Sin registro automático de Auditoría: el movimiento se audita abajo como una
    # sola modificación del contrato; el TMovimiento que se crea es su documento.
    @transaction.atomic
    @registro_automatico.sin_auditoria_automatica()
    def form_valid(self, form):
        def rechazar(mensaje, campo=None):
            if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
            form.add_error(campo, mensaje)
            return self.form_invalid(form)

        try:
            # 1. Obtener contrato y fecha nueva
            contrato = self.object
            nueva_fecha = form.cleaned_data.get('fecha_efectiva')

            # Un evento de la persona cada vez (24-10-2026): si otro usuario guarda a la
            # vez un movimiento, una baja o una corrección suya, este espera su turno y
            # valida la fecha contra lo que el otro dejó.
            bloquear_historico(contrato.aspirante_id)
            if not CAlta.objects.filter(pk=contrato.pk).exists():
                return rechazar('Este contrato ya no está vigente: otro usuario le dio de baja '
                                'mientras tanto. Recargue la lista.')

            # =================================================================
            # PASO 1: VALIDACIÓN CRONOLÓGICA (EL PORTERO)
            # =================================================================
            
            # Regla única del histórico (`contratos/cronologia.py`): ni futura ni el
            # mismo día o antes que el último evento de la persona.
            mensaje = validar_fecha_evento(
                nueva_fecha, contrato.aspirante_id, contrato,
                etiqueta='La fecha efectiva del movimiento')
            if mensaje:
                if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
                else:
                    form.add_error('fecha_efectiva', mensaje)
                    return self.form_invalid(form)

            # =================================================================
            # PASO 1.5: VALIDACIÓN DE CAMBIOS REALES PARA MOVIMIENTO
            # =================================================================
            # Solo cuenta lo que cambia el CONTRATO (cargo, tipo, motivo, duración,
            # tipo de salario, tridente). Antes se miraba `form.has_changed()`, que
            # daba siempre «sí» porque la fecha efectiva, la de solicitud y las
            # observaciones no tienen valor inicial, así que este aviso nunca
            # saltaba (24-10-2026). Escribir solo un número de resolución tampoco es
            # un movimiento: eso se hace editando el contrato.
            cambios = [c for c in form.changed_data if c in MovimientoForm.CAMPOS_DEL_MOVIMIENTO]
            if not cambios:
                mensaje = "No se ha aplicado ningún cambio válido. Modifique algún dato para generar un movimiento."
                
                if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
                else:
                    form.add_error(None, mensaje)
                    return self.form_invalid(form)
            
            # Obtenemos el contrato previo seguro para extraer la historia
            contrato_previo = CAlta.objects.get(pk=self.object.pk)

            # =================================================================
            # PASO 2: CAPTURAR DATOS PREVIOS (LÓGICA DE NEGOCIO)
            # =================================================================
            cargo_ant = contrato_previo.cargo.ncargo.descripcion if contrato_previo.cargo else "---"
            unidad_ant_obj = contrato_previo.cargo.departamento.unidad_organizativa if (contrato_previo.cargo and contrato_previo.cargo.departamento) else None
            unidad_ant = unidad_ant_obj.descripcion if unidad_ant_obj else "---"

            rol_ant_str = contrato_previo.cargo.rol.tipo if (contrato_previo.cargo and contrato_previo.cargo.rol) else "---"
            tri_ant_str = str(contrato_previo.tridente) if contrato_previo.tridente else "---"
            salario_ant = contrato_previo.calcular_salario_escala() or 0

            # --- NUEVO: CAPTURAR TIPO Y MOTIVO ANTERIOR ---
            tipo_ant_str = contrato_previo.tipo.descripcion if contrato_previo.tipo else "---"
            motivo_ant_str = contrato_previo.motivo.descripcion if contrato_previo.motivo else "---"

            # PASO 3: CAPTURAR DATOS NUEVOS
            cargo_nuevo_obj = form.cleaned_data.get('cargo')
            tipo_nuevo_obj = form.cleaned_data.get('tipo')
            motivo_nuevo_obj = form.cleaned_data.get('motivo')
            duracion_nueva_val = form.cleaned_data.get('duracion')
            
            cargo_nue = cargo_nuevo_obj.ncargo.descripcion if cargo_nuevo_obj else "---"
            unidad_nue_obj = cargo_nuevo_obj.departamento.unidad_organizativa if (cargo_nuevo_obj and cargo_nuevo_obj.departamento) else None
            unidad_nue = unidad_nue_obj.descripcion if unidad_nue_obj else "---"

            # El salario lo calcula el servidor con la escala (24-10-2026), no se toma
            # el que manda el navegador: es el mismo cálculo que enseña la pantalla.
            tridente_obj = form.cleaned_data.get('tridente')
            salario_calculado = salario_de_escala_para(
                cargo_nuevo_obj, form.cleaned_data.get('tipo_salario'),
                tridente_obj.pk if tridente_obj else None)
            if not salario_calculado or salario_calculado <= 0:
                return rechazar(SALARIO_NO_CALCULADO)
            salario_nue = float(salario_calculado)

            observaciones_txt = form.cleaned_data.get('observaciones', '')
            fecha_solicitud_dt = form.cleaned_data.get('fecha_solicitud')

            # PASO 4: GUARDAR EL HISTÓRICO
            from django.utils import timezone 
            
            # Extraemos la descripción del Tipo de Salario del formulario
            tipo_sal_nue_val = dict(form.fields['tipo_salario'].choices).get(form.cleaned_data.get('tipo_salario'), "---")

            nuevo_mov = TMovimiento.objects.create(
                contrato=self.object,
                aspirante=self.object.aspirante,
                no_expediente=self.object.no_expediente,
                fecha_efectiva=nueva_fecha if nueva_fecha else timezone.now().date(),
                fecha_solicitud=fecha_solicitud_dt,
                observaciones=observaciones_txt,
                
                # FOTO DEL PASADO
                cargo_anterior=cargo_ant,
                departamento_anterior=contrato_previo.cargo.departamento.descripcion if (contrato_previo.cargo and contrato_previo.cargo.departamento) else "---",
                grupo_escala_anterior=contrato_previo.cargo.ncargo.grupo_escala.nivel if (contrato_previo.cargo and contrato_previo.cargo.ncargo.grupo_escala) else "---",
                cat_ocupacional_anterior=contrato_previo.cargo.ncargo.get_cat_ocupacional_display() if contrato_previo.cargo else "---",
                tipo_salario_anterior=contrato_previo.get_tipo_salario_display() if contrato_previo.tipo_salario else "---",
                rol_anterior=rol_ant_str,       
                tridente_anterior=tri_ant_str,  
                salario_anterior=salario_ant,
                # «Otros» congelado (24-10-2026); el «A» se anota tras guardar.
                otros_anterior=contrato_previo.importe_otros,
                unidad_anterior=unidad_ant,
                unidad_anterior_fk=unidad_ant_obj,
                tipo_contrato_anterior=tipo_ant_str, # <--- NUEVO
                motivo_anterior=motivo_ant_str,      # <--- NUEVO
                
                # FOTO DE LA NUEVA PROPUESTA
                cargo_nuevo=cargo_nue,
                departamento_nuevo=cargo_nuevo_obj.departamento.descripcion if (cargo_nuevo_obj and cargo_nuevo_obj.departamento) else "---",
                grupo_escala_nuevo=cargo_nuevo_obj.ncargo.grupo_escala.nivel if (cargo_nuevo_obj and cargo_nuevo_obj.ncargo.grupo_escala) else "---",
                cat_ocupacional_nuevo=cargo_nuevo_obj.ncargo.get_cat_ocupacional_display() if cargo_nuevo_obj else "---",
                tipo_salario_nuevo=tipo_sal_nue_val,
                rol_nuevo=cargo_nuevo_obj.rol.tipo if (cargo_nuevo_obj and cargo_nuevo_obj.rol) else "---",
                tridente_nuevo=str(form.cleaned_data.get('tridente')) if form.cleaned_data.get('tridente') else "---",
                salario_nuevo=salario_nue,
                unidad_nueva=unidad_nue,
                unidad_nueva_fk=unidad_nue_obj,
                tipo_contrato_nuevo=tipo_nuevo_obj.descripcion if tipo_nuevo_obj else "---", # <--- NUEVO
                motivo_nuevo=motivo_nuevo_obj.descripcion if motivo_nuevo_obj else "---",   # <--- NUEVO
                duracion_nueva=duracion_nueva_val,                                           # <--- NUEVO
                
                tipo_movimiento="Movimiento de Nómina"
            )

            # PASO 5: ACTUALIZAR CONTRATO
            antes_auditoria = registro_automatico.fotografia(contrato_previo, con_vacios=True)
            form.instance.en_proceso_movimiento = False
            self.object = form.save()
            # Releído de la base: así las fechas ya son fechas y no el texto del formulario.
            TMovimiento.objects.filter(pk=nuevo_mov.pk).update(
                otros_nuevo=CAlta.objects.get(pk=self.object.pk).importe_otros)
            registro_automatico.registrar(
                self.object, AccionAuditoria.MOVIMIENTO, antes=antes_auditoria,
                despues=registro_automatico.fotografia(self.object, con_vacios=True))

            # La ficha del trabajador sigue su unidad: si el movimiento lo cambió de
            # unidad, la ficha también (decisión de RRHH, 23-10-2026). Es parte del
            # mismo movimiento, así que va con update() y sin evento propio.
            if unidad_nue_obj and self.object.aspirante.unidad_organizativa_id != unidad_nue_obj.pk:
                Aspirante.objects.filter(pk=self.object.aspirante_id).update(
                    unidad_organizativa=unidad_nue_obj)

            messages.success(self.request, 'Movimiento de Nómina registrado correctamente.')

            # La unidad ANTERIOR del contrato (antes de este cambio) ya era una de
            # las mías -> lo hice todo yo (Caso 1, interno). Si no era mía, es que
            # otro moderador la cedió y yo la estoy recibiendo ahora (Caso 3).
            # Al Administrador (sin `unidades` propias) siempre se le cuenta como
            # interno: no tiene sentido "recibir de otro moderador" para él.
            usuario = self.request.user
            codigo_tarea = 'primer_movimiento_interno'
            if getattr(usuario, 'es_moderador', False) and unidad_ant_obj:
                if not usuario.unidades.filter(pk=unidad_ant_obj.pk).exists():
                    codigo_tarea = 'primer_movimiento_recibido'

            from progreso.servicios import completar_tarea
            completar_tarea(usuario, codigo_tarea)
            from ranking.models import Actividad
            from ranking.servicios import registrar_actividad
            registrar_actividad(usuario, Actividad.MOVIMIENTO, detalle=self.object)

            if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':


                return JsonResponse({
                    'form_is_valid': True,
                    'message': 'Movimiento registrado correctamente.',
                    'success_url': self.get_success_url(),
                    # Ahora sí existe 'nuevo_mov'
                    'pdf_url': reverse('imprimir_movimiento', kwargs={'pk': nuevo_mov.pk})
                })
            return super().form_valid(form)

        
        except Exception as e:
            # --- MANEJO DE ERRORES ---
            logger.exception(
                "Error crítico en movimiento de nómina (contrato=%s): %s",
                getattr(self.object, 'pk', None), e
            )

            transaction.set_rollback(True)
            return JsonResponse({'form_is_valid': False, 'error_popup': str(e)}, status=500)

    def form_invalid(self, form):
        logger.warning("Movimiento de nómina inválido: %s", form.errors.as_json())


        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest':
            # Construimos un mensaje legible a partir de los errores del formulario
            mensajes = []
            for campo, errores in form.errors.items():
                for error in errores:
                    mensajes.append(str(error))
            mensaje_final = " ".join(mensajes) if mensajes else "Revise los datos del formulario."

            return JsonResponse({
                'form_is_valid': False,
                'error_popup': mensaje_final,   # ← el frontend ya sabe leer esta clave
            }, status=400)
            
        return super().form_invalid(form)
    

def abreviar_cargo_inteligente(texto_cargo):
    if not texto_cargo: return "-"
    
    diccionario = {
        "OPERADOR": "OP.", "OBRERO": "OBR.", "OPERARIO": "OPE.", "ESPECIALISTA": "ESP.",
        "MANTENIMIENTO": "MANT.", "DEPARTAMENTO": "DPTO.", "ADMINISTRATIVO": "ADMIN.",
        "ADMINISTRACION": "ADMIN.", "SERVICIOS": "SERVS.", "GENERAL": "GRAL.",
        "AUXILIAR": "AUX.", "TECNICO": "TEC.", "TÉCNICO": "TÉC.",
        "SUPERIOR": "SUP.", "PRINCIPAL": "PRAL.", "PRODUCCION": "PROD.",
        "FABRICACION": "FAB.", "FABRICACIÓN": "FAB.", "TRANSFORMADORES": "TRANSF.",
        "DISTRIBUCION": "DIST.", "ENERGETICO": "ENERG.", "MAQUINARIA": "MAQ.",
        "RECURSOS": "REC.", "HUMANOS": "HUM.", "SEGURIDAD": "SEG.",
    }
    
    palabras = texto_cargo.upper().split()
    # Pylance fix: Aseguramos que 'p' siempre es str y el resultado también
    palabras_nuevas = [str(diccionario.get(p, p)) for p in palabras]
    return " ".join(palabras_nuevas)


class ModeloMovimientoDocxView(View):
    def get(self, request, pk, origen=None):
        # --- FASE 1: RESOLVER EL REGISTRO ---
        obj = None
        es_movimiento_real = False

        if origen == 'movimiento':
            # Ruta explícita: el pk es SIEMPRE de TMovimiento.
            # La ruta genérica de abajo probaba CAlta primero, así que un
            # TMovimiento.pk que coincidiera con un CAlta.pk existente (algo muy
            # probable, ambas secuencias arrancan en 1) imprimía el documento
            # de OTRO trabajador.
            obj = get_object_or_404(TMovimiento, pk=pk)
            es_movimiento_real = True
        else:
            # 1. Intentar como CAlta (pk de contrato)
            try:
                contrato = CAlta.objects.get(pk=pk)
                # Buscar el movimiento asociado a este contrato (el más reciente)
                movimiento = TMovimiento.objects.filter(contrato_id=contrato.pk).order_by('-id').first()
                if movimiento:
                    obj = movimiento
                    es_movimiento_real = True
                else:
                    # Sin movimiento (no debería pasar, porque pdf_url vacío cuando no hay)
                    obj = contrato
                    es_movimiento_real = False
            except CAlta.DoesNotExist:
                # 2. Si no es contrato, intentar como TMovimiento directo
                try:
                    obj = TMovimiento.objects.get(pk=pk)
                    es_movimiento_real = True
                except TMovimiento.DoesNotExist:
                    # 3. Fallback final a CBaja
                    obj = CBaja.objects.filter(pk=pk).first()
                    if not obj:
                        return HttpResponse("Error: No se encontró el registro.", status=404)
                    es_movimiento_real = True

        # Contrato base (CAlta activo). Si es baja, esto será None porque ya se borró.
        contrato_base = obj.contrato if es_movimiento_real and hasattr(obj, 'contrato') else (obj if not es_movimiento_real else None)

        # --- CONFIGURACIÓN TARIFA ---
        # Fondo de tiempo de Configuración, sin valor fijo de respaldo (si falta,
        # la tarifa queda vacía y la regla CFG-004 lo avisa).
        fondo = float(parametros_de_tarifa()[0] or 0)

        # --- FUNCIONES DE FORMATO LIBRES DE "NONE" ---
        def obtener_inicial_categoria(cat_str):
            if not cat_str or str(cat_str) == "None": return ""
            cat = str(cat_str).upper()
            if "OBRERO" in cat: return "O"
            if "TÉCNICO" in cat or "TECNICO" in cat: return "T"
            if "CUADRO" in cat: return "C"
            if "SERVICIOS" in cat: return "S"
            if "ADMINISTRATIVO" in cat: return "A"
            return cat[0]

        def formatear_tridente(tri_obj):
            """Extrae el numeral romano (I/II/III) del texto guardado ("Tridente I", etc.)
            para el Word: el modelo del documento exige números romanos, no arábigos."""
            if not tri_obj or str(tri_obj) in ["None", "---"]: return ""
            t = str(tri_obj).upper()
            if "III" in t: return "III"
            if "II" in t: return "II"
            if "I" in t: return "I"
            return t

        # --- DETECCIÓN DE BAJA ---
        t_mov_str = str(getattr(obj, 'tipo_movimiento', "Alta Inicial" if not es_movimiento_real else "")).upper()
        es_alta = "ALTA" in t_mov_str
        es_baja = "BAJA" in t_mov_str
        es_movimiento = "MOVIMIENTO" in t_mov_str

        # Para las Bajas, necesitamos el registro histórico (CBaja) para sacar el Departamento y Categoría exactos
        baja_record = CBaja.objects.filter(no_expediente=obj.no_expediente).order_by('-id').first() if es_baja else None
        
        # El cargo de referencia (De donde sacamos dpto, ueb, categoria)
        cargo_ref = baja_record.cargo if (es_baja and baja_record) else (contrato_base.cargo if contrato_base else None)

        # --- LÓGICA DE DATOS SUPERIORES (UEB, Categoria, Cargo, Area) ---
        if es_baja:
            ueb_val = getattr(obj, 'unidad_anterior', "")
            if not ueb_val or ueb_val == "---":
                ueb_val = cargo_ref.departamento.unidad_organizativa.descripcion if cargo_ref else ""
            
            cargo_texto = getattr(obj, 'cargo_anterior', "")
            if not cargo_texto or cargo_texto == "---":
                cargo_texto = cargo_ref.ncargo.descripcion if cargo_ref else ""
                
        else:
            ueb_val = getattr(obj, 'unidad_nueva', "") if es_movimiento_real else ""
            if not ueb_val or ueb_val == "---":
                ueb_val = cargo_ref.departamento.unidad_organizativa.descripcion if cargo_ref else ""
            
            cargo_texto = getattr(obj, 'cargo_nuevo', "") if es_movimiento_real else ""
            if not cargo_texto or cargo_texto == "---":
                cargo_texto = cargo_ref.ncargo.descripcion if cargo_ref else ""

        # Área y Categoría
        area_val = getattr(obj, 'departamento_nuevo', None) if es_movimiento_real else ""
        if not area_val or area_val == "---":
            area_val = cargo_ref.departamento.descripcion if cargo_ref else ""

        cat_str = getattr(obj, 'cat_ocupacional_nuevo', None) if es_movimiento_real else ""
        if not cat_str or cat_str == "---":
            cat_str = cargo_ref.ncargo.get_cat_ocupacional_display() if cargo_ref and hasattr(cargo_ref.ncargo, 'get_cat_ocupacional_display') else ""
        
        cat_val = obtener_inicial_categoria(cat_str)

        # Extracción segura del Rol
        rol_n = getattr(obj, 'rol_nuevo', "") if es_movimiento_real else ""
        if not rol_n or rol_n == "---":
            rol_n = contrato_base.cargo.rol.tipo if contrato_base and contrato_base.cargo and getattr(contrato_base.cargo, 'rol', None) else ""

        # Tridente: se muestra tal cual quedó guardado en el TMovimiento histórico.
        # NO se rellena con el tridente ACTUAL del contrato como respaldo: este es
        # un documento histórico y el contrato pudo cambiar de tridente después de
        # este movimiento, así que inventar el dato falsearía el registro. Si sale
        # vacío es porque el TMovimiento se guardó sin tridente_nuevo — ver la causa
        # raíz real en los puntos donde se crea TMovimiento con tipo_movimiento=
        # "Alta Inicial"/"Recontratación" sin ese campo.
        tri_n = getattr(obj, 'tridente_nuevo', "") if es_movimiento_real else ""

        # Ajuste de tamaño de texto para Cargo
        if len(cargo_texto) > 35:
            cargo_final = RichText(cargo_texto, size=14)
        elif len(cargo_texto) > 25:
            cargo_final = RichText(cargo_texto, size=16)
        else:
            cargo_final = cargo_texto

        # --- LÓGICA DE SALARIOS BASE ---
        salario_base_num = float(getattr(obj, 'salario_nuevo', 0) or 0) if es_movimiento_real else float(contrato_base.calcular_salario_escala() or 0)
        tarifa_base_num = salario_base_num / fondo if fondo else 0
        salario_str = f"{salario_base_num:.2f} ({tarifa_base_num:.5f})" if salario_base_num > 0 else ""

        # --- OTROS Y TOTAL ---
        # Desde el 24-10-2026 «Otros» (grado científico + Instructor + CNCI + Años
        # de servicio) va CONGELADO en el movimiento: el documento no cambia con
        # el tiempo. Sin movimiento (contrato suelto) se calcula a hoy.
        suma_otros_num = 0
        if es_movimiento_real and getattr(obj, 'otros_nuevo', None) is not None:
            suma_otros_num = float(obj.otros_nuevo)
        elif contrato_base is not None and not es_movimiento_real:
            suma_otros_num = float(contrato_base.importe_otros)

        if suma_otros_num > 0:
            tarifa_otros_num = suma_otros_num / fondo if fondo else 0
            otros_str = f"{suma_otros_num:.2f} ({tarifa_otros_num:.5f})"
        else:
            otros_str = ""
        
        total_num = salario_base_num + suma_otros_num
        tarifa_total_num = total_num / fondo if fondo else 0
        total_str = f"{total_num:.2f} ({tarifa_total_num:.5f})" if total_num > 0 else ""

        # --- LÓGICA DE FECHAS (CORREGIDA) ---
        f_sol = getattr(obj, 'fecha_solicitud', None)
        fecha_efectiva = getattr(obj, 'fecha_efectiva', None) or getattr(obj, 'fecha_alta', datetime.now())

        # Fecha de solicitud (puede ser None)
        if f_sol:
            d_sol = f_sol.strftime("%d")
            m_sol = f_sol.strftime("%m")
            a_sol = f_sol.strftime("%Y")   # ← AÑO COMPLETO 4 DÍGITOS
        else:
            d_sol = ""
            m_sol = ""
            a_sol = ""

        # Fecha efectiva (siempre presente)
        ed = fecha_efectiva.strftime("%d")
        em = fecha_efectiva.strftime("%m")
        ea = fecha_efectiva.strftime("%Y")   # ← AÑO COMPLETO 4 DÍGITOS

        # --- CONSTRUCCIÓN DEL CONTEXTO PARA EL WORD ---
        context = {
            'doc_id': f"{obj.pk:06d}" if es_movimiento_real and not es_alta else "", 
            'ueb': ueb_val,
            
            # CABECERA SUPERIOR → FECHA DE SOLICITUD (o vacío)
            'd': d_sol,
            'm': m_sol,
            'a': a_sol,   # ← AÑO DE SOLICITUD (4 dígitos)
            
            # BLOQUE INFERIOR → FECHA EFECTIVA
            'ed': ed,
            'em': em,
            'ea': ea,     # ← AÑO DE EFECTIVA (4 dígitos)
            
            'x_alta': "X" if es_alta else "",
            'x_baja': "X" if es_baja else "",
            'x_mov':  "X" if es_movimiento else "",
            
            'nombre': obj.aspirante.nombre,
            'ap1': obj.aspirante.papellido,
            'ap2': obj.aspirante.sapellido,
            'exp': obj.no_expediente,
            
            'cat': cat_val,
            'cargo': cargo_final,
            'area': area_val,
            
            # --- FILA "A:" ---
            'rol_nue': "" if es_baja else rol_n,
            'tri_nue': "" if es_baja else formatear_tridente(tri_n),
            'sal_nue': "" if es_baja else salario_str,
            'otros': "" if es_baja else otros_str,
            'total_sal': "" if es_baja else total_str,
            
            'observaciones': getattr(obj, 'observaciones', "") or getattr(obj, 'motivo_movimiento', ""),
        }

        # --- FILA "DE:" (HISTÓRICO) ---
        if es_movimiento_real:
            sal_ant_num = float(getattr(obj, 'salario_anterior', 0) or 0)
            tarifa_ant_num = sal_ant_num / fondo if fondo else 0
            
            # «Otros» de antes, congelado en el movimiento (24-10-2026).
            suma_otros_ant = float(getattr(obj, 'otros_anterior', None) or 0)

            if suma_otros_ant > 0:
                tarifa_otros_ant = suma_otros_ant / fondo if fondo else 0
                otros_ant_str = f"{suma_otros_ant:.2f} ({tarifa_otros_ant:.5f})"
            else:
                otros_ant_str = ""

            total_ant_num = sal_ant_num + suma_otros_ant
            tarifa_total_ant = total_ant_num / fondo if fondo else 0
            total_ant_str = f"{total_ant_num:.2f} ({tarifa_total_ant:.5f})" if total_ant_num > 0 else ""

            # Extraemos el Rol asegurándonos de que si viene la palabra "None" la borre
            rol_ant_bd = str(getattr(obj, 'rol_anterior', ""))
            
            context.update({
                'rol_ant': "" if rol_ant_bd == "None" else rol_ant_bd,
                'tri_ant': formatear_tridente(getattr(obj, 'tridente_anterior', "")),
                'sal_ant': f"{sal_ant_num:.2f} ({tarifa_ant_num:.5f})" if sal_ant_num > 0 else "",
                'otros_ant': otros_ant_str,
                'total_ant': total_ant_str,
            })

        # --- GENERACIÓN DEL DOCUMENTO ---
        try:
            # Todas las plantillas de Word viven juntas en `plantillas_word/`.
            # Esta estaba suelta dentro de `templates/`, que es la carpeta de las
            # plantillas HTML de Django: un .docx ahí no lo encuentra nadie que
            # vaya a buscarlo, y Django además rastrea ese directorio.
            template_path = os.path.join(
                settings.BASE_DIR, 'plantillas_word', 'documentos_legales',
                '13-MOVIMIENTO DE NOMINAS.docx')
            doc = DocxTemplate(template_path)
            doc.render(context)
            
            buffer = BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            # `MOV_`, `ALTA_` o `BAJA_` + nombre + expediente (core/nombres_descarga.py).
            if es_baja:
                prefijo = 'BAJA'
            elif es_alta or 'RECONTRAT' in t_mov_str:
                prefijo = 'ALTA'
            else:
                prefijo = 'MOV'
            filename = documento_de_trabajador(prefijo, obj.aspirante, obj.no_expediente, 'docx')
            response = HttpResponse(buffer.getvalue(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        except Exception as e:
            return HttpResponse(f"Error al generar el documento: {str(e)}", status=500)
# 2. ACTUALIZA ESTA FUNCIÓN (Agregamos el retorno de textos para OOB)
# contratos/views.py

def cargar_salario(request):
    cargo_id      = request.GET.get('cargo')
    tridente_id   = request.GET.get('tridente')
    tipo_salario  = request.GET.get('tipo_salario')
    es_movimiento = request.GET.get('es_movimiento') 

    context = {
        'salario': 0.00, 'tarifa': 0, 'extras': 0,
        'nuevo_rol': '', 'nuevo_grupo': '', 
        'mostrar_tridente': False, 
        'es_movimiento': es_movimiento == '1',
        'es_cuadro_flag': False
    }

    if cargo_id:
        try:
            # 1. Cargamos el cargo con sus relaciones
            cargo = CargoPlantilla.objects.select_related('ncargo').get(id=cargo_id)
            grupo_obj = cargo.ncargo.grupo_escala
            rol_obj = cargo.rol  
            
            # 2. DETERMINAMOS SI ES CUADRO
            cat_nombre = cargo.ncargo.get_cat_ocupacional_display()
            categorias_cuadro = ["Cuadro Ejecutivo", "Cuadro Directivo", "CEJ", "CDI"]
            es_cuadro_por_cat = cat_nombre in categorias_cuadro or cargo.ncargo.cat_ocupacional in categorias_cuadro
            
            context['es_cuadro_flag'] = es_cuadro_por_cat
            context['nueva_cat'] = cat_nombre
            # AQUÍ LA CORRECCIÓN: Si no hay rol, se queda en "-", sin inventar "Cuadro"
            context['nuevo_rol'] = rol_obj.tipo if rol_obj else "-"
            context['nuevo_grupo'] = grupo_obj.nivel if grupo_obj else "-"
            
            # El tridente solo se muestra (y solo cuenta) para un salario dinámico que
            # no sea de Cuadro. Del XXII al XXIV la escala solo tiene Decisorios.
            nivel_num = nivel_romano_a_int(grupo_obj.nivel) if grupo_obj else 0
            context['mostrar_tridente'] = (
                tipo_salario != 'FIJ' and not es_cuadro_por_cat
                and not (22 <= nivel_num <= 24 and rol_obj and rol_obj.tipo != "Decisorio"))

            # El salario con el cálculo ÚNICO de la app (`contratos/salarios.py`), el
            # mismo del Word, los informes y la Pre-Nómina; y la tarifa y las horas
            # extras con la fórmula única (`contratos/tarifas.py`). Antes aquí las
            # horas extras eran «salario ÷ 160.6», fijo en el código.
            tridente = tridente_id if (context['mostrar_tridente'] and str(tridente_id).isdigit()) else None
            tarifas = calcular_tarifas(salario_de_combinacion(cargo, tridente, tipo_salario))
            if tarifas['salario']:
                context.update({
                    'salario': tarifas['salario'],
                    'tarifa': tarifas['tarifa'] or 0,
                    'extras': tarifas['extras'] or 0,
                })
                
        except Exception as e:
            logger.exception("Error calculando salario (cargo=%s, tridente=%s): %s", cargo_id, tridente_id, e)

    return render(request, "pages/contrato/partials/cargar_salario.html", context)


def cargar_annos_servicio(request):
    """Años de servicio y su pago, a partir de la F. Alta Entidad del formulario.

    Va aparte de `cargar_salario()` y no mezclado con él porque no comparten NADA:
    el salario de escala depende del cargo y del tridente, y este importe depende
    solo de una fecha. Unirlos obligaría a recalcular la escala salarial cada vez
    que se toca una fecha, y al revés.

    La fecha llega en `hx-vals` leída del DOM y no por `hx-include`, porque el
    campo `fecha_alta_entidad` nace `disabled` en el formulario y un campo
    deshabilitado no viaja en el envío: con `hx-include` la primera carga llegaría
    siempre sin fecha y borraría el valor.
    """
    texto = (request.GET.get('fecha_alta_entidad') or '').strip()
    fecha = None
    if texto:
        try:
            fecha = datetime.strptime(texto, '%Y-%m-%d').date()
        except ValueError:
            # Una fecha a medio teclear no es un error: se trata como «todavía no
            # hay fecha» y los dos campos salen vacíos.
            fecha = None

    annos, pago = annos_y_pago(fecha)
    return render(request, "pages/contrato/partials/cargar_annos_servicio.html", {
        'annos_servicio': annos if fecha else '',
        'pago_annos_servicio': f'{pago:.2f}' if pago is not None else '',
    })

# --- AÑADIR AL FINAL DE views.py ---

def cargar_cargos_contrato(request):
    """Vista exclusiva para rellenar el select de cargos en modales de Contratos vía HTMX"""
    id_dpto = request.GET.get('departamento')
    if id_dpto and id_dpto.isdigit():
        cargos = CargoPlantilla.objects.filter(
            departamento_id=id_dpto, 
            activo=True
        ).select_related('ncargo').order_by('ncargo__descripcion')
    else:
        cargos = CargoPlantilla.objects.none()
        
    # Renderiza estrictamente nuestra plantilla con los atributos data-
    return render(request, 'pages/contrato/partials/options_cargos.html', {'cargos': cargos})


# =========================================================================
# VISTA WIZARD FASE 3: Finalizar Contrato y (Opcional) Movimiento
# =========================================================================
@requiere_edicion
def finalizar_contrato_wizard(request, aspirante_id):
    borrador = request.session.get('contrato_borrador')
    aspirante_borrador = request.session.get('aspirante_borrador')

    def _abortar_wizard(mensaje):
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
        messages.error(request, mensaje)
        return redirect('list_aspir')

    if not borrador:
        return _abortar_wizard('No hay datos en proceso. Cierre y vuelva a intentar.')

    # El borrador vive en la sesión del usuario, que es única. Si quedó uno a medias
    # de otro trabajador (por ejemplo al cerrar el modal con la X en vez de Cancelar),
    # aquí se crearía un contrato con SUS datos a nombre de esta otra persona.
    # Comprobamos que el borrador corresponde al aspirante de la URL.
    if str(aspirante_borrador) != str(aspirante_id):
        request.session.pop('contrato_borrador', None)
        request.session.pop('aspirante_borrador', None)
        return _abortar_wizard(
            'El contrato en proceso pertenece a otro trabajador y se ha descartado '
            'por seguridad. Vuelva a llenar el formulario.'
        )

    aspirante = get_object_or_404(Aspirante, doc_identidad=aspirante_id)

    # Convertir formato de diccionario para la creación dinámica del Modelo 
    # y filtrar campos extras del formulario que no existen en la BD (ej. unidad, departamento)
    borrador_db = borrador.copy()
    
    # Obtenemos los nombres válidos de los campos reales del modelo CAlta
    campos_validos = {f.name for f in CAlta._meta.get_fields()}
    atributos_validos = {getattr(f, 'attname', f.name) for f in CAlta._meta.get_fields()}

    # Campos del formulario que se llaman igual que una relación del modelo pero que
    # NO contienen una clave foránea (son texto para mostrar). Sin esta lista, el
    # mapeo de abajo los convertiría en 'rol_id' y reventaría al guardar.
    CAMPOS_SOLO_PRESENTACION = {'rol', 'grupo_escala'}

    for k in list(borrador_db.keys()):
        if k in CAMPOS_SOLO_PRESENTACION:
            borrador_db.pop(k)
        # Convertir FKs (ej. cargo -> cargo_id)
        elif k + '_id' in atributos_validos and not k.endswith('_id'):
            borrador_db[k + '_id'] = borrador_db.pop(k)
        # Si el campo es del formulario pero NO del modelo, lo descartamos
        elif k not in campos_validos and k not in atributos_validos:
            borrador_db.pop(k)

    # La sesión guarda las fechas como texto ISO. Se convierten aquí, una vez, porque
    # la ventana del Alta Inicial calcula «Otros» con la F. Alta Entidad (25-10-2026).
    from django.db.models import DateField
    from django.utils.dateparse import parse_date
    for campo in CAlta._meta.get_fields():
        if isinstance(campo, DateField) and isinstance(borrador_db.get(campo.name), str):
            borrador_db[campo.name] = parse_date(borrador_db[campo.name]) or None

    # GET: Construir el modal vacío (La columna izquierda oculta)
    if request.method == 'GET':
        try:
            unsaved_contrato = CAlta(**borrador_db)
            unsaved_contrato.aspirante = aspirante
        except Exception as e:
            logger.exception("Error al instanciar CAlta desde el borrador: %s", e)
            return JsonResponse({'form_is_valid': False, 'error_popup': f"Error interno en los datos: {str(e)}"}, status=500)
            
        # 1. PRECARGAR EL FORMULARIO CON LA INSTANCIA
        initial_data = {}
        if borrador_db.get('fecha_alta'):
            initial_data['fecha_efectiva'] = borrador_db.get('fecha_alta') 
            
        # --- INGENIERÍA INVERSA: Recuperar combos perdidos en la purga ---
        unidad_id = None
        dpto_id = None
        
        if unsaved_contrato.cargo_id:
            try:
                cargo_obj = CargoPlantilla.objects.select_related('departamento').get(pk=unsaved_contrato.cargo_id)
                if cargo_obj.departamento:
                    dpto_id = cargo_obj.departamento.id
                    unidad_id = cargo_obj.departamento.unidad_organizativa_id
                    
                    # Inyectamos al formulario para que los combos aparezcan seleccionados
                    initial_data['unidad'] = unidad_id
                    initial_data['departamento'] = dpto_id
                    initial_data['cargo'] = unsaved_contrato.cargo_id
            except CargoPlantilla.DoesNotExist:
                pass
                
        # Los querysets dependientes se pasan al constructor (no se asignan después),
        # para que el formulario pueda construir el mapa de plazas con los cargos reales.
        form_movimiento = MovimientoForm(
            instance=unsaved_contrato,
            initial=initial_data,
            user=request.user,
            unidad_id=unidad_id,
            departamento_id=dpto_id,
        )

        # 2. CÁLCULO DE DATOS VISUALES (Columna Derecha)
        i_grupo = '-'
        i_cat = '-'
        i_rol = '-'
        i_salario = 0
        i_tarifa = 0
        i_extras = 0

        if unsaved_contrato.cargo_id:
            try:
                cargo_obj = CargoPlantilla.objects.select_related('ncargo', 'rol').get(pk=unsaved_contrato.cargo_id)
                i_grupo = cargo_obj.ncargo.grupo_escala.nivel if cargo_obj.ncargo.grupo_escala else '-'
                i_cat = getattr(cargo_obj.ncargo, 'get_cat_ocupacional_display')() if hasattr(cargo_obj.ncargo, 'get_cat_ocupacional_display') else '-'
                i_rol = cargo_obj.rol.tipo if cargo_obj.rol else "-"
                
                
                # Salario, tarifa y horas extras con el cálculo ÚNICO de la app (antes
                # aquí las horas extras eran «× 1.25» fijo en el código).
                tarifas = calcular_tarifas(salario_de_combinacion(
                    cargo_obj, unsaved_contrato.tridente_id, unsaved_contrato.tipo_salario))
                if tarifas['salario']:
                    i_salario = tarifas['salario']
                    i_tarifa = tarifas['tarifa'] or 0
                    i_extras = tarifas['extras'] or 0
            except Exception as e:
                logger.exception("Error precargando datos del cargo en el wizard: %s", e)

        context = {
            'is_wizard': True,
            'aspirante': aspirante,
            'contrato_actual': unsaved_contrato, 
            'form': form_movimiento,
            'initial_rol': i_rol, 
            'initial_grupo': i_grupo, 
            'initial_cat': i_cat,
            'salario_actual': 0, # En wizard la izquierda SIEMPRE es 0 o vacía
            'initial_salario_escala': i_salario,
            'initial_tarifa_horaria': i_tarifa, 
            'initial_tarifa_extras': i_extras,
        }

        # =========================================================
        # LA MAGIA DEL WIZARD: Inyectar la fecha límite a la Fase 3
        # =========================================================
        
        
        # Último evento de la persona (su última baja o movimiento): la fecha del
        # alta tiene que ser como pronto el día siguiente. El POST lo vuelve a
        # comprobar con la misma regla (`contratos/cronologia.py`).
        fecha_limite = ultimo_evento(aspirante.id)
        if fecha_limite:
            context['fecha_limite_js'] = fecha_limite.strftime('%Y-%m-%d')
        # =========================================================

        return render(request, "pages/contrato/movimiento_nomina.html", context)

    # POST: Ejecutar el guardado en Base de Datos
    elif request.method == 'POST':
        from django.urls import reverse
        from django.utils import timezone
       
        
        try:
            # Sin registro automático de Auditoría: el alta se audita como UNA
            # creación del contrato al final, ya con los datos del movimiento si lo
            # hubo (aquí el contrato se guarda dos veces y nace un TMovimiento).
            with transaction.atomic(), registro_automatico.sin_auditoria_automatica():
                # Un evento de la persona cada vez (24-10-2026): si dos usuarios terminan
                # a la vez el asistente con la misma persona, solo uno la contrata.
                bloquear_historico(aspirante.pk)
                if CAlta.objects.filter(aspirante=aspirante).exists():
                    transaction.set_rollback(True)
                    return JsonResponse({'form_is_valid': False, 'error_popup': (
                        'Esta persona ya tiene un contrato vigente: otro usuario la contrató '
                        'mientras tanto.')}, status=400)

                # 1. CREAR CONTRATO (Siempre se hace)
                contrato = CAlta(**borrador_db)
                contrato.aspirante = aspirante
                
                if contrato.cargo_id:
                    # Bloqueamos la fila del cargo dentro de la transacción. La plaza se
                    # validó en la Fase 1, pero el contrato no se guarda hasta aquí: en
                    # ese intervalo otro usuario pudo ocupar la última vacante.
                    cargo_obj = CargoPlantilla.objects.select_for_update().select_related('ncargo').get(pk=contrato.cargo_id)

                    if contrato.tipo and contrato.tipo.ocupa_plaza:
                        if not cargo_obj.en_plantilla:
                            transaction.set_rollback(True)
                            return JsonResponse({
                                'form_is_valid': False,
                                'error_popup': (
                                    f'El cargo "{cargo_obj.ncargo.descripcion}" está fuera de la '
                                    'plantilla aprobada, por lo que no admite contratos que '
                                    'ocupen plaza.'
                                )
                            }, status=400)

                        if cargo_obj.cant_cubierta_real >= cargo_obj.cant_aprobada:
                            transaction.set_rollback(True)
                            return JsonResponse({
                                'form_is_valid': False,
                                'error_popup': (
                                    f'El cargo "{cargo_obj.ncargo.descripcion}" ya no tiene plazas '
                                    f'disponibles ({cargo_obj.cant_cubierta_real}/{cargo_obj.cant_aprobada}). '
                                    'Es posible que otro usuario haya ocupado la última mientras '
                                    'llenaba el contrato.'
                                )
                            }, status=400)
                
                # --- LA FECHA DEL ALTA ES LA FECHA EFECTIVA DEL MOVIMIENTO ---
                # Manda siempre la fecha de la pantalla del movimiento, no la del
                # borrador. Es obligatoria (ya no se pone «hoy» por defecto) y pasa por
                # la regla única del histórico ANTES de guardar nada: ni futura, ni el
                # mismo día o antes que la última baja o movimiento de la persona (en
                # una recontratación, como pronto el día siguiente a la baja).
                try:
                    from datetime import datetime
                    fecha_ui = datetime.strptime(
                        request.POST.get('fecha_efectiva') or '', '%Y-%m-%d').date()
                except ValueError:
                    fecha_ui = None
                mensaje = validar_fecha_evento(
                    fecha_ui, aspirante.id, etiqueta='La fecha efectiva del alta')
                # Del borrador llega como texto ISO (la sesión no guarda fechas).
                alta_entidad = contrato.fecha_alta_entidad
                if isinstance(alta_entidad, str):
                    from django.utils.dateparse import parse_date
                    alta_entidad = parse_date(alta_entidad)
                if not mensaje and alta_entidad and alta_entidad > fecha_ui:
                    mensaje = (
                        f'La fecha efectiva del alta ({fecha_ui:%d/%m/%Y}) no puede ser '
                        f'anterior a la F. Alta Entidad ({alta_entidad:%d/%m/%Y}).')
                if mensaje:
                    transaction.set_rollback(True)
                    return JsonResponse({'form_is_valid': False, 'error_popup': mensaje}, status=400)
                contrato.fecha_alta = fecha_ui

                contrato.save() # Guardado Físico
                logger.info("Contrato creado desde el wizard: pk=%s aspirante=%s", contrato.pk, contrato.aspirante_id)
                
                pdf_url = ""
                
                # 2. CREAR EL MOVIMIENTO «ALTA INICIAL»: SIEMPRE (decisión de RRHH del
                # 23-10-2026). Ya no existe «Omitir movimiento»: todo contrato nace con
                # su Alta Inicial en el histórico. Si el formulario no es válido, no se
                # guarda nada (ni el contrato).
                # Números de resolución (25-10-2026): manda lo que diga la ventana del
                # Alta Inicial, también si se vació. Si la ventana no los envía (una
                # pestaña abierta antes de esta versión), se conservan los del contrato;
                # antes se guardaban vacíos y se perdía lo escrito en el paso 1.
                datos_movimiento = request.POST.copy()
                for campo in MovimientoForm.CAMPOS_RESOLUCION:
                    if campo not in datos_movimiento:
                        datos_movimiento[campo] = borrador.get(campo) or ''
                form = MovimientoForm(datos_movimiento, instance=contrato, user=request.user)
                if form.is_valid():
                    cargo_nuevo = form.cleaned_data.get('cargo')
                    # El salario lo calcula el servidor (24-10-2026), como en el movimiento.
                    tridente_obj = form.cleaned_data.get('tridente')
                    salario_calculado = salario_de_escala_para(
                        cargo_nuevo, form.cleaned_data.get('tipo_salario'),
                        tridente_obj.pk if tridente_obj else None)
                    if not salario_calculado or salario_calculado <= 0:
                        transaction.set_rollback(True)
                        return JsonResponse({'form_is_valid': False,
                                             'error_popup': SALARIO_NO_CALCULADO}, status=400)
                    salario_nue = float(salario_calculado)

                    tipo_sal_nue_val = dict(form.fields['tipo_salario'].choices).get(form.cleaned_data.get('tipo_salario'), "---")
                    mov_alta = TMovimiento.objects.create(
                        contrato=contrato,
                        aspirante=aspirante,
                        no_expediente=contrato.no_expediente,
                        # La misma fecha ya validada arriba: el alta y su movimiento
                        # son un solo evento del histórico.
                        fecha_efectiva=contrato.fecha_alta,
                        fecha_solicitud=form.cleaned_data.get('fecha_solicitud'),
                        observaciones=form.cleaned_data.get('observaciones', ''),
                        
                        cargo_anterior="---",
                        salario_anterior=0,
                        otros_anterior=0,
                        unidad_anterior="---",
                        
                        cargo_nuevo=cargo_nuevo.ncargo.descripcion if cargo_nuevo else "---",
                        departamento_nuevo=cargo_nuevo.departamento.descripcion if (cargo_nuevo and cargo_nuevo.departamento) else "---",
                        grupo_escala_nuevo=cargo_nuevo.ncargo.grupo_escala.nivel if (cargo_nuevo and cargo_nuevo.ncargo.grupo_escala) else "---",
                        cat_ocupacional_nuevo=cargo_nuevo.ncargo.get_cat_ocupacional_display() if cargo_nuevo else "---",
                        tipo_salario_nuevo=tipo_sal_nue_val,
                        rol_nuevo=cargo_nuevo.rol.tipo if (cargo_nuevo and cargo_nuevo.rol) else "---",
                        tridente_nuevo=str(form.cleaned_data.get('tridente')) if form.cleaned_data.get('tridente') else "---",
                        # El tipo de contrato, el motivo y la duración no se guardaban en
                        # el Alta Inicial (24-10-2026): el siguiente movimiento decía venir
                        # de un tipo que el alta no tenía (regla MOV-015).
                        tipo_contrato_nuevo=str(form.cleaned_data.get('tipo')) if form.cleaned_data.get('tipo') else "---",
                        motivo_nuevo=str(form.cleaned_data.get('motivo')) if form.cleaned_data.get('motivo') else "---",
                        duracion_nueva=form.cleaned_data.get('duracion'),
                        salario_nuevo=salario_nue,
                        unidad_nueva=cargo_nuevo.departamento.unidad_organizativa.descripcion if (cargo_nuevo and cargo_nuevo.departamento) else "---",
                        unidad_nueva_fk=cargo_nuevo.departamento.unidad_organizativa if (cargo_nuevo and cargo_nuevo.departamento) else None,

                        tipo_movimiento="Alta Inicial"
                    )
                    form.instance.en_proceso_movimiento = False
                    contrato = form.save()
                    # «Otros» congelado del alta (24-10-2026).
                    # Releído de la base: en el asistente las fechas aún llegan como texto.
                    TMovimiento.objects.filter(pk=mov_alta.pk).update(
                        otros_nuevo=CAlta.objects.get(pk=contrato.pk).importe_otros)
                    # Apuntamos al movimiento recién creado, no al contrato: así el
                    # documento no depende de resolver un pk ambiguo entre tablas.
                    pdf_url = reverse('imprimir_movimiento', kwargs={'pk': mov_alta.pk})
                else:
                    # Si el form falla, cancelamos todo (Contrato no se guarda) y
                    # devolvemos el error al modal. La transacción se anula AL
                    # FINAL: pintar el formulario consulta la base, y con la
                    # transacción ya anulada esas consultas fallaban y el usuario
                    # veía un error técnico (500) en vez del mensaje del formulario.
                    context = {
                        'is_wizard': True, 'aspirante': aspirante, 'contrato_actual': contrato, 'form': form,
                        'initial_rol': '-', 'initial_grupo': '-', 'initial_cat': '-',
                        'salario_actual': 0, 'initial_salario_escala': 0,
                        'initial_tarifa_horaria': 0, 'initial_tarifa_extras': 0,
                    }
                    html = render_to_string("pages/contrato/movimiento_nomina.html", context, request=request)

                    # El modal solo sabe leer 'error_popup'. Sin este mensaje, el
                    # usuario veía "Error de comunicación inesperado" ante cualquier
                    # error de validación.
                    mensajes = [str(error) for errores in form.errors.values() for error in errores]
                    mensaje_final = " ".join(mensajes) if mensajes else "Revise los datos del movimiento."

                    transaction.set_rollback(True)
                    return JsonResponse({
                        'form_is_valid': False,
                        'html_form': html,
                        'error_popup': mensaje_final,
                    }, status=400)
                
                registro_automatico.registrar(
                    contrato, AccionAuditoria.ALTA,
                    despues=registro_automatico.fotografia(contrato))

                # 3. LIMPIEZA
                del request.session['contrato_borrador']
                if 'aspirante_borrador' in request.session:
                    del request.session['aspirante_borrador']

                from progreso.servicios import completar_tarea
                completar_tarea(request.user, 'primera_contratacion')
                from ranking.models import Actividad
                from ranking.servicios import registrar_actividad
                registrar_actividad(request.user, Actividad.ALTA, detalle=contrato)

                return JsonResponse({
                    'form_is_valid': True,
                    'success_url': reverse('list_contrato'),
                    'pdf_url': pdf_url
                })

        except Exception as e:
            logger.exception("Error al finalizar el contrato desde el wizard (aspirante=%s): %s",
                             aspirante_id, e)
            return JsonResponse({'form_is_valid': False, 'error_popup': str(e)}, status=500)

def exportar_contratos_excel(request):
    """Sábana de Excel de la lista de Contratos.

    Desde el 24-10-2026 (decisión de RRHH) exporta las MISMAS filas que se ven en
    la lista, con sus filtros, su búsqueda y su orden (`_contratos_de_la_lista`):
    ya no hay paso intermedio para elegir unidades, porque la lista ya filtra por
    Unidad Organizativa. El Moderador solo ve (y exporta) lo de sus unidades.

    Cada columna se declara UNA vez con su cabecera y su valor (`COLUMNAS_SABANA`),
    así la cabecera y el dato no se pueden descolocar (antes el Móvil salía bajo
    «Fijo» y al revés).
    """
    from core.nombres_descarga import nombre_de_informe
    from prenomina.captura import annos_de_servicio
    from prenomina.models import NEscalaAnnosServicio

    contratos = _contratos_de_la_lista(
        request, 'aspirante__municipio', 'aspirante__provincia', 'aspirante__especialidad',
        'tipo', 'motivo', 'cargo__departamento__unidad_organizativa',
        'cnci_nomenclador', 'instructor_nomenclador')

    # La escala de años de servicio se lee UNA vez, no una por trabajador.
    escala_annos = NEscalaAnnosServicio.como_diccionario()

    def si_no(valor):
        return "Sí" if valor else "No"

    def importe(valor):
        return float(valor) if valor else 0

    def annos(c):
        return annos_de_servicio(c.fecha_alta_entidad) if c.fecha_alta_entidad else None

    def pago_annos(c):
        anos = annos(c)
        if anos is None:
            return None
        pago = NEscalaAnnosServicio.cuantia_de(escala_annos, anos)
        return float(pago) if pago is not None else None

    def grado(c):
        return importe(c.importe_maestria) + importe(c.importe_doctorado)

    def otros(c):
        # Misma suma que el «Otros» del movimiento de nómina: grado científico
        # (Maestría o Doctorado) + Instructor + CNCI + Años de servicio.
        return grado(c) + importe(c.importe_instructor) + importe(c.importe_cnci) + (pago_annos(c) or 0)

    def fecha(valor):
        return valor.strftime('%d/%m/%Y') if valor else ""

    def cargo(c, ruta):
        valor = c.cargo
        for paso in ruta.split('.'):
            valor = getattr(valor, paso, None) if valor is not None else None
        return valor or ""

    COLUMNAS_SABANA = [
        ("No. Expediente", lambda c, a: c.no_expediente),
        ("Nombre", lambda c, a: a.nombre),
        ("1er Apellido", lambda c, a: a.papellido),
        ("2do Apellido", lambda c, a: a.sapellido),
        ("Unidad Organizativa", lambda c, a: cargo(c, 'departamento.unidad_organizativa.descripcion')),
        ("Departamento", lambda c, a: cargo(c, 'departamento.descripcion')),
        ("Cargo", lambda c, a: cargo(c, 'ncargo.descripcion')),
        ("Cat. Ocupacional", lambda c, a: CAT_MAP.get(cargo(c, 'ncargo.cat_ocupacional'),
                                                      cargo(c, 'ncargo.cat_ocupacional')[:1])),
        ("Tipo de Contrato", lambda c, a: getattr(c.tipo, 'descripcion', '')),
        ("Motivo", lambda c, a: getattr(c.motivo, 'descripcion', '')),
        ("Fecha Alta", lambda c, a: fecha(c.fecha_alta)),
        ("F. Alta Entidad", lambda c, a: fecha(c.fecha_alta_entidad)),
        ("Duración (Días)", lambda c, a: c.duracion or ""),
        ("C. Formal", lambda c, a: si_no(c.c_formal)),
        ("No. Res. C. Formal", lambda c, a: c.c_formal_res or ""),
        ("Funcionario", lambda c, a: si_no(c.funcionario)),
        ("No. Res. Funcionario", lambda c, a: c.funcionario_res or ""),
        ("Designado", lambda c, a: si_no(c.designado)),
        ("No. Res. Designado", lambda c, a: c.designado_res or ""),
        ("De Confianza", lambda c, a: si_no(c.de_confianza)),
        ("No. Res. De Confianza", lambda c, a: c.confianza_res or ""),
        ("Trab. a distancia", lambda c, a: si_no(c.trabajo_distancia)),
        ("Teletrabajo", lambda c, a: si_no(c.teletrabajo)),
        ("Pluriempleo", lambda c, a: si_no(c.pluriempleo)),
        ("Chofer Prof.", lambda c, a: si_no(c.profesional)),
        ("Jubilado Recontratado", lambda c, a: si_no(c.jubilado_recontratado)),
        ("Misión", lambda c, a: si_no(c.mision)),
        ("País Misión", lambda c, a: c.pais or ""),
        ("Días Misión", lambda c, a: c.mision_dias or ""),
        ("Importe Misión", lambda c, a: importe(c.mision_importe) if c.mision_importe is not None else ""),
        ("Reg. Militar", lambda c, a: c.get_reg_militar_display() if c.reg_militar else ""),
        ("Grupo Escala", lambda c, a: cargo(c, 'ncargo.grupo_escala.nivel')),
        ("Rol", lambda c, a: cargo(c, 'rol.tipo')),
        ("Tridente", lambda c, a: getattr(c.tridente, 'tipo', '')),
        ("Salario Escala", lambda c, a: importe(c.salario_actual)),
        ("Maestría o Doctorado", lambda c, a: grado(c)),
        ("Instructor", lambda c, a: importe(c.importe_instructor)),
        ("CNCI", lambda c, a: importe(c.importe_cnci)),
        ("Años de Servicio", lambda c, a: annos(c) if annos(c) is not None else ""),
        ("Pago Años de Servicio", lambda c, a: pago_annos(c) if pago_annos(c) is not None else ""),
        ("Otros", lambda c, a: otros(c)),
        ("Carnet de Ident.", lambda c, a: a.doc_identidad),
        ("Serie CI", lambda c, a: a.serie_ci or ""),
        ("Edad", lambda c, a: a.get_edad or ""),
        ("Sexo", lambda c, a: a.get_sexo_display()),
        ("Raza", lambda c, a: a.get_raza_display()),
        ("Nivel Educacional", lambda c, a: a.get_nivel_educ_display()),
        ("Especialidad", lambda c, a: getattr(a.especialidad, 'nombre', '')),
        ("Título de Oro", lambda c, a: si_no(a.titulo_oro)),
        ("Grado Científico", lambda c, a: a.get_grado_cientifico_display() if a.grado_cientifico else ""),
        ("Provincia", lambda c, a: getattr(a.provincia, 'nombre', '')),
        ("Municipio", lambda c, a: getattr(a.municipio, 'nombre', '')),
        ("Dirección", lambda c, a: a.direccion or ""),
        ("Fijo", lambda c, a: a.fijo_personal or ""),
        ("Móvil", lambda c, a: a.movil_personal or ""),
        ("Talla Pantalón/Falda", lambda c, a: a.tpantalon or ""),
        ("Talla Camisa/Blusa", lambda c, a: a.tcamisa or ""),
        ("Talla Zapatos", lambda c, a: a.tzapatos or ""),
    ]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trabajadores Activos"
    ws.append([cabecera for cabecera, _ in COLUMNAS_SABANA])

    negrita_centrado = Font(bold=True, color="FFFFFF")
    fondo_azul = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
    alineacion_centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for col_num, cell in enumerate(ws[1], 1):
        cell.font = negrita_centrado
        cell.fill = fondo_azul
        cell.alignment = alineacion_centro
        ws.column_dimensions[get_column_letter(col_num)].width = 20

    for c in contratos:
        ws.append([valor(c, c.aspirante) for _, valor in COLUMNAS_SABANA])

    # Cabecera fija y filtros de Excel en cada columna.
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions

    hay_filtros = any(v for k, v in request.GET.items() if k not in ('sort', 'order'))
    nombre = nombre_de_informe('Sabana_Contratos', 'filtrado' if hay_filtros else '',
                               extension='xlsx')
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="%s"' % nombre
    wb.save(response)
    return response

MAPA_CATEGORIA_TEXTO = {
    'OPE': 'Obrero',
    'ADM': 'Administrativo',
    'SER': 'Servicio',
    'TEC': 'Técnico',
    'CDI': 'Cuadro',
    'CEJ': 'Cuadro',
}

class ExportarContratoWordView(FormView):
    template_name = "pages/contrato/exportar_contrato.html" # HTML que crearemos luego
    form_class = ExportarContratoWordForm

    PLANTILLAS = {
        'creacion': 'CONTRATO DE TRABAJO 2026.docx',
        'modificacion': 'MODIFICACIÓN AL CONTRATO DE TRABAJO.docx',
    }

    def _get_contrato_optimizado(self, pk):
        """ Consulta unificada para evitar N+1 en las relaciones del contrato """
        # Se llama desde get_initial, get_context_data y form_valid: sin caché se
        # repetía la misma consulta 2-3 veces por petición.
        if getattr(self, '_contrato_cache', None) is not None:
            return self._contrato_cache
        try:
            self._contrato_cache = CAlta.objects.select_related(
                'aspirante__municipio',
                'aspirante__provincia',
                'aspirante__especialidad',
                'cargo__departamento__unidad_organizativa',
                'cargo__ncargo__grupo_escala',
                'cargo__rol',
                'tipo',
                'motivo',
                'tridente',
                'cla',
                'cnci_nomenclador',
                'instructor_nomenclador',
                'nocturnidad_1__nocturnidad',
                'nocturnidad_2__nocturnidad'
            ).get(pk=pk)
        except CAlta.DoesNotExist:
            raise Http404("El contrato solicitado no existe.")
        return self._contrato_cache

    def get_form_kwargs(self):
        """Inyecta el queryset de cuadros activos al formulario."""
        kwargs = super().get_form_kwargs()

        from bolsa.models import Aspirante

        kwargs['cuadros_qs'] = (
            Aspirante.objects.filter(
                estado='ACTIVO',
                calta_contratos__cargo__ncargo__cat_ocupacional__in=['CDI', 'CEJ']
            )
            .distinct()
            .order_by('nombre', 'papellido')
        )

        return kwargs

    def get_initial(self):
        """ Inicializa el formulario transitorio con datos pre-procesados """
        initial = super().get_initial()
        contrato = self._get_contrato_optimizado(self.kwargs['pk'])
        
        config = Configuracion.objects.first()
        
        if config and config.periodo:
            initial['periodo_pago'] = 'Quincenal' if config.periodo == 15 else 'Mensual'
            
        # La del último movimiento de nómina del contrato (el alta cuenta como
        # uno). Es solo la propuesta: RRHH puede cambiarla en el asistente.
        fecha_efectiva = contrato.fecha_efectiva_vigente()
        if fecha_efectiva:
            initial['fecha_efectiva'] = fecha_efectiva

        # Extraer textos de nocturnidad
        textos_noc = []
        for noc_relation in [contrato.nocturnidad_1, contrato.nocturnidad_2]:
            if noc_relation and hasattr(noc_relation, 'nocturnidad') and noc_relation.nocturnidad:
                noc = noc_relation.nocturnidad
                if noc.hora_inicio and noc.hora_fin:
                    t_inicio = noc.hora_inicio.strftime('%I:%M %p').lstrip('0')
                    t_fin = noc.hora_fin.strftime('%I:%M %p').lstrip('0')
                    textos_noc.append(f"{t_inicio} a {t_fin}")

        if textos_noc:
            initial['nocturnidad_texto'] = " y ".join(textos_noc)

        return initial

    def get_context_data(self, **kwargs):
        """ Renderiza la pantalla (Estudio de Exportación) con datos de solo lectura para el usuario """
        context = super().get_context_data(**kwargs)
        contrato = self._get_contrato_optimizado(self.kwargs['pk'])
        context['contrato'] = contrato
        context['config'] = Configuracion.objects.first()
        context['provincias'] = NProvincia.objects.all().order_by('nombre')

        # Municipio de la unidad organizativa del contrato, para precargarlo en
        # el desplegable. La provincia NO se toca: todas las unidades comparten
        # la de Parámetros Generales y solo se les declara el municipio, que
        # además es opcional. Si esta unidad no lo tiene, queda vacío como antes.
        unidad = (contrato.cargo.departamento.unidad_organizativa
                  if contrato.cargo and contrato.cargo.departamento_id else None)
        context['municipio_unidad_id'] = (
            unidad.municipio_id if unidad and unidad.municipio_id else '')

        # Preparar Grados Científicos para solo lectura
        grados = []
        if getattr(contrato, 'importe_maestria', 0) > 0:
            grados.append(f"Maestría (${contrato.importe_maestria})")
        if getattr(contrato, 'importe_doctorado', 0) > 0:
            grados.append(f"Doctorado (${contrato.importe_doctorado})")
        context['grados_cientificos_texto'] = " • ".join(grados) if grados else "(-)"

        # Cálculos Matemáticos de Salario reutilizando el método del modelo
        monto_escala = contrato.calcular_salario_escala()
        context['salario_escala'] = f"{monto_escala:.2f}" if monto_escala else "0.00"
        tarifa = calcular_tarifas(monto_escala)['tarifa']
        context['tarifa_horaria'] = f"{tarifa:.5f}" if tarifa is not None else "0.00"

        return context

    def _extraer_fecha_nacimiento(self, doc_identidad):
        """ Extrae la fecha de nacimiento (dd/mm/yyyy) del Carnet de Identidad Cubano """
        if not doc_identidad or len(doc_identidad) < 6 or not doc_identidad[:6].isdigit():
            return "________"
        try:
            yy, mm, dd = int(doc_identidad[:2]), int(doc_identidad[2:4]), int(doc_identidad[4:6])
            hoy = datetime.today()
            century = 2000 if yy <= hoy.year % 100 else 1900
            fecha_nac = datetime(year=century + yy, month=mm, day=dd)
            return fecha_nac.strftime('%d/%m/%Y')
        except ValueError:
            return "________"

    def _compilar_contexto_word(self, contrato, cleaned_data, config):
        """ Consolida todos los datos en un diccionario listo para DocxTpl """
        
        # 1. Identificación Cuadro Firmante
        empleador_nombre = ""
        empleador_cargo = ""
        cuadro_aspirante = cleaned_data.get('firma_cuadro')
        
        if cuadro_aspirante:
            empleador_nombre = (
                f"{cuadro_aspirante.nombre} "
                f"{cuadro_aspirante.papellido} "
                f"{cuadro_aspirante.sapellido or ''}"
            ).strip()

            contrato_actual = (
                cuadro_aspirante.calta_contratos
                .filter(cargo__isnull=False)
                .select_related('cargo', 'cargo__ncargo')
                .order_by('-fecha_alta')
                .first()
            )

            if contrato_actual and contrato_actual.cargo and contrato_actual.cargo.ncargo:
                empleador_cargo = contrato_actual.cargo.ncargo.descripcion

        # 2. Fechas para el cierre del documento
        fecha_efectiva = cleaned_data.get('fecha_efectiva')
        if fecha_efectiva:
            firma_dia = str(fecha_efectiva.day).zfill(2)
            meses = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio', 
                     7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'}
            firma_mes = meses.get(fecha_efectiva.month, '').capitalize()
            firma_anno = str(fecha_efectiva.year)
        else:
            firma_dia = firma_mes = firma_anno = ""

        # 3. Matemática Salarial
        monto_escala = contrato.calcular_salario_escala()
        salario_escala = f"{monto_escala:.2f}" if monto_escala else ""
        tarifa = calcular_tarifas(monto_escala)['tarifa']
        tarifa_horaria = f"{tarifa:.5f}" if tarifa is not None else ""

        # 4. Extracción de Provincia y Municipio (Desde el HTML manual)
        prov_id = self.request.POST.get('provincia_entidad')
        muni_id = self.request.POST.get('municipio_entidad')
        
        entidad_provincia = ""
        entidad_municipio = ""
        
        if prov_id:
            from nomencladores.models import NProvincia
            prov_obj = NProvincia.objects.filter(id=prov_id).first()
            if prov_obj: entidad_provincia = prov_obj.nombre
            
        if muni_id:
            from nomencladores.models import NMunicipio
            muni_obj = NMunicipio.objects.filter(id=muni_id).first()
            if muni_obj: entidad_municipio = muni_obj.nombre

        # 5. Resolución de Nombramiento (Limpiando el "Campo Vacío")
        res_no = ""
        if contrato.funcionario and contrato.funcionario_res:
            res_no = contrato.funcionario_res
        elif contrato.designado and contrato.designado_res:
            res_no = contrato.designado_res

        # 6. Código del tridente en números romanos ('I', 'II', 'III')
        tridente_codigo = (contrato.tridente.tipo or '').strip().upper() if contrato.tridente else ''

        rol_tipo = (contrato.cargo.rol.tipo or '').upper() if contrato.cargo and contrato.cargo.rol else ''

        # 7. Construcción Final del Diccionario (Valores por defecto en "" para usar el Subrayado de Word)
        ctx = {
            # ENTIDAD Y FIRMANTE
            'entidad_nombre': (
                contrato.cargo.departamento.unidad_organizativa.descripcion
                if contrato.cargo and contrato.cargo.departamento and contrato.cargo.departamento.unidad_organizativa
                else ""
            ),
            'entidad_direccion': config.direccion if config else "",
            'entidad_rama': config.rama if config else "",
            'entidad_provincia': entidad_provincia, 
            'entidad_municipio': entidad_municipio, 
            'empleador_nombre': empleador_nombre,
            'empleador_cargo': empleador_cargo,

            # TRABAJADOR
            'trabajador_nombre': f"{contrato.aspirante.nombre} {contrato.aspirante.papellido} {contrato.aspirante.sapellido or ''}".strip(),
            'trabajador_ci': contrato.aspirante.doc_identidad,
            'trabajador_fecha_nacimiento': self._extraer_fecha_nacimiento(contrato.aspirante.doc_identidad).replace('_', ''),
            'trabajador_profesion': contrato.aspirante.especialidad.nombre if contrato.aspirante.especialidad else "",
            'trabajador_direccion': contrato.aspirante.direccion or "",
            'trabajador_provincia': contrato.aspirante.provincia.nombre if contrato.aspirante.provincia else "",
            'trabajador_municipio': contrato.aspirante.municipio.nombre if contrato.aspirante.municipio else "",

            # CONTRATO (CLÁUSULA PRIMERA Y SEGUNDA)
            'check_indeterminado': "X" if contrato.tipo and "INDETERMINADO" in contrato.tipo.descripcion.upper() else "",
            'check_determinado': "X" if contrato.tipo and "INDETERMINADO" not in contrato.tipo.descripcion.upper() else "",
            'contrato_duracion': f"{contrato.duracion} días." if contrato.duracion else "",
            'contrato_motivo': contrato.motivo.descripcion if contrato.motivo else "",
            'cargo_nombre': contrato.cargo.ncargo.descripcion if contrato.cargo else "",
            'cargo_grupo': contrato.cargo.ncargo.grupo_escala.nivel if contrato.cargo and contrato.cargo.ncargo.grupo_escala else "",
            
            # CATEGORÍA OCUPACIONAL
            'bg_obr': "X" if contrato.cargo and contrato.cargo.ncargo.cat_ocupacional == 'OPE' else "",
            'bg_adm': "X" if contrato.cargo and contrato.cargo.ncargo.cat_ocupacional == 'ADM' else "",
            'bg_ser': "X" if contrato.cargo and contrato.cargo.ncargo.cat_ocupacional == 'SER' else "",
            'bg_tec': "X" if contrato.cargo and contrato.cargo.ncargo.cat_ocupacional == 'TEC' else "",
            'bg_cdi': "X" if contrato.cargo and contrato.cargo.ncargo.cat_ocupacional in ['CDI', 'CEJ'] else "",

            # ROLES
            # El rol es el del cargo que ocupa (antes leía una copia en el contrato
            # que podía quedarse con el rol de un cargo anterior).
            'check_fundamental': "X" if rol_tipo and 'FUNDAMENTAL' in rol_tipo else "",
            'check_apoyo': "X" if rol_tipo and 'APOYO' in rol_tipo else "",
            'check_decisorio': "X" if rol_tipo and 'DECISORIO' in rol_tipo else "",
            
            # TRIDENTES
            # Se marca por el código romano ('I', 'II', 'III'), no por el id de la
            # tabla: si se recrean los nomencladores los ids cambian y el documento
            # marcaría la casilla equivocada.
            'check_t1': "X" if tridente_codigo == 'I' else "",
            'check_t2': "X" if tridente_codigo == 'II' else "",
            'check_t3': "X" if tridente_codigo == 'III' else "",

            # SALARIO Y HORARIOS
            'contrato_jornada': cleaned_data.get('jornada_texto') or "",
            'contrato_horario': cleaned_data.get('horario_texto') or "",
            'salario_resolucion': cleaned_data.get('resolucion_salario_escala') or "",
            'salario_escala': salario_escala,
            'tarifa_horaria': tarifa_horaria,
            'importe_total': salario_escala,
            
            # ADICIONALES Y PAGOS
            'pago_cla': f"(${contrato.cla.tarifa_hora})" if contrato.cla else "",
            'pago_nocturnidad': cleaned_data.get('nocturnidad_texto') or "",
            'pago_cnci': contrato.importe_cnci or "",
            'check_maestria': "X" if getattr(contrato, 'importe_maestria', 0) > 0 else "",
            'maestria_importe': f"${contrato.importe_maestria}" if getattr(contrato, 'importe_maestria', 0) > 0 else "",
            'check_doctorado': "X" if getattr(contrato, 'importe_doctorado', 0) > 0 else "",
            'doctorado_importe': f"${contrato.importe_doctorado}" if getattr(contrato, 'importe_doctorado', 0) > 0 else "",
            'sistema_pago_texto': cleaned_data.get('sistema_pago') or "",
            'check_pago_quincenal': "X" if cleaned_data.get('periodo_pago') == 'Quincenal' else "",
            'check_pago_mensual': "X" if cleaned_data.get('periodo_pago') == 'Mensual' else "",
            
            # RESOLUCIONES Y CIERRE
            'resolucion_nombramiento_no': res_no,
            'check_es_funcionario': "X" if contrato.funcionario else "",
            'check_es_designado': "X" if contrato.designado else "",
            'municipio_firma': entidad_municipio,
            'firma_dia': firma_dia,
            'firma_mes': firma_mes,
            'firma_anno': firma_anno,

            # --- NUEVO: solo para el documento de modificación ---
            'categoria_texto': (
                MAPA_CATEGORIA_TEXTO.get(contrato.cargo.ncargo.cat_ocupacional, "")
                if contrato.cargo and contrato.cargo.ncargo else ""
            ),
            'observaciones': cleaned_data.get('observaciones', '') or "",
        }
        return ctx

    def form_valid(self, form):
        """ Generación y Descarga del Documento Word Binario """
        contrato = self._get_contrato_optimizado(self.kwargs['pk'])
        
        config = Configuracion.objects.first()
        tipo = form.cleaned_data.get('tipo_documento', 'creacion')
        
        # Compilar Contexto (Inyectamos form.cleaned_data)
        context_word = self._compilar_contexto_word(contrato, form.cleaned_data, config)
        
        # Localizar plantilla según el tipo de documento elegido
        nombre_plantilla = self.PLANTILLAS.get(tipo, self.PLANTILLAS['creacion'])
        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'documentos_legales', nombre_plantilla)
        
        if not os.path.exists(template_path):
            # Si el archivo fue borrado del disco, lanzamos el 404
            raise Http404("La plantilla legal oficial no se encuentra en el servidor. Ruta buscada: " + template_path)

        # Inyección a través de DocxTemplate
        doc = DocxTemplate(template_path)
        doc.render(context_word)
        
        # Preparación de la respuesta HTTP para descarga
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        # `CON_` o `MOD_CON_` + nombre + expediente (core/nombres_descarga.py).
        prefijo = 'MOD_CON' if tipo == 'modificacion' else 'CON'
        filename = documento_de_trabajador(prefijo, contrato.aspirante, contrato.no_expediente, 'docx')
        response = HttpResponse(buffer.read(), content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response