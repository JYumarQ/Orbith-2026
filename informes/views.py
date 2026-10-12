# 1. Librerías Estándar de Python
import json
import os
import calendar
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from usuarios.mixins import RequiereEdicionMixin, puede_editar
from . import altas_bajas
from . import misiones
from . import excel
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

    Quien tiene el alcance acotado —el Moderador, y el Observador con unidades
    asignadas— ve exactamente las que tiene asignadas, que por el invariante de
    `usuarios/forms.py` ya incluyen las subunidades de sus principales.

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


class GuiaInformeRRHHMixin:
    """Marca la tarea `primer_informe_rrhh` de la Guía de Orbith al consultar
    cualquiera de los siete Informes RRHH. Va en `get()` y no en cada
    `get_context_data()` para tocar una sola línea por informe."""

    def get(self, request, *args, **kwargs):
        from progreso.servicios import completar_tarea
        completar_tarea(request.user, 'primer_informe_rrhh')
        # Solo al abrir el informe: los filtros (HTMX) no son otra consulta.
        if not request.htmx:
            from ranking.models import Actividad
            from ranking.servicios import registrar_actividad
            registrar_actividad(request.user, Actividad.INFORME,
                                detalle=f'Informe RRHH: {request.resolver_match.url_name}')
        return super().get(request, *args, **kwargs)


# Create your views here.
class InformeEconomiaView(GuiaInformeRRHHMixin, TemplateView):

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

        datos, totales = self.calcular_consolidado(fuente)
        context['datos_tabla'], context['totales'] = datos, totales

        # `datos`, `mes`, `anno` y `ueb` son los nombres que esperan la plantilla
        # de Word y la del PDF desde antes de que este informe tuviera contexto
        # compartido. Se dejan como alias para que las TRES exportaciones lean
        # de este único sitio en vez de armarse cada una el suyo por su cuenta,
        # que es lo que permitía que se desincronizaran.
        context['datos'] = datos
        context['mes'] = context['mes_actual']
        context['anno'] = context['anno_actual']
        context['ueb'] = _nombre_del_alcance(self.request)
        context['periodo_texto'] = '%s %s' % (
            MESES_ES[int(context['mes_actual']) - 1], context['anno_actual'])

        context['cifras_consolidado'] = self.cifras_de_cabecera(totales)

        # Empresa, provincia, logo, quién exporta y cuándo. Era el único de los
        # siete informes que no los tenía: sus exportaciones a Word y PDF son
        # anteriores a la cabecera común y se armaban su propio contexto aparte.
        context.update(_cabecera_documento(self.request))

        return context

    @staticmethod
    def cifras_de_cabecera(totales):
        """Las cinco cifras que encabezan el documento, como en los otros seis.

        Este informe no tiene tarjetas en pantalla: su tabla termina en una fila
        TOTAL que ya las contiene. Se derivan de ahí —y no de una consulta
        aparte— para que no puedan contradecir a la tabla que llevan encima.

        Ternas (rótulo, valor, pie), el mismo formato que usa `LibroDeInforme`.
        """
        cobertura = (round(totales['cub'] / totales['aprob'] * 100, 1)
                     if totales['aprob'] else 0)
        return [
            ('Total de trabajadores', totales['t_tot'],
             'Plantilla cubierta más contratos'),
            ('Mujeres', totales['t_muj'], 'Del total de trabajadores'),
            ('Plantilla aprobada', totales['aprob'], 'Plazas del organigrama'),
            ('Vacantes', totales['vac'], 'Plazas aprobadas sin cubrir'),
            ('Cobertura', '%s %%' % cobertura, 'Cubiertas sobre aprobadas'),
        ]


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
        # `en_plantilla`: las plazas fuera de la plantilla aprobada no son
        # plantilla, así que no suman aquí. Sus trabajadores sí siguen contando
        # más abajo (existen y cobran), igual que en la prenómina.
        for cargo in fuente.cargos:
            if not cargo.activo or not cargo.en_plantilla:
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
    """Consolidado de la Fuerza de Trabajo en Word.

    Lee el contexto de la pantalla, como las otras seis exportaciones a Word.
    Antes se armaba el suyo llamando a `calcular_consolidado` por su cuenta: la
    misma cuenta hecha en tres sitios, y ninguno de los tres tenía la cabecera
    común, así que el documento salía sin logo ni identificación.
    """

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        template_path = os.path.join(
            settings.BASE_DIR, 'plantillas_word', 'informes_economia',
            'consolidado_template.docx')
        try:
            doc = DocxTemplate(template_path)
            context['logo'] = _logo_para_word(doc, context.get('config'))
            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = (
                'attachment; filename="%s"'
                % _nombre_de_fichero(context, 'docx', 'Consolidado'))
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarConsolidadoPDFView(InformeEconomiaView):
    """Consolidado de la Fuerza de Trabajo en PDF."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        html = get_template('pages/reportes/consolidado_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Consolidado'))
        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response
    

class InformeTrabajadoresUEBView(GuiaInformeRRHHMixin, TemplateView):
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


class InformePuestosClaveView(GuiaInformeRRHHMixin, TemplateView):
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
                  if c.ncargo_id == ncargo_id and c.activo and c.en_plantilla
                  and de_mi_alcance(c)]
        if not cargos:
            return None

        aprob = sum(c.cant_aprobada for c in cargos)
        cub = sum(c.cant_cubierta for c in cargos)
        vac = max(aprob - cub, 0)

        # Mismo filtro que la consulta original: contratos de cargos activos y de
        # aspirantes en ACTIVO.
        #
        # `en_plantilla` es imprescindible aquí, no un extra: los contratos se
        # emparejan por `ncargo_id`, y un mismo NCargo puede existir DOS veces en
        # el departamento (la pareja dentro/fuera de la plantilla aprobada). Sin
        # este filtro, los trabajadores del cargo de fuera se contarían en la fila
        # del de dentro, cuyas plazas sí se excluyeron tres líneas más arriba.
        contratos = [c for c in fuente.contratos
                     if c.ncargo_id == ncargo_id and c.cargo_activo and c.en_plantilla
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
        for unidad_id in {c.unidad_id for c in fuente.cargos
                          if c.activo and c.en_plantilla}:
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
                 for c in fuente.cargos
                 if c.puesto_clave and c.activo and c.en_plantilla}.items(),
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
class InformeMisionesView(GuiaInformeRRHHMixin, TemplateView):
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
                # Del contrato (o de la fotografía del cierre). `None` es «sin
                # registrar»: se pinta como 0, pero no es lo mismo que 0.
                'pais': c.pais, 'dias': c.mision_dias, 'importe': c.mision_importe,
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

        # Una exportación puede llegar con los valores que el usuario retocó en
        # pantalla (ver `ExportarMisionesMixin`). Solo en tiempo real: un cierre
        # es una fotografía y no se edita.
        valores = getattr(self, 'valores_manuales', None)
        context['con_valores_manuales'] = bool(
            valores and not context.get('es_historico')
            and misiones.aplicar_valores_manuales(misiones_por_unidad, valores))
        context['nota_valores_manuales'] = misiones.NOTA_VALORES_MANUALES

        # Doble clic, «Guardar» y «Restablecer»: quien puede editar, y solo con
        # los datos de hoy.
        context['mision_editable'] = (
            puede_editar(self.request.user) and not context.get('es_historico'))

        context['total_misiones'] = total_misiones
        context['importe_total'] = misiones.importe_total(misiones_por_unidad)
        context['desglose'] = desglose
        context['misiones_por_unidad'] = misiones_por_unidad
        context['paises'] = len({c.pais for c in contratos if c.pais})
        context['unidades_con_mision'] = len(misiones_por_unidad)
        context['unidades'] = _combo_unidades(self.request.user)
        context.update(_cabecera_documento(self.request))
        return context
    
class ExportarMisionesMixin:
    """Las exportaciones de Misiones aceptan también POST con los valores de la
    pantalla.

    Por GET (como siempre) el documento sale con lo que hay en la base de datos.
    Por POST lleva en `valores` los Días e Importe que el usuario editó sin
    guardar, y el documento sale con ellos y una nota al pie. Los filtros
    siguen viajando en la URL, así que el resto del informe no cambia.
    """

    def post(self, request, *args, **kwargs):
        try:
            datos = json.loads(request.POST.get('valores') or '{}')
        except ValueError:
            datos = {}
        self.valores_manuales = misiones.leer_valores_manuales(datos)
        return self.get(request, *args, **kwargs)


class GuardarMisionesView(RequiereEdicionMixin, View):
    """«Guardar» del informe: escribe Días e Importe en los contratos.

    Todo o nada; los motivos de un rechazo vuelven en `errores`, uno por
    trabajador. La lógica vive en `informes/misiones.py::guardar_cambios`.
    """

    def post(self, request, *args, **kwargs):
        try:
            datos = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse(
                {'ok': False, 'mensaje': 'La petición no es válida.'}, status=400)
        try:
            guardados = misiones.guardar_cambios(request.user, datos.get('cambios'))
        except misiones.ErrorDeGuardado as error:
            return JsonResponse({'ok': False, 'mensaje': str(error),
                                 'errores': error.errores,
                                 'actuales': error.actuales}, status=409)
        return JsonResponse({'ok': True, 'guardados': guardados})


class ExportarMisionesWordView(ExportarMisionesMixin, InformeMisionesView):
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


class ExportarMisionesPDFView(ExportarMisionesMixin, InformeMisionesView):
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


class RegistroDiarioView(GuiaInformeRRHHMixin, TemplateView):
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
            cargos_plan = [c for c in fuente.cargos if c.activo and c.en_plantilla]
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


class InformeMotivosContratoView(GuiaInformeRRHHMixin, TemplateView):
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


# ---------------------------------------------------------------------------
# INFORME: ALTAS Y BAJAS DEL MES (modelo de la UNE)
# ---------------------------------------------------------------------------

class InformeAltasBajasView(GuiaInformeRRHHMixin, TemplateView):
    """Quien entro y quien salio en un mes, en el formato que pide la UNE.

    Es el unico informe de RRHH que NO lee de `fuentes.FuenteDatos`. Los otros
    seis son fotografias —cuantos hay hoy, o cuantos habia al cerrar agosto— y
    por eso pueden servirse de un cierre mensual. Este es de movimientos: pregunta
    quien cruzo la puerta entre dos fechas, y un cierre no sabe responder eso.
    El detalle esta explicado en `informes/altas_bajas.py`.

    Del selector de periodo de la barra superior solo se toma el mes y el anno,
    no la fotografia: elegir «cierre de agosto» equivale aqui a «movimientos de
    agosto».
    """

    template_name = "pages/informes/informe_altas_bajas.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Se llama aunque no se use su lista de contratos: es quien alimenta el
        # selector de periodo de la barra comun.
        fuente, contexto_fuente = fuentes.resolver_fuente(self.request)
        context.update(contexto_fuente)

        anno, mes = self._periodo(fuente)
        unidades_ids = altas_bajas.unidades_pedidas(self.request)

        altas = altas_bajas.altas_del_mes(anno, mes, unidades_ids)
        bajas = altas_bajas.bajas_del_mes(anno, mes, unidades_ids)

        claves = altas_bajas.meses_con_movimiento(unidades_ids)
        # Se arma UNA vez: consulta la configuración y las unidades, y este
        # contexto la necesita dos veces (la cabecera y el municipio del resumen).
        cabecera = _cabecera_documento(self.request)

        context.update({
            'mes_actual': str(mes),
            'anno_actual': str(anno),
            'mes_nombre': MESES_ES[mes - 1],
            'periodo_texto': '%s %d' % (MESES_ES[mes - 1], anno),

            'altas': altas,
            'bajas': bajas,
            'resumen_altas': altas_bajas.resumen(altas),
            'resumen_bajas': altas_bajas.resumen(bajas),

            # Con signo siempre, tambien cuando el saldo es positivo: «+4» se lee
            # como una ganancia de plantilla, y «4» a secas no dice nada.
            'saldo_texto': '%+d' % (len(altas) - len(bajas)),

            # Municipio de la fila de resumen. Solo hay UNO cuando el informe va
            # de una sola unidad; con varias, ninguno seria «el» municipio del
            # informe, asi que se escribe la marca de hueco. Es la misma regla
            # que sigue la cabecera del documento desde Puestos Clave.
            'municipio_resumen': (cabecera['cab_municipio']
                                  or altas_bajas.SIN_MUNICIPIO),

            # El selector de período de la barra común manda también aquí. En
            # los otros seis elige QUÉ FOTOGRAFÍA mirar (información actual o el
            # cierre de un mes) y solo ofrece meses con cierre declarado; en
            # este elige el MES DE LOS MOVIMIENTOS, y por eso:
            #   - `modo=todos`: cualquier mes vale, este informe no lee cierres;
            #   - los meses resaltados son los que tuvieron altas o bajas, no
            #     los que tienen cierre;
            #   - no hay opción de «volver a la información actual», porque un
            #     informe de movimientos siempre necesita un mes.
            'periodo_de_movimientos': True,
            'periodos_claves': claves,
            'periodos_annos': altas_bajas.annos_con_movimiento(claves, anno),
            'periodo_anno': anno,
            'periodo_mes': mes,

            # Este informe nunca lee un cierre, así que jamás es «histórico».
            # Si se llega desde otro informe con `?fuente=cierre` en la URL, se
            # aprovecha su mes pero no se hereda el aviso de fotografía.
            'es_historico': False,
            'unidades_sin_cierre': [],

            'unidades': _combo_unidades(self.request.user),
        })
        context.update(cabecera)
        return context

    def _periodo(self, fuente):
        """El mes del informe, con el MES ANTERIOR por defecto.

        El mes anterior y no el corriente porque este es el informe que se envía
        a la UNE, y lo que se envía es un mes completo: a día 3 de septiembre lo
        que hace falta es agosto entero, no los tres días que van de septiembre.
        Abrir en el mes en curso enseñaría un total a medio hacer con toda la
        apariencia de estar terminado.

        Cualquier valor imposible cae a ese mismo mes por defecto en vez de
        reventar: la vista se alcanza escribiendo la URL a mano, y `?mes=99` no
        debe devolver un error 500.
        """
        hoy = date.today()
        anterior = date(hoy.year, hoy.month, 1) - timedelta(days=1)
        defecto = (anterior.year, anterior.month)

        if fuente.periodo:
            return fuente.periodo.anno, fuente.periodo.mes
        try:
            mes = int(self.request.GET.get('mes') or defecto[1])
            anno = int(self.request.GET.get('anno') or defecto[0])
        except (TypeError, ValueError):
            return defecto
        if not 1 <= mes <= 12 or not 1900 <= anno <= 2200:
            return defecto
        return anno, mes


class ExportarAltasBajasExcelView(InformeAltasBajasView):
    """El libro de cuatro hojas del modelo de la UNE, listo para enviar."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        try:
            libro = excel.libro_de_altas_bajas(context)
        except Exception as e:
            return HttpResponse('Error al generar el Excel: %s' % e, status=500)
        return excel.respuesta(
            libro, _nombre_de_fichero(context, 'xlsx', 'Altas_y_Bajas'))


class ExportarAltasBajasWordView(InformeAltasBajasView):
    """Altas y Bajas del Mes en Word."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        template_path = os.path.join(
            settings.BASE_DIR, 'plantillas_word', 'informes_economia',
            'altas_bajas_template.docx')
        try:
            doc = DocxTemplate(template_path)
            context['logo'] = _logo_para_word(doc, context.get('config'))
            doc.render(context)

            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = (
                'attachment; filename="%s"'
                % _nombre_de_fichero(context, 'docx', 'Altas_y_Bajas'))
            doc.save(response)
            return response
        except Exception as e:
            return HttpResponse(f'Error al generar el Word: {str(e)}', status=500)


class ExportarAltasBajasPDFView(InformeAltasBajasView):
    """Altas y Bajas del Mes en PDF."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        html = get_template('pages/reportes/altas_bajas_pdf.html').render(context)

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            'attachment; filename="%s"'
            % _nombre_de_fichero(context, 'pdf', 'Altas_y_Bajas'))
        if pisa.CreatePDF(html, dest=response).err:
            return HttpResponse('Hubo un error al generar el PDF', status=500)
        return response


# ---------------------------------------------------------------------------
# EXPORTACIÓN A EXCEL DE LOS SEIS INFORMES DE RRHH
# ---------------------------------------------------------------------------
# Todas heredan de la vista de pantalla del informe, así que el libro sale de
# EXACTAMENTE los mismos datos que se están viendo: mismo filtro por unidad,
# mismo período, mismo modo de agrupación. Ninguna recalcula nada por su cuenta.
#
# Los tres informes con niveles —Puestos Clave, Misiones y Contratos
# Determinados— llevan DOS hojas de contenido: una plana con el nivel repetido
# en columnas, filtrable y ordenable, y otra que imita los niveles de la
# pantalla. Son dos usos distintos del mismo dato y ninguna sustituye a la otra.


def _libro_a_respuesta(libro, context, informe):
    return excel.respuesta(
        libro.libro, _nombre_de_fichero(context, 'xlsx', informe))


class ExportarConsolidadoExcelView(InformeEconomiaView):
    """Consolidado de la Fuerza de Trabajo en Excel."""

    # Las cinco categorías del modelo, en el orden en que se leen en pantalla.
    CATEGORIAS = ('Obreros', 'Técnico', 'Cuadro', 'Servicio', 'Administrativo')

    COLUMNAS = ('Cargo u Ocupación', 'Plantilla Aprobada', 'Plantilla Cubierta',
                'Plantilla Vacante', 'Mujeres', 'Determinados',
                'Determinados Mujeres', 'Adiestrados', 'Adiestrados Mujeres',
                'Total', 'Total Mujeres')

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        datos, totales = context['datos_tabla'], context['totales']

        # Las mismas cifras que encabezan su Word y su PDF: las calcula la vista
        # de pantalla una sola vez. Antes se repetían aquí, y una cuenta escrita
        # dos veces es una cuenta que puede decir dos cosas distintas.
        cifras = context['cifras_consolidado']

        libro = excel.LibroDeInforme(context, 'Consolidado de la Fuerza de Trabajo')
        libro.portada(cifras)
        libro.resumen(cifras)

        filas = [[nombre] + [datos[nombre][clave] for clave in (
                    'aprob', 'cub', 'vac', 'p_muj', 'd_tot', 'd_muj',
                    'a_tot', 'a_muj', 't_tot', 't_muj')]
                 for nombre in self.CATEGORIAS]
        total = ['TOTAL'] + [totales[clave] for clave in (
            'aprob', 'cub', 'vac', 'p_muj', 'd_tot', 'd_muj',
            'a_tot', 'a_muj', 't_tot', 't_muj')]

        libro.datos('Consolidado', self.COLUMNAS, filas,
                    anchos=[26] + [14] * 10,
                    centradas=tuple(range(2, 12)), total=total)
        return _libro_a_respuesta(libro, context, 'Consolidado')


class ExportarResumenUEBExcelView(InformeTrabajadoresUEBView):
    """Trabajadores por UEB en Excel."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        cifras = [
            ('Total de trabajadores', context['total_general'], 'Trabajadores activos'),
            ('Mujeres', context['total_mujeres'],
             '%s %% del total' % context['porciento_mujeres']),
            ('Unidades con personal', context['unidades_con_personal'],
             'de %d unidades' % len(context['datos_uebs'])),
            ('Mayor plantilla', context['unidad_mayor']['total'],
             context['unidad_mayor']['nombre']),
        ]

        libro = excel.LibroDeInforme(context, 'Trabajadores por UEB')
        libro.portada(cifras)
        libro.resumen(cifras)

        filas = [[d['nombre'], d['total'], d['mujeres'], d['porciento']]
                 for d in context['datos_uebs']]
        total = ['TOTAL GENERAL', context['total_general'],
                 context['total_mujeres'], 100]

        libro.datos('Trabajadores por UEB',
                    ('Unidad Empresarial de Base', 'Trabajadores', 'Mujeres',
                     '% del total'),
                    filas, anchos=[52, 16, 14, 14],
                    centradas=(2, 3, 4), total=total)
        return _libro_a_respuesta(libro, context, 'Trabajadores_UEB')


class ExportarPuestosClaveExcelView(InformePuestosClaveView):
    """Resumen de Puestos Clave en Excel, plano y por niveles."""

    COLUMNAS = ('Aprobada', 'Cubierta', 'Vacantes', '% Efic.', 'Determinados',
                'Mujeres', 'Adiestramiento')
    CLAVES = ('aprob', 'cub', 'vac', 'porc', 'det', 'muj', 'adiest')

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        stats = context['stats']

        cifras = [
            ('Plantilla aprobada', stats['aprobada'], 'Plazas de puestos clave'),
            ('Cubierta activa', stats['cubierta'], 'Plazas ocupadas hoy'),
            ('Vacantes críticas', stats['vacante'], 'Puestos clave sin cubrir'),
            ('Eficiencia global', '%s %%' % stats['porcentaje'],
             'Cubiertas sobre aprobadas'),
            ('Determinados', stats['det'], 'Contratos determinados'),
            ('Mujeres', stats['muj'], 'En puestos clave'),
            ('Adiestramiento', stats['adiest'], 'En adiestramiento'),
        ]

        libro = excel.LibroDeInforme(context, 'Resumen de Puestos Clave')
        libro.portada(cifras)
        libro.resumen(cifras)

        planas, niveles = self._volcar(context['datos_familias'])

        # En modo consolidado no hay nivel de unidad —es justo lo que el
        # conmutador quita—, así que su columna saldría vacía en todas las
        # filas. Una columna siempre en blanco en una hoja con autofiltro es
        # ruido: se ofrece para filtrar por algo que no existe.
        if context.get('agrupacion') == 'consolidado':
            cabeceras = ('Familia', 'Cargo') + self.COLUMNAS
            planas = [[fila[0]] + fila[2:] for fila in planas]
            anchos = [26, 46] + [13] * 7
            centradas = tuple(range(3, 10))
        else:
            cabeceras = ('Familia', 'Unidad', 'Cargo') + self.COLUMNAS
            anchos = [26, 30, 46] + [13] * 7
            centradas = tuple(range(4, 11))

        libro.datos('Puestos Clave', cabeceras, planas,
                    anchos=anchos, centradas=centradas)
        libro.por_niveles('Por niveles',
                          ('Familia / Unidad / Cargo',) + self.COLUMNAS,
                          niveles, anchos=[62] + [13] * 7,
                          centradas=tuple(range(2, 9)))
        return _libro_a_respuesta(libro, context, 'Puestos_Clave')

    def _volcar(self, familias):
        """Las dos vistas del mismo árbol, en un solo recorrido.

        Se recorre una vez y se llenan las dos listas a la vez: recorrerlo dos
        veces abriría la puerta a que una hoja y la otra dejaran de coincidir.
        """
        planas, niveles = [], []

        def cifras(origen):
            return [origen[clave] for clave in self.CLAVES]

        def unidad(nodo, familia, profundidad):
            """Una unidad, sus cargos y sus hijas, cada cual a su altura.

            La profundidad se pasa y no se deduce del papel: una subunidad se
            pinta igual que su unidad padre pero cuelga un nivel por debajo, y
            sin este parametro las dos salian al mismo nivel y la jerarquia se
            perdia justo donde mas importa.

            Una unidad sin nombre es la que fabrica el modo consolidado para no
            tener dos caminos de codigo: no se pinta, y sus cargos suben un
            nivel porque en ese modo el nivel de unidad no existe.
            """
            nombre = nodo.get('nombre') or ''
            if nombre:
                niveles.append(('unidad', profundidad, [nombre]
                                + cifras(nodo['subtotales'])))
                profundidad_del_cargo = profundidad + 1
            else:
                profundidad_del_cargo = profundidad

            for puesto in nodo['puestos']:
                planas.append([familia, nombre, puesto['nombre']]
                              + cifras(puesto))
                niveles.append(('dato', profundidad_del_cargo,
                                [puesto['nombre']] + cifras(puesto)))

            for hija in nodo.get('subunidades') or []:
                unidad(hija, familia, profundidad + 1)

        for familia in familias:
            niveles.append(('familia', 0, [familia['nombre']]
                            + cifras(familia['subtotales'])))
            for nodo in familia['unidades']:
                unidad(nodo, familia['nombre'], 1)

        return planas, niveles


class ExportarMisionesExcelView(ExportarMisionesMixin, InformeMisionesView):
    """Misiones Internacionales en Excel, plano y por unidad."""

    COLUMNAS = ('Expediente', 'Nombre y Apellidos', 'Cargo', 'Cat. Ocup.',
                'Grupo Escala', 'País', 'Días', 'Importe')
    FORMATO_IMPORTE = '#,##0.00'

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        desglose = context['desglose']

        cifras = [
            ('Total en misión', context['total_misiones'], 'Trabajadores en el exterior'),
            ('Importe', context['importe_total'], 'Suma de los importes de misión'),
            ('Países', context['paises'], 'Destinos distintos'),
            ('Unidades', context['unidades_con_mision'], 'Con personal en misión'),
        ] + [(nombre, valor, 'Por categoría ocupacional')
             for nombre, valor in desglose.items()]

        libro = excel.LibroDeInforme(context, 'Misiones Internacionales')
        libro.portada([cifras[0], cifras[2], cifras[3]])
        resumen = libro.resumen(cifras)
        resumen.cell(row=6, column=3).number_format = self.FORMATO_IMPORTE

        planas, niveles, categorias = [], [], []
        for unidad in context['misiones_por_unidad']:
            niveles.append(('unidad', 0, ['%s (%d en misión)'
                                          % (unidad['nombre'], unidad['total'])]
                            + [''] * (len(self.COLUMNAS) - 2)))
            for t in unidad['trabajadores']:
                # Vacío se exporta como 0, igual que se ve en pantalla.
                fila = [t['expediente'], t['nombre'], t['cargo'],
                        t['cat_letra'], t['g_escala'], t['pais'],
                        t['dias'] or 0, t['importe'] or Decimal('0')]
                planas.append([unidad['nombre']] + fila)
                niveles.append(('dato', 1, [fila[1]] + fila[2:]))
                categorias.append(t['cat_codigo'])

        total = (['Total'] + [''] * (len(self.COLUMNAS) - 1)
                 + [context['importe_total']])
        hoja_plana = libro.datos(
            'Misiones', ('Dirección / Área o UEB',) + self.COLUMNAS,
            planas, anchos=[30, 12, 34, 40, 11, 14, 20, 9, 14],
            centradas=(2, 5, 6, 8), col_categoria=5,
            categorias=categorias, total=total)
        hoja_niveles = libro.por_niveles(
            'Por unidad', ('Unidad / Trabajador',) + self.COLUMNAS[2:],
            niveles, anchos=[40, 40, 11, 14, 20, 9, 14],
            centradas=(3, 4, 6))

        self._formato_importe(hoja_plana, columna=9)
        self._formato_importe(hoja_niveles, columna=7)
        if context['con_valores_manuales']:
            for hoja in (resumen, hoja_plana, hoja_niveles):
                self._nota_valores_manuales(hoja, context['nota_valores_manuales'])
        return _libro_a_respuesta(libro, context, 'Misiones')

    def _formato_importe(self, hoja, columna):
        for fila in range(5, hoja.max_row + 1):
            hoja.cell(row=fila, column=columna).number_format = self.FORMATO_IMPORTE

    @staticmethod
    def _nota_valores_manuales(hoja, texto):
        """Debajo del pie, en la misma letra pequeña."""
        celda = hoja.cell(row=hoja.max_row + 1, column=1)
        celda.value = texto
        celda.font = excel.FUENTE_PIE


class ExportarRegistroDiarioExcelView(RegistroDiarioView):
    """Registro Diario por Trabajadores en Excel.

    Sin gráficos: son de JavaScript y no existen fuera del navegador. Lo que se
    archiva son las cifras, igual que en el Word y en el PDF.
    """

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        cifras = [
            ('Plan mensual', context['plan_editable'], 'Plan declarado para el mes'),
            ('Real', context['plan_real'], 'Trabajadores físicos'),
            ('Cumplimiento', '%s %%' % context['plan_cumplimiento'],
             'Real sobre plan'),
            ('Diferencia', context['plan_diferencia'], 'Real menos plan'),
            ('Mujeres', context['total_mujeres'], 'Del total de trabajadores'),
        ]

        libro = excel.LibroDeInforme(context, 'Registro Diario por Trabajadores')
        libro.portada(cifras)
        libro.resumen(cifras)

        filas = [[nombre, valores['tot'], valores['muj']]
                 for nombre, valores in context['datos'].items()]
        total = ['TOTAL DE TRABAJADORES FÍSICOS', context['plan_real'],
                 context['total_mujeres']]

        libro.datos('Indicadores',
                    ('Indicadores de Control', 'Trabajadores',
                     'De ellos, Mujeres'),
                    filas, anchos=[52, 18, 20], centradas=(2, 3), total=total)
        return _libro_a_respuesta(libro, context, 'Registro_Diario')


class ExportarMotivosExcelView(InformeMotivosContratoView):
    """Contratos Determinados en Excel, plano y por niveles."""

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        cifras = [
            ('Total determinados', context['total_contratos'], 'Contratos vigentes'),
            ('Vigentes', context['vencen_vigente'], 'Vencen a más de 30 días'),
            ('Advertencia', context['vencen_alerta'], 'Vencen en 30 días o menos'),
            ('Críticos', context['vencen_critico'], 'Vencen en 15 días o menos'),
            ('Mujeres', context['total_mujeres'],
             '%s %% del total' % context['porc_mujeres']),
        ]

        libro = excel.LibroDeInforme(context, 'Contratos Determinados')
        libro.portada(cifras[:4])
        libro.resumen(cifras)

        planas, niveles = self._volcar(
            context['datos_agrupados'],
            consolidado=context.get('agrupacion') == 'consolidado')

        libro.datos('Contratos Determinados',
                    ('Tipo de Contrato', 'Motivo', 'Unidad', 'Expediente',
                     'Nombre y Apellidos', 'Sexo'),
                    planas, anchos=[26, 34, 30, 12, 36, 8],
                    centradas=(4, 6))
        libro.por_niveles('Por niveles',
                          ('Tipo / Motivo / Unidad / Trabajador', 'Expediente',
                           'Sexo', 'Total'),
                          niveles, anchos=[62, 14, 8, 12], centradas=(2, 3, 4))

        # El desglose por motivo que la pantalla enseña como barras.
        libro.datos('Motivos',
                    ('Motivo', 'Contratos', '% del total'),
                    [[m['nombre'], m['count'], m['porc']]
                     for m in context['lista_motivos']],
                    anchos=[52, 16, 14], centradas=(2, 3))
        return _libro_a_respuesta(libro, context, 'Contratos_Determinados')

    def _volcar(self, agrupados, consolidado=False):
        """Las dos vistas del mismo árbol, en un solo recorrido.

        El conmutador se decide AQUÍ y no mirando si hay `uebs`: la vista indexa
        cada contrato dos veces —una por unidad en `uebs` y otra en `contratos`
        con la unidad dentro— y las dos listas existen siempre, en los dos modos.
        Preguntar por `uebs` daba el mismo desglose para «Desglosado» y para
        «Consolidado», que es justamente lo que el conmutador debe distinguir.

        En consolidado se recorre `contratos`, que lleva la unidad en cada fila:
        el nivel de unidad desaparece del árbol pero el dato no se pierde, y en
        la hoja plana sigue habiendo columna de Unidad.
        """
        planas, niveles = [], []

        for tipo, datos_tipo in agrupados.items():
            niveles.append(('familia', 0, [tipo, '', '', datos_tipo['total']]))

            for motivo, datos_motivo in datos_tipo['motivos'].items():
                niveles.append(('unidad', 1, [motivo, '', '',
                                              datos_motivo['total']]))

                uebs = None if consolidado else datos_motivo.get('uebs')
                if uebs:
                    # Ojo: `uebs[x]['contratos']` guarda los contratos PELADOS,
                    # mientras que `motivo['contratos']` guarda diccionarios con
                    # el contrato dentro. Son dos índices del mismo dato hechos
                    # en momentos distintos (ver `InformeMotivosContratoView`).
                    for ueb, datos_ueb in uebs.items():
                        niveles.append(('unidad', 2, [ueb, '', '',
                                                      len(datos_ueb['contratos'])]))
                        for contrato in datos_ueb['contratos']:
                            self._contrato(planas, niveles, tipo, motivo, ueb,
                                           contrato, profundidad=3)
                else:
                    for fila in datos_motivo['contratos']:
                        # Sin nivel de unidad, el contrato sube uno.
                        self._contrato(planas, niveles, tipo, motivo,
                                       fila['unidad'], fila['contrato'],
                                       profundidad=2)

        return planas, niveles

    @staticmethod
    def _contrato(planas, niveles, tipo, motivo, unidad, contrato,
                  profundidad):
        planas.append([tipo, motivo, unidad, contrato.no_expediente,
                       contrato.aspirante_nombre, contrato.sexo])
        niveles.append(('dato', profundidad, [contrato.aspirante_nombre,
                                              contrato.no_expediente,
                                              contrato.sexo, '']))
