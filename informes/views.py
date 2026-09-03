# 1. Librerías Estándar de Python
import os
import calendar
import re
from datetime import date, datetime

# 2. Librerías y Módulos de Django
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import get_template
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from django.views.generic import TemplateView
# 3. Librerías de Terceros
from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage
from xhtml2pdf import pisa

# 4. Modelos de tus Propias Aplicaciones
# Los modelos de plantilla y contratos ya no se consultan aquí: los informes leen
# de `fuentes.py`, que es quien decide si sirve datos vivos o un cierre mensual.
from cierres.periodos import Periodo
from configuracion.models import Configuracion
from nomencladores.models import (NTipoFamilia, NFamiliaCargo, NCargo,
                                  color_de_categoria)
from strorganizativa.jerarquia import ordenar_con_jerarquia
from strorganizativa.models import UnidadOrganizativa
from usuarios.mixins import RequiereEdicionMixin
from . import fuentes
from .models import PlanMensualRegistro


def _combo_unidades(usuario):
    """Unidades que alimentan el selector de unidad de los informes.

    Se leen siempre de los datos vivos, también en modo histórico: es un control
    de navegación, no un dato del informe.

    Se ofrecen las principales Y sus subunidades. Antes solo salían las raíces,
    con el razonamiento de que elegir una principal ya arrastra a sus hijas
    (`expandir_unidades`) y ofrecerlas todas sería redundante. Pero eso deja
    fuera una pregunta legítima y frecuente: «¿cómo va SOLO este taller?».
    Ahora se puede lo uno y lo otro — el total de la principal eligiéndola a
    ella, o el de una subunidad concreta eligiéndola a ella—, que es justo la
    diferencia entre un filtro jerárquico y uno plano.

    Cada fila lleva `nivel` (0 raíz, 1 subunidad) para que la plantilla las
    pueda indentar: sin esa pista visual, «Camagüey» y «Oficina Central»
    parecerían dos unidades hermanas.

    El Moderador ve exactamente las que tiene asignadas —que, por el invariante
    de `usuarios/forms.py`, ya incluyen las subunidades de sus principales—.

    Esto es comodidad, no seguridad: quien decide lo que cada usuario puede ver
    es `fuentes.resolver_fuente()`, en el servidor.
    """
    permitidas = fuentes.unidades_visibles(usuario)
    consulta = UnidadOrganizativa.objects.select_related('tipo', 'padre')
    if permitidas is not None:
        consulta = consulta.filter(pk__in=permitidas)
    return ordenar_con_jerarquia(consulta)


MESES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
            'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _nombre_del_alcance(request, por_defecto='Empresa Eléctrica Camagüey'):
    """Texto que identifica el alcance del informe en un documento exportado.

    Con el filtro de unidad convertido en selector múltiple, el encabezado de un
    Word o un PDF ya no puede ser el nombre de una sola unidad. Sin nada elegido
    se mantiene el nombre de la empresa, que es lo que ponía antes.
    """
    ids = [valor for valor in request.GET.getlist('ueb') if valor]
    if not ids:
        return por_defecto
    nombres = list(UnidadOrganizativa.objects
                   .filter(pk__in=ids)
                   .order_by('orden_informe')
                   .values_list('descripcion', flat=True))
    return ', '.join(nombres) if nombres else por_defecto


# Cuantas unidades se nombran en la cabecera que se repite en CADA pagina antes
# de resumirlas con «y N mas». La lista completa se imprime una sola vez, al
# principio del documento: una cabecera que crece con el numero de unidades le
# robaria media hoja a la tabla en todas las paginas.
UNIDADES_EN_CABECERA = 2


def _cabecera_documento(request):
    """Datos de identificacion que encabezan un informe exportado.

    Un documento impreso tiene que decir por si solo de que empresa, de que
    territorio y de quien es. Se arma una sola vez y la usan por igual la
    pantalla, el Word y el PDF, para que los tres digan lo mismo.

    La provincia sale SIEMPRE de Parametros Generales. El municipio solo cuando
    el informe va de UNA unidad concreta, porque es el unico caso en que hay un
    municipio que sea el del informe; con varias, el dato seria enganoso.

    Quien exporta se identifica con el nombre del trabajador vinculado a su
    cuenta —el mismo que se ve en su perfil—, sea del rol que sea. Si la cuenta
    no tiene contrato vinculado se cae al nombre de usuario: es preferible a
    dejar el hueco en blanco en un documento que se archiva.
    """
    from configuracion.models import Configuracion

    config = Configuracion.objects.select_related('provincia_entidad').first()

    ids = [valor for valor in request.GET.getlist('ueb')
           if valor and str(valor).isdigit()]
    unidades = list(UnidadOrganizativa.objects
                    .filter(pk__in=ids)
                    .select_related('municipio')
                    .order_by('orden_informe', 'descripcion'))
    nombres = [u.descripcion for u in unidades]

    if len(nombres) <= UNIDADES_EN_CABECERA:
        resumen = ', '.join(nombres)
    else:
        resumen = '%s y %d más' % (
            ', '.join(nombres[:UNIDADES_EN_CABECERA]),
            len(nombres) - UNIDADES_EN_CABECERA)

    usuario = request.user
    quien = (getattr(usuario, 'nombre_completo', None)
             or getattr(usuario, 'username', '') or '')

    # Fecha y hora de la exportación, en español. `strftime('%B')` devolvería el
    # mes en el idioma del servidor, que aquí es inglés.
    ahora = datetime.now()
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    fecha_es = (f"{dias[ahora.weekday()]}, {ahora.day:02d} de "
                f"{MESES_ES[ahora.month - 1]} de {ahora.year} | "
                f"{ahora.strftime('%I:%M %p')}")

    return {
        'config': config,
        'nombre_empresa': config.nombre_empresa if config else 'Empresa Eléctrica',
        'cab_provincia': (config.provincia_entidad.nombre
                          if config and config.provincia_entidad_id else ''),
        # Solo con UNA unidad: es el unico caso en que el informe tiene municipio.
        'cab_municipio': (unidades[0].municipio.nombre
                          if len(unidades) == 1 and unidades[0].municipio_id else ''),
        'cab_unidades': nombres,
        'cab_unidades_resumen': resumen or 'Todas las unidades',
        # `True` cuando hay mas unidades de las que caben arriba: la plantilla
        # imprime entonces la lista entera al principio del documento.
        'cab_lista_aparte': len(nombres) > UNIDADES_EN_CABECERA,
        'cab_exportado_por': quien,
        'fecha_generacion': fecha_es,
    }


# Create your views here.
class InformeEconomiaView(TemplateView):

    def get_template_names(self):
        if self.request.htmx:
            return ['pages/informes/partials/tabla_consolidado.html']
        return ['pages/informes/consolidado_ftrabajo.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # La fuente decide si esto sale de la base de datos viva o de un cierre.
        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        from datetime import date
        hoy = date.today()
        context['mes_actual'] = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        context['anno_actual'] = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        # `ueb_actual` (las unidades marcadas) lo trae ya `contexto_fuente`.
        context['unidades'] = _combo_unidades(self.request.user)

        context['datos_tabla'], context['totales'] = self.calcular_consolidado(fuente)

        return context


    def mapear_categoria(self, codigo):
        mapa = {'OPE': 'Obreros', 'TEC': 'Técnico', 'CDI': 'Cuadro', 'CEJ': 'Cuadro', 'SER': 'Servicio', 'ADM': 'Administrativo'}
        return mapa.get(codigo, 'Obreros')

    def calcular_consolidado(self, fuente):
        datos = {
            'Obreros': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Técnico': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Cuadro': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Servicio': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
            'Administrativo': {'aprob':0, 'cub':0, 'vac':0, 'p_muj':0, 'd_tot':0, 'd_muj':0, 'a_tot':0, 'a_muj':0},
        }

        # Cargos Aprobados, Cubiertos y Vacantes
        for cargo in fuente.cargos:
            if not cargo.activo:
                continue
            cat = self.mapear_categoria(cargo.cat_ocupacional)
            datos[cat]['aprob'] += cargo.cant_aprobada
            datos[cat]['cub'] += cargo.cant_cubierta
            datos[cat]['vac'] += cargo.vacantes

        # Contratos, para sacar las mujeres, determinados y adiestrados
        for c in fuente.contratos:
            # Protegemos el código asegurándonos de que tenga cargo y tipo asignado
            if not c.ncargo_id or not c.tipo_descripcion: continue
            cat = self.mapear_categoria(c.cat_ocupacional)
            mujer = c.es_mujer

            # Convertimos el nombre del nomenclador a mayúsculas para buscar las palabras clave
            desc_tipo = c.tipo_descripcion.upper()

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
        # El documento sale de la misma fuente que la pantalla: si se está viendo
        # un cierre, lo que se exporta es ese cierre, no los datos de hoy.
        fuente, _ = fuentes.resolver_fuente(request)
        hoy = date.today()
        mes = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        anno = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        datos, totales = self.calcular_consolidado(fuente)

        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'informes_economia', 'consolidado_template.docx')
        doc = DocxTemplate(template_path)
        
        nombre_ueb = _nombre_del_alcance(request)

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
        fuente, _ = fuentes.resolver_fuente(request)
        hoy = date.today()
        mes = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        anno = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        # Usamos tu misma matemática exacta
        datos, totales = self.calcular_consolidado(fuente)

        nombre_ueb = _nombre_del_alcance(request)

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

        # Compara las unidades entre sí. Con el filtro múltiple sigue teniendo
        # sentido acotarlo ("compara estas tres"), y sin nada elegido se comporta
        # igual que siempre: todas las que el usuario puede ver.
        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        hoy = date.today()
        context['mes_actual'] = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        context['anno_actual'] = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        # Llamada correcta al método de la clase
        datos_uebs, total_general, total_mujeres = self.calcular_resumen_uebs(fuente)

        context['datos_uebs'] = datos_uebs
        context['total_general'] = total_general
        context['total_mujeres'] = total_mujeres
        context.update(self._cifras_de_cabecera(
            datos_uebs, total_general, total_mujeres))
        context['unidades'] = _combo_unidades(self.request.user)
        context.update(_cabecera_documento(self.request))

        return context


    def calcular_resumen_uebs(self, fuente):
        """Una fila por unidad raíz, sumando las de sus subunidades.

        En modo histórico la jerarquía es la que se congeló en el cierre, no la
        de hoy: si una subunidad cambió de padre en octubre, el informe de agosto
        la sigue contando donde estaba en agosto.
        """
        raices = sorted(
            (u for u in fuente.unidades.values() if not u.padre_id),
            key=lambda u: u.orden)

        datos_uebs = []
        total_general = 0; total_mujeres = 0

        for ueb in raices:
            unidades_ids = {ueb.id}
            if ueb.es_principal:
                unidades_ids |= {u.id for u in fuente.unidades.values()
                                 if u.padre_id == ueb.id}

            contratos_ueb = [c for c in fuente.contratos if c.unidad_id in unidades_ids]

            total_ueb = len(contratos_ueb)
            mujeres_ueb = sum(1 for c in contratos_ueb if c.es_mujer)

            datos_uebs.append({
                'nombre': ueb.descripcion,
                'es_principal': ueb.es_principal,
                'es_subunidad': ueb.es_subunidad,
                'total': total_ueb,
                'mujeres': mujeres_ueb,
                # Se rellena abajo: hasta no recorrerlas todas no se sabe el total.
                'porciento': 0,
            })
            total_general += total_ueb; total_mujeres += mujeres_ueb

        # Peso de cada unidad sobre la plantilla de la empresa. Es lo que
        # convierte la tabla en una comparación y no en una lista de números.
        for fila in datos_uebs:
            fila['porciento'] = (round(fila['total'] * 100 / total_general, 1)
                                 if total_general else 0)

        return datos_uebs, total_general, total_mujeres

    def _cifras_de_cabecera(self, datos_uebs, total_general, total_mujeres):
        """Las cuatro cifras que encabezan el informe.

        Se calculan aquí, y no en la plantilla, porque las comparten la
        pantalla, el Word y el PDF: en la plantilla habría que repetir la misma
        división tres veces y arriesgarse a que una se quede atrás.
        """
        con_personal = [d for d in datos_uebs if d['total']]
        mayor = max(con_personal, key=lambda d: d['total']) if con_personal else None
        return {
            'porciento_mujeres': (round(total_mujeres * 100 / total_general, 1)
                                  if total_general else 0),
            'unidades_con_personal': len(con_personal),
            'unidad_mayor': mayor,
        }


class ExportarResumenUEBWordView(InformeTrabajadoresUEBView):
    def get(self, request, *args, **kwargs):
        fuente, _ = fuentes.resolver_fuente(request)
        hoy = date.today()
        mes = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        anno = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        # Calculamos los datos
        datos_uebs, total_general, total_mujeres = self.calcular_resumen_uebs(fuente)

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


class ExportarResumenUEBPDFView(InformeTrabajadoresUEBView):
    """El mismo informe en PDF.

    Hereda de la vista de pantalla, así que las cifras salen del mismo cálculo:
    no hay forma de que el papel diga una cosa y el navegador otra.
    """

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        html = get_template('pages/reportes/resumen_ueb_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Trabajadores_UEB'))

        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response
    

# --- NUEVO INFORME: PUESTOS CLAVES ---

# Como se organiza el informe de Puestos Clave. Lo elige el usuario con el
# selector de la barra de filtros:
#
#   'desglosado'   Familia -> Unidad Organizativa -> cargos. Es el modelo
#                  oficial: cada unidad encabeza con sus totales y debajo van
#                  sus cargos. Una unidad principal encabeza en letra mayor con
#                  la suma de sus subunidades, y cada subunidad lleva la suya.
#   'consolidado'  Familia -> cargos, sumando cada cargo de TODAS las unidades.
#                  Responde a «cuantas plazas de Liniero hay en la empresa».
#
# La eleccion se guarda en la sesion, asi que sobrevive a ir a otro informe y
# volver, y se olvida al cerrar el navegador. Las tres salidas —pantalla, Word y
# PDF— leen la misma estructura: en modo consolidado se construye una unica
# «unidad» sin nombre y las plantillas no le pintan cabecera, de modo que hay un
# solo camino de codigo en vez de dos que se puedan desincronizar.
AGRUPACIONES = ('desglosado', 'consolidado')
AGRUPACION_POR_DEFECTO = 'consolidado'
CLAVE_AGRUPACION = 'puestos_clave_agrupacion'


def _agrupacion_elegida(request, clave, por_defecto=AGRUPACION_POR_DEFECTO):
    """El modo de agrupación de un informe: el del filtro, o el recordado.

    Lo usan Puestos Clave y Contratos Determinados, cada uno con su `clave` de
    sesión: son informes distintos y cada uno recuerda lo suyo. Guardarlo en la
    sesión de Django, y no en el navegador, evita la doble carga de leerlo con
    JavaScript y volver a pedir la página.
    """
    elegida = request.GET.get('agrupar')
    if elegida in AGRUPACIONES:
        request.session[clave] = elegida
        return elegida
    return request.session.get(clave, por_defecto)


class InformePuestosClaveView(TemplateView):
    template_name = 'pages/informes/informe_puestos_clave.html'

    def _resumen_de_ncargo(self, fuente, ncargo_id, nombre_alternativo='',
                           unidades_ids=None):
        """Cifras de un nomenclador de cargo dentro de la fuente, o None si no tiene
        ninguna plaza activa (el informe lo omite, igual que antes).

        Con `unidades_ids` las cifras se acotan a esas unidades, que es lo que
        permite que el mismo cargo aparezca una vez por unidad con los numeros
        de cada una. Sin ellas se suma todo, como antes.
        """
        def de_mi_alcance(fila):
            return unidades_ids is None or fila.unidad_id in unidades_ids

        cargos = [c for c in fuente.cargos
                  if c.ncargo_id == ncargo_id and c.activo and de_mi_alcance(c)]
        if not cargos:
            return None

        aprob = sum(c.cant_aprobada for c in cargos)
        cub = sum(c.cant_cubierta for c in cargos)
        vac = max(aprob - cub, 0)

        # Mismo filtro que la consulta original: contratos de cargos activos y de
        # aspirantes en ACTIVO.
        contratos = [c for c in fuente.contratos
                     if c.ncargo_id == ncargo_id and c.cargo_activo
                     and c.aspirante_estado == 'ACTIVO' and de_mi_alcance(c)]

        c_det = c_muj = c_adiest = 0
        for c in contratos:
            desc_tipo = (c.tipo_descripcion or '').upper()
            if c.es_mujer:
                c_muj += 1
            if "INDETERMINADO" in desc_tipo:
                continue
            elif "DETERMINADO" in desc_tipo:
                c_det += 1
            elif "ADIESTRAMIENTO" in desc_tipo:
                c_adiest += 1

        return {
            'codigo': ncargo_id,
            'nombre': nombre_alternativo or cargos[0].ncargo_descripcion,
            'aprob': aprob, 'cub': cub, 'vac': vac,
            'porc': int((cub / aprob * 100)) if aprob > 0 else 0,
            'det': c_det, 'muj': c_muj, 'adiest': c_adiest,
        }

    def _acumular(self, f_stats, puesto):
        for origen, destino in (('aprob', 'aprob'), ('cub', 'cub'), ('vac', 'vac'),
                                ('det', 'det'), ('muj', 'muj'), ('adiest', 'adiest')):
            f_stats[destino] += puesto[origen]

    # ------------------------------------------------------------------
    # AGRUPACIÓN POR UNIDAD ORGANIZATIVA
    # ------------------------------------------------------------------
    # El informe oficial no lista los cargos en una sola tabla: los reparte por
    # unidad, cada una con su cabecera y sus totales. Y una unidad principal
    # encabeza toda su rama, con las subunidades debajo.
    #
    # Se construye a partir de `fuente.cargos`, que ya trae `unidad_id` en cada
    # fila, así que la fotografía de un mes cerrado se agrupa por las unidades
    # que EXISTÍAN entonces, no por las de hoy.
    # ------------------------------------------------------------------

    def _nodo_de_unidad(self, unidad_id, fuente, ncargos):
        """Una unidad con sus cargos y sus totales, o None si no tiene ninguno.

        Las unidades sin puestos clave se omiten del informe, igual que en el
        modelo oficial: una cabecera con tres ceros no dice nada que no diga su
        ausencia.
        """
        puestos = []
        totales = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}

        for ncargo_id, nombre in ncargos:
            puesto = self._resumen_de_ncargo(
                fuente, ncargo_id, nombre_alternativo=nombre,
                unidades_ids={unidad_id})
            if puesto is None:
                continue
            puestos.append(puesto)
            self._acumular(totales, puesto)

        if not puestos:
            return None

        totales['porc'] = int(totales['cub'] / totales['aprob'] * 100) if totales['aprob'] else 0
        fila = fuente.unidades.get(unidad_id)
        return {
            'id': unidad_id,
            'nombre': fila.descripcion if fila else '',
            'orden': (fila.orden if fila and fila.orden is not None else 9999),
            'es_padre': False,
            'subtotales': totales,
            'puestos': puestos,
            'subunidades': [],
        }

    def _agrupar_por_unidad(self, fuente, ncargos, alcance=None):
        """Los cargos de una familia, repartidos por unidad y por rama.

        Devuelve una lista de nodos de primer nivel. Un nodo con `subunidades`
        es una unidad principal: sus totales son los suyos MÁS los de sus hijas,
        que es lo que se espera al leer «Dirección Técnica: 57 plazas».

        Una subunidad cuya principal queda FUERA del alcance del informe sube a
        primer nivel. No es un detalle estetico: si el informe solo cubre el
        Taller, encabezar con «Oficina Central» y sus 6 plazas diria que esa es
        toda la direccion, cuando en realidad tiene 10. La principal solo
        encabeza cuando el informe la abarca entera.

        `alcance` es la lista de unidades que cubre el informe, o `None` para la
        empresa completa (ver `informes.fuentes.resolver_fuente`).
        """
        def esta_en_el_informe(unidad_id):
            return alcance is None or unidad_id in alcance

        con_contenido = {}
        for unidad_id in {c.unidad_id for c in fuente.cargos if c.activo}:
            nodo = self._nodo_de_unidad(unidad_id, fuente, ncargos)
            if nodo is not None:
                con_contenido[unidad_id] = nodo

        raices = {}
        for unidad_id, nodo in con_contenido.items():
            fila = fuente.unidades.get(unidad_id)
            padre_id = fila.padre_id if fila else None

            if (padre_id is None or padre_id not in fuente.unidades
                    or not esta_en_el_informe(padre_id)):
                raices[unidad_id] = nodo
                continue

            # La principal encabeza la rama aunque ella misma no tenga cargos
            # (lo normal: todo cuelga de sus hijas), así que se crea vacía.
            padre = raices.get(padre_id)
            if padre is None:
                padre = con_contenido.get(padre_id)
                if padre is None:
                    fila_padre = fuente.unidades[padre_id]
                    padre = {
                        'id': padre_id,
                        'nombre': fila_padre.descripcion,
                        'orden': (fila_padre.orden
                                  if fila_padre.orden is not None else 9999),
                        'es_padre': True,
                        'subtotales': {'aprob': 0, 'cub': 0, 'vac': 0,
                                       'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0},
                        'puestos': [],
                        'subunidades': [],
                    }
                raices[padre_id] = padre
            padre['es_padre'] = True
            padre['subunidades'].append(nodo)

        # Totales de la rama y orden final. Se ordena por `orden_informe` —la
        # posición en el organigrama—, que es el criterio de todos los informes
        # del proyecto; el alfabético dejaría a las unidades en un orden que no
        # es el que la empresa reconoce.
        for nodo in raices.values():
            if not nodo['subunidades']:
                continue
            nodo['subunidades'].sort(key=lambda n: (n['orden'], n['nombre']))
            for hija in nodo['subunidades']:
                for clave in ('aprob', 'cub', 'vac', 'det', 'muj', 'adiest'):
                    nodo['subtotales'][clave] += hija['subtotales'][clave]
            aprob = nodo['subtotales']['aprob']
            nodo['subtotales']['porc'] = (
                int(nodo['subtotales']['cub'] / aprob * 100) if aprob else 0)

        return sorted(raices.values(), key=lambda n: (n['orden'], n['nombre']))

    def _familia(self, fuente, nombre, ncargos, alcance=None,
                 agrupacion=AGRUPACION_POR_DEFECTO):
        """Un bloque del informe: la familia, sus unidades y sus subtotales.

        Devuelve None si la familia no tiene ni un cargo con plazas, para que no
        aparezca un epígrafe vacío.
        """
        if agrupacion == 'desglosado':
            unidades = self._agrupar_por_unidad(fuente, ncargos, alcance)
        else:
            unidades = self._sin_agrupar(fuente, ncargos)

        if not unidades:
            return None

        # Solo se suman los nodos de primer nivel: los totales de una principal
        # YA incluyen a sus hijas, y volver a sumarlas duplicaría la rama entera.
        subtotales = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}
        for nodo in unidades:
            for clave in ('aprob', 'cub', 'vac', 'det', 'muj', 'adiest'):
                subtotales[clave] += nodo['subtotales'][clave]
        subtotales['porc'] = (
            int(subtotales['cub'] / subtotales['aprob'] * 100)
            if subtotales['aprob'] else 0)

        return {'nombre': nombre, 'unidades': unidades, 'subtotales': subtotales}

    def _sin_agrupar(self, fuente, ncargos):
        """Modo consolidado: todos los cargos juntos, sumando todas las unidades.

        Se devuelve con la misma forma que el modo desglosado —una lista con un
        solo nodo, sin nombre— para que las plantillas no necesiten saber en qué
        modo está el informe. Sin nombre, no pintan cabecera de unidad.
        """
        puestos = []
        totales = {'aprob': 0, 'cub': 0, 'vac': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porc': 0}
        for ncargo_id, nombre_cargo in ncargos:
            puesto = self._resumen_de_ncargo(
                fuente, ncargo_id, nombre_alternativo=nombre_cargo)
            if puesto is None:
                continue
            puestos.append(puesto)
            self._acumular(totales, puesto)

        if not puestos:
            return []

        totales['porc'] = int(totales['cub'] / totales['aprob'] * 100) if totales['aprob'] else 0
        return [{
            'id': None, 'nombre': '', 'orden': 0, 'es_padre': False,
            'subtotales': totales, 'puestos': puestos, 'subunidades': [],
        }]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        # 1. Filtros. Las unidades marcadas (`ueb_actual`) las trae ya
        # `contexto_fuente`, que además es quien las cruza con el alcance del rol.
        tipo_id = self.request.GET.get('tipo_familia', '')
        mes = self.request.GET.get('mes', str(date.today().month))
        anno = self.request.GET.get('anno', str(date.today().year))
        if fuente.periodo:
            mes, anno = str(fuente.periodo.mes), str(fuente.periodo.anno)

        agrupacion = _agrupacion_elegida(self.request, CLAVE_AGRUPACION)

        # 2. Tipos de Familia
        tipos_familia = NTipoFamilia.objects.all().order_by('nombre')
        if not tipo_id:
            tipo_id = 'puestos_clave'

        # 3. Estructuras
        datos_familias = []
        stats = {'aprobada': 0, 'cubierta': 0, 'vacante': 0, 'det': 0, 'muj': 0, 'adiest': 0, 'porcentaje': 0}

        # 4. Los bloques del informe: una familia por epígrafe, y dentro de cada
        #    una las unidades organizativas con sus cargos (ver
        #    AGRUPACIONES, arriba).
        if tipo_id == 'puestos_clave':
            # Los NCargos marcados como Puesto Clave que tienen plazas en la fuente.
            # `puesto_clave` sale de la propia fila, así que en modo histórico se
            # respeta la marca que tenía el cargo entonces, no la de hoy.
            # `.lower()` porque el orden venía de PostgreSQL, que no distingue
            # mayúsculas al ordenar texto; `sorted()` de Python sí, y colocaría
            # todos los cargos en minúscula al final de la lista.
            ncargos = sorted(
                {c.ncargo_id: c.ncargo_descripcion
                 for c in fuente.cargos if c.puesto_clave and c.activo}.items(),
                key=lambda par: (par[1] or '').lower())

            bloque = self._familia(fuente, '⭐ Puestos Clave', ncargos,
                                   contexto_fuente.get('unidades_alcance'),
                                   agrupacion)
            if bloque:
                datos_familias.append(bloque)
        else:
            try:
                tipo_id_int = int(tipo_id)
            except (ValueError, TypeError):
                tipo_id_int = None

            if tipo_id_int:
                familias = (NFamiliaCargo.objects
                            .filter(tipo_familia_id=tipo_id_int)
                            .prefetch_related('cargos'))
                for familia in familias:
                    # Solo las plazas clave dentro de esta familia. La pertenencia
                    # a la familia se lee de los nomencladores vivos también en
                    # modo histórico: es un agrupador global, como el propio
                    # nombre de la familia, no un dato de la unidad.
                    ncargos = [(n.pk, n.descripcion)
                               for n in familia.cargos.all() if n.puesto_clave]
                    bloque = self._familia(
                        fuente, familia.nombre, ncargos,
                        contexto_fuente.get('unidades_alcance'), agrupacion)
                    if bloque:
                        datos_familias.append(bloque)

        for bloque in datos_familias:
            stats['aprobada'] += bloque['subtotales']['aprob']
            stats['cubierta'] += bloque['subtotales']['cub']
            stats['vacante'] += bloque['subtotales']['vac']
            stats['det'] += bloque['subtotales']['det']
            stats['muj'] += bloque['subtotales']['muj']
            stats['adiest'] += bloque['subtotales']['adiest']

        if stats['aprobada'] > 0:
            stats['porcentaje'] = int((stats['cubierta'] / stats['aprobada']) * 100)

        # La fecha de generación la trae `_cabecera_documento`, que es común a
        # todos los informes.
        context.update(_cabecera_documento(self.request))
        context.update({
            'datos_familias': datos_familias,
            'stats': stats,
            'tipos_familia': tipos_familia,
            'tipo_actual': tipo_id,
            # Filtramos el combo para no mostrar las subunidades sueltas, solo contenedores o independientes
            'unidades': _combo_unidades(self.request.user),
            'mes_actual': mes,
            'anno_actual': anno,
            'agrupacion': agrupacion,
        })
        return context


def _logo_para_word(doc, config):
    """El logo de la empresa como imagen incrustada en un .docx.

    Devuelve cadena vacía si no hay logo configurado o si el fichero no se puede
    leer: la etiqueta queda vacía y la cabecera no se descuadra, que es mejor que
    tumbar la exportación por una imagen.
    """
    if not (config and config.logo):
        return ''
    try:
        return InlineImage(doc, config.logo.path, width=Mm(28))
    except Exception:
        return ''


def _nombre_de_fichero(context, extension, informe='Puestos_Clave'):
    """Nombre del documento descargado: informe, alcance y período.

    `Puestos_Clave_Nuevitas_Septiembre_2026.docx` se reconoce de un vistazo en la
    carpeta de descargas; `Puestos_Clave_9_2026.docx`, que es lo que se ponía
    antes, no distingue el informe de una unidad del de la empresa entera.
    """
    partes = [informe]

    unidades = context.get('cab_unidades') or []
    if len(unidades) == 1:
        partes.append(unidades[0])
    elif unidades:
        partes.append('%d_unidades' % len(unidades))

    try:
        partes.append(MESES_ES[int(context.get('mes_actual')) - 1])
    except (TypeError, ValueError, IndexError):
        partes.append(str(context.get('mes_actual') or ''))
    partes.append(str(context.get('anno_actual') or ''))

    limpio = re.sub(r'[^\w\-]+', '_', '_'.join(p for p in partes if p), flags=re.UNICODE)
    return '%s.%s' % (limpio.strip('_'), extension)


class ExportarPuestosClaveWordView(InformePuestosClaveView):
    def get(self, request, *args, **kwargs):
        # La estructura por familia y unidad, la cabecera del documento y las
        # cifras salen todas del contexto de la pantalla: el Word enseña
        # exactamente lo mismo que se está viendo.
        context = self.get_context_data(**kwargs)
        context['ueb'] = _nombre_del_alcance(request)

        # La plantilla NO se edita a mano: la fabrica
        # `plantillas_word/generadores/crear_puestos_clave.py`. Su tabla lleva
        # diez filas que parecen vacías y en realidad son las etiquetas de los
        # bucles de docxtpl; borrar una al retocar el documento en Word deja el
        # informe vacío sin dar ningún error.
        template_path = os.path.join(settings.BASE_DIR, 'plantillas_word', 'informes_economia', 'puestos_clave_template.docx')

        try:
            doc = DocxTemplate(template_path)

            # El logo se inserta como imagen de verdad, no como ruta: docxtpl lo
            # incrusta en el .docx con `InlineImage`.
            context['logo'] = _logo_para_word(doc, context.get('config'))

            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            filename = _nombre_de_fichero(context, 'docx')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarPuestosClavePDFView(InformePuestosClaveView):
    def get(self, request, *args, **kwargs):
        # 1. Obtenemos la data de la vista principal
        context = self.get_context_data(**kwargs)
        
        # El logo, la empresa, la provincia y el resto de la cabecera vienen ya
        # de `_cabecera_documento()`, que comparten las tres salidas.

        # 2. Renderizar PDF
        template = get_template('pages/reportes/puestos_clave_pdf.html')
        html = template.render(context)
        
        response = HttpResponse(content_type='application/pdf')
        filename = _nombre_de_fichero(context, 'pdf')
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

        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        hoy = date.today()
        context['mes_actual'] = str(fuente.periodo.mes) if fuente.periodo else str(hoy.month)
        context['anno_actual'] = str(fuente.periodo.anno) if fuente.periodo else str(hoy.year)

        # 1. Solo los contratos en misión
        contratos = [c for c in fuente.contratos if c.mision]

        # 2. Variables de conteo
        total_misiones = len(contratos)
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
            unidad = fuente.unidad(c.unidad_id)
            ueb_nombre = unidad.descripcion if unidad else "Sin Unidad"
            orden = unidad.orden if unidad else 999

            cat_sigla = c.cat_ocupacional or ""
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
                'nombre': c.aspirante_nombre,
                'cargo': c.ncargo_descripcion or "-",
                'cat_letra': cat_sigla[0] if cat_sigla else "-",
                # El codigo completo, para que la insignia pueda tomar el color
                # de su categoria: con la inicial sola, Cuadro Directivo y
                # Cuadro Ejecutivo serian indistinguibles de «C» de nada.
                'cat_codigo': cat_sigla,
                'g_escala': c.grupo_escala_nivel or "-",
                'pais': c.pais, 'dias': 0, 'importe': 0.00
            })

        # Ordenamos las llaves según el mapa de orden y reconstruimos
        sorted_keys = sorted(orden_map.keys(), key=lambda k: orden_map[k])

        # Una LISTA de unidades, cada una con los suyos, y no un diccionario:
        # es la forma que entienden por igual la plantilla de pantalla, la del
        # PDF y los bucles de docxtpl del Word. Un diccionario obliga a cada una
        # a recorrerlo a su manera.
        misiones_por_unidad = [
            {'nombre': nombre,
             'total': len(datos_por_ueb[nombre]),
             'trabajadores': datos_por_ueb[nombre]}
            for nombre in sorted_keys
        ]

        context['total_misiones'] = total_misiones
        context['importe_total'] = importe_total
        context['desglose'] = desglose
        context['misiones_por_unidad'] = misiones_por_unidad
        context['paises'] = len({c.pais for c in contratos if c.pais})
        context['unidades_con_mision'] = len(misiones_por_unidad)
        context['unidades'] = _combo_unidades(self.request.user)
        context.update(_cabecera_documento(self.request))
        return context
    
class ExportarMisionesWordView(InformeMisionesView):
    """Misiones Internacionales en Word."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        template_path = os.path.join(
            settings.BASE_DIR, 'plantillas_word', 'informes_economia',
            'misiones_template.docx')
        try:
            doc = DocxTemplate(template_path)
            context['logo'] = _logo_para_word(doc, context.get('config'))
            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = (
                'attachment; filename="%s"'
                % _nombre_de_fichero(context, 'docx', 'Misiones'))
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarMisionesPDFView(InformeMisionesView):
    """Misiones Internacionales en PDF."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        html = get_template('pages/reportes/misiones_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Misiones'))
        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response


class RegistroDiarioView(TemplateView):
    template_name = "pages/informes/registro_diario.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from datetime import date

        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        hoy = date.today()
        mes_actual = self.request.GET.get('mes', str(hoy.month))
        anno_actual = self.request.GET.get('anno', str(hoy.year))
        if fuente.periodo:
            mes_actual, anno_actual = str(fuente.periodo.mes), str(fuente.periodo.anno)

        # El Plan Mensual se guarda por (mes, año, UNA unidad, familia): esa clave
        # es anterior al filtro múltiple y no cambia. Con exactamente una unidad
        # marcada se usa la suya; con ninguna o con varias se usa la clave del
        # plan consolidado (''), que es la misma que se usaba antes cuando no
        # había filtro. Así ningún plan ya guardado se queda huérfano.
        marcadas = [valor for valor in self.request.GET.getlist('ueb') if valor]
        ueb_filtro = marcadas[0] if len(marcadas) == 1 else ''
        familia_filtro = self.request.GET.get('tipo_familia', '')

        # 1. Contratos de la fuente (ya acotados a la unidad seleccionada y a sus
        #    subunidades por `resolver_fuente`).
        contratos = fuente.contratos

        if familia_filtro:
            # Antes filtraba por `cargo__ncargo__familia_id`, un campo que NO existe:
            # `NCargo` tiene `familias` (M2M). Cualquier valor en este filtro
            # reventaba con FieldError; no saltaba porque la plantilla nunca lo
            # enviaba. Ahora se resuelve contra las familias congeladas de la fila.
            try:
                familia_id = int(familia_filtro)
            except (TypeError, ValueError):
                familia_id = None
            if familia_id is not None:
                familias_de_ncargo = {
                    c.ncargo_id: c.familias_ids for c in fuente.cargos}
                contratos = [c for c in contratos
                             if familia_id in familias_de_ncargo.get(c.ncargo_id, ())]

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
            cat = c.cat_ocupacional or ""
            es_mujer = c.es_mujer

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

        # El plan manual NO forma parte de la fotografía: es un objetivo de
        # planificación, no un dato observado. Como ya está indexado por
        # (mes, año, ueb, familia), en modo cierre lee de forma natural el plan
        # de ese mismo mes.
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
            # Si no existe, calculamos el de la plantilla de la fuente
            cargos_plan = [c for c in fuente.cargos if c.activo]
            if familia_filtro:
                try:
                    familia_id = int(familia_filtro)
                except (TypeError, ValueError):
                    familia_id = None
                if familia_id is not None:
                    cargos_plan = [c for c in cargos_plan
                                   if familia_id in (c.familias_ids or ())]

            valor_plan = sum(c.cant_aprobada for c in cargos_plan)

        # Enviar al contexto
        context['mes_actual'] = mes_actual
        context['anno_actual'] = anno_actual
        # `ueb_actual` (lo marcado en el selector) lo trae `contexto_fuente`;
        # `ueb_filtro` es solo la clave del plan y no debe pisarlo.
        context['tipo_actual'] = familia_filtro
        context['datos'] = datos
        context['plan_editable'] = valor_plan

        # Cifras de la Eficiencia del Plan, ya resueltas. En pantalla las calcula
        # JavaScript sobre la marcha porque el plan se edita ahí mismo; el Word y
        # el PDF no tienen JavaScript, así que se calculan aquí y las tres
        # salidas dicen lo mismo.
        real = sum(d['tot'] for llave, d in datos.items() if llave != 'Misiones')
        context['plan_real'] = real
        context['plan_diferencia'] = real - valor_plan
        context['plan_cumplimiento'] = (round(real * 100 / valor_plan, 1)
                                        if valor_plan else 0)
        context['total_mujeres'] = sum(
            d['muj'] for llave, d in datos.items() if llave != 'Misiones')

        # Para los combos (Ajusta NFamiliaCargo a tu modelo real)
        context['unidades'] = _combo_unidades(self.request.user)
        context.update(_cabecera_documento(self.request))

        return context


class ExportarRegistroDiarioWordView(RegistroDiarioView):
    """Registro Diario en Word.

    Los gráficos no van: son de JavaScript y no existen fuera del navegador. El
    documento lleva la Eficiencia del Plan y los indicadores, que es el dato que
    se archiva.
    """

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        template_path = os.path.join(
            settings.BASE_DIR, 'plantillas_word', 'informes_economia',
            'registro_diario_template.docx')
        try:
            doc = DocxTemplate(template_path)
            context['logo'] = _logo_para_word(doc, context.get('config'))
            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = (
                'attachment; filename="%s"'
                % _nombre_de_fichero(context, 'docx', 'Registro_Diario'))
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarRegistroDiarioPDFView(RegistroDiarioView):
    """Registro Diario en PDF."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        html = get_template('pages/reportes/registro_diario_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Registro_Diario'))
        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response

# Vista para que JavaScript guarde el plan con Doble Clic sin recargar.
#
# `RequiereEdicionMixin` cierra la escritura al Observador. Es la ÚNICA vista de
# este módulo que escribe: el resto de Informes son de solo lectura, así que sin
# este cierre un usuario de consulta podía grabar el Plan Mensual desde «Registro
# Diario por Trabajadores» pese a que su rol no se lo permite en ninguna otra
# pantalla. Responde JSON, y el mixin también: el doble clic recibe un 403 con
# `error_popup` en vez de una página de error.
class GuardarPlanDiarioView(RequiereEdicionMixin, View):
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
        
# Como se organiza Contratos Determinados. Mismas dos palabras que en Puestos
# Clave —quien aprende el conmutador en un informe lo reconoce en el otro—,
# aunque aqui lo que se desglosa son tres niveles y alli uno:
#
#   'desglosado'   Tipo de contrato -> Motivo -> Unidad -> los contratos, con el
#                  total de cada nivel. Es como se ha visto siempre la pantalla.
#   'consolidado'  Una sola tabla corrida, con el tipo, el motivo y la unidad
#                  como columnas. Sirve para buscar, ordenar y llevarse la lista.
#
# Arranca DESGLOSADO, que es lo que esta pantalla ya hacia: el conmutador solo
# añade la posibilidad de verla corrida.
CLAVE_AGRUPACION_MOTIVOS = 'motivos_agrupacion'


class InformeMotivosContratoView(TemplateView):
    template_name = "pages/informes/informe_motivos_contrato.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()

        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        # Mismo criterio que la consulta original: solo aspirantes en ACTIVO y
        # tipos de contrato que exigen motivo. La cascada por unidad ya la aplicó
        # `resolver_fuente`.
        contratos = [c for c in fuente.contratos
                     if c.aspirante_estado == 'ACTIVO' and c.requiere_motivo]

        # 2. ORDENAR POR ORDEN_INFORME EN VEZ DE DESCRIPCIÓN.
        #    El desempate final era `aspirante__nombre` (solo el nombre de pila);
        #    aquí se usa el nombre completo, que ordena igual y además desempata
        #    entre homónimos en vez de dejarlo al azar.
        contratos.sort(key=lambda c: (
            c.tipo_descripcion or '',
            c.motivo_descripcion or '',
            (fuente.unidad(c.unidad_id).orden if fuente.unidad(c.unidad_id) else 999),
            c.aspirante_nombre or '',
        ))

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
            
            if c.sexo == 'F': total_mujeres += 1
            elif c.sexo == 'M': total_hombres += 1

            cat = c.cat_ocupacional or None
            if cat == 'TEC': cat_t += 1
            elif cat == 'OPE': cat_o += 1
            elif cat == 'SER': cat_s += 1
            elif cat == 'ADM': cat_a += 1
            elif cat in ['CDI', 'CEJ']: cat_c += 1

            if c.dias_restantes is not None:
                if c.dias_restantes <= 15: vencen_critico += 1
                elif c.dias_restantes <= 30: vencen_alerta += 1
                else: vencen_vigente += 1

            tipo_desc = c.tipo_descripcion or "Sin Tipo Asignado"
            motivo_desc = c.motivo_descripcion or "Sin Motivo Asignado"

            ueb_obj = fuente.unidad(c.unidad_id)
            ueb_desc = ueb_obj.descripcion if ueb_obj else "Sin Unidad Organizativa"
            ueb_color = ueb_obj.color if ueb_obj else "#697a8d"

            # 3. EXTRAER LAS BANDERAS PARA EL HTML
            es_p = ueb_obj.es_principal if ueb_obj else False
            es_s = ueb_obj.es_subunidad if ueb_obj else False
            
            conteo_motivos[motivo_desc] = conteo_motivos.get(motivo_desc, 0) + 1
            
            if tipo_desc not in datos_agrupados:
                datos_agrupados[tipo_desc] = {'total': 0, 'motivos': {}}
            datos_agrupados[tipo_desc]['total'] += 1

            if motivo_desc not in datos_agrupados[tipo_desc]['motivos']:
                # `uebs` reparte por unidad —el modo desglosado— y `contratos`
                # los guarda todos juntos, que es el modo consolidado: mismo
                # agrupamiento por tipo y motivo, sin el nivel de la unidad.
                # Son dos índices de los MISMOS contratos, no dos copias.
                datos_agrupados[tipo_desc]['motivos'][motivo_desc] = {
                    'total': 0, 'uebs': {}, 'contratos': []}
            datos_agrupados[tipo_desc]['motivos'][motivo_desc]['total'] += 1
            # La unidad viaja con el contrato porque en consolidado deja de ser
            # una cabecera y pasa a ser una columna. `FilaContrato` es inmutable,
            # así que no se le puede colgar el nombre encima.
            datos_agrupados[tipo_desc]['motivos'][motivo_desc]['contratos'].append(
                {'contrato': c, 'unidad': ueb_desc, 'color': ueb_color})

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

        # El color sale de la CATEGORÍA, no del puesto que ocupe en el ranking.
        # Antes se repartía una escala por orden de tamaño, así que la misma
        # categoría cambiaba de color según los datos: Obreros era rojo un mes y
        # verde al siguiente, y el color dejaba de significar nada.
        lista_categorias = [
            {'nombre': '[C] Cuadros', 'count': cat_c, 'codigo': 'CDI'},
            {'nombre': '[T] Técnicos', 'count': cat_t, 'codigo': 'TEC'},
            {'nombre': '[A] Administrativos', 'count': cat_a, 'codigo': 'ADM'},
            {'nombre': '[O] Obreros', 'count': cat_o, 'codigo': 'OPE'},
            {'nombre': '[S] Servicios', 'count': cat_s, 'codigo': 'SER'},
        ]
        lista_categorias.sort(key=lambda x: x['count'], reverse=True)

        for item in lista_categorias:
            item['color'] = color_de_categoria(item['codigo'])
            item['porc'] = int((item['count'] / total_contratos * 100)) if total_contratos else 0

        porc_mujeres = round((total_mujeres / total_contratos * 100) if total_contratos else 0, 1)
        porc_hombres = round((total_hombres / total_contratos * 100) if total_contratos else 0, 1)

        context.update(_cabecera_documento(self.request))
        context.update({
            'agrupacion': _agrupacion_elegida(
                self.request, CLAVE_AGRUPACION_MOTIVOS, 'desglosado'),
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
            # `strftime("%B")` devolvía el mes en inglés ("August"), porque depende
            # del locale del servidor. `Periodo` lo da siempre en español.
            'mes_actual': (fuente.periodo or Periodo(hoy.year, hoy.month)).etiqueta.split()[0],
            'anno_actual': fuente.periodo.anno if fuente.periodo else hoy.year,
            # 4. ENVIAR LAS UNIDADES Y EL FILTRO ACTUAL AL TEMPLATE
            'unidades': _combo_unidades(self.request.user),
        })
        
        return context


class ExportarMotivosWordView(InformeMotivosContratoView):
    """Contratos Determinados en Word."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        # Una plantilla por modo. Se podría envolver las dos tablas en un `if`
        # dentro de un solo .docx, pero entonces quien lo abriera para retocar
        # el diseño tendría que adivinar cuál de las dos está viendo.
        plantilla = ('motivos_consolidado_template.docx'
                     if context.get('agrupacion') == 'consolidado'
                     else 'motivos_template.docx')
        template_path = os.path.join(
            settings.BASE_DIR, 'plantillas_word', 'informes_economia', plantilla)
        try:
            doc = DocxTemplate(template_path)
            context['logo'] = _logo_para_word(doc, context.get('config'))
            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = (
                'attachment; filename="%s"'
                % _nombre_de_fichero(context, 'docx', 'Contratos_Determinados'))
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarMotivosPDFView(InformeMotivosContratoView):
    """Contratos Determinados en PDF."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        html = get_template('pages/reportes/motivos_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Contratos_Determinados'))
        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response
