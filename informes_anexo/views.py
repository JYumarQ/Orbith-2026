"""
Vistas del módulo Anexo 14: Estructura Jerárquica y Plantilla Aprobada.

Reporte "en vivo" (sin persistencia): siempre refleja el estado actual de
UnidadOrganizativa / Departamento / CargoPlantilla. Solo Administradores y
Observadores pueden verlo/generarlo (Moderadores no tienen acceso).
"""
from datetime import date
from io import BytesIO
from .excel.reports.anexo14 import Anexo14Report
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import HttpResponse
from django.template.loader import get_template
from django.views import View
from django.views.generic import TemplateView

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from xhtml2pdf import pisa

from bolsa.models import Aspirante
from configuracion.models import Configuracion
from contratos.models import CAlta
from nomencladores.models import NCargo
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa

NOMBRE_CARGO_DIRECTOR_CH = "Director de Capital Humano"
NOMBRE_CARGO_DIRECTOR_GENERAL = "Director General"

# (clave, etiqueta, categorías NCargo.cat_ocupacional que agrupa)
CATEGORIAS_KPI = [
    ("cuadros", "Cuadros (C)", ["CDI", "CEJ"]),
    ("tecnicos", "Técnicos (T)", ["TEC"]),
    ("administrativos", "Administrativos (A)", ["ADM"]),
    ("obreros", "Obreros (O)", ["OPE"]),
    ("servicio", "Servicio (S)", ["SER"]),
]

# CDI y CEJ se muestran como una única categoría "Cuadro" en toda la interfaz
# (tabla, filtro y exports), sin distinguir Cuadro Directivo de Cuadro Ejecutivo.
ETIQUETAS_CATEGORIA = {
    "CDI": "Cuadro",
    "CEJ": "Cuadro",
    "TEC": "Técnico",
    "ADM": "Administrativo",
    "OPE": "Obrero",
    "SER": "Servicio",
}

# Opciones del filtro de categoría (CDI/CEJ colapsadas en un solo valor "CUADRO")
OPCIONES_FILTRO_CATEGORIA = [
    ("CUADRO", "Cuadro"),
    ("TEC", "Técnico"),
    ("ADM", "Administrativo"),
    ("OPE", "Obrero"),
    ("SER", "Servicio"),
]


def _titulo_director(plantilla, aspirante):
    """
    Arma el título con género correcto según Aspirante.sexo ('M'/'F').
    Sin ocupante resuelto todavía, usa la forma neutra "Director/a ...".
    `plantilla` debe traer un marcador "{sufijo}" justo después de "Director"
    (ej. "Director{sufijo} General").
    """
    if aspirante and aspirante.sexo == "F":
        sufijo = "a"
    elif aspirante:
        sufijo = ""
    else:
        sufijo = "/a"
    return plantilla.format(sufijo=sufijo)


class PermisoAnexoMixin(UserPassesTestMixin):
    """Solo Administradores y Observadores pueden ver/generar el Anexo 14."""

    def test_func(self):
        user = self.request.user
        return bool(getattr(user, "es_admin", False) or getattr(user, "es_observador", False))

    def handle_no_permission(self):
        raise PermissionDenied("El Anexo 14 solo está disponible para Administradores y Observadores.")


def _queryset_aspirantes_cuadro():
    """
    Aspirantes activos cuyo cargo actual es de categoría Cuadro (CDI/CEJ),
    para el select manual de respaldo. Mismo patrón que
    contratos/views.py (ExportarContratoWordView.get_form_kwargs).
    """
    return (
        Aspirante.objects.filter(
            estado="ACTIVO",
            calta_contratos__cargo__ncargo__cat_ocupacional__in=["CDI", "CEJ"],
        )
        .distinct()
        .order_by("nombre", "papellido")
    )


def _resolver_firmante(descripcion_cargo, plantilla_titulo, aspirante_manual_id=None):
    """
    Devuelve un dict con el estado de resolución de un firmante:
      - aspirante: el Aspirante a mostrar (o None)
      - titulo: "Director"/"Directora"/"Director/a" + el resto de la plantilla,
        según Aspirante.sexo
      - cargo_existe: si el NCargo con ese nombre exacto existe en el nomenclador
      - es_manual: si el valor viene de una selección manual explícita
      - ambiguo: si hay más de un contrato activo para el mismo cargo exacto
    """
    resultado = {"aspirante": None, "cargo_existe": False, "es_manual": False, "ambiguo": False}

    if aspirante_manual_id:
        elegido = _queryset_aspirantes_cuadro().filter(pk=aspirante_manual_id).first()
        if elegido:
            resultado["aspirante"] = elegido
            resultado["es_manual"] = True
            resultado["cargo_existe"] = NCargo.objects.filter(descripcion__iexact=descripcion_cargo).exists()
            resultado["titulo"] = _titulo_director(plantilla_titulo, elegido)
            return resultado

    ncargo = NCargo.objects.filter(descripcion__iexact=descripcion_cargo).first()
    if not ncargo:
        resultado["titulo"] = _titulo_director(plantilla_titulo, None)
        return resultado

    resultado["cargo_existe"] = True

    ocupantes = list(
        CAlta.objects.filter(
            cargo__ncargo=ncargo,
            aspirante__estado="ACTIVO",
            tipo__ocupa_plaza=True,
        ).select_related("aspirante")
    )

    if len(ocupantes) == 1:
        resultado["aspirante"] = ocupantes[0].aspirante
    elif len(ocupantes) > 1:
        # Dato inconsistente (más de un ocupante activo para el mismo cargo):
        # no se adivina, se deja para selección manual.
        resultado["ambiguo"] = True

    resultado["titulo"] = _titulo_director(plantilla_titulo, resultado["aspirante"])
    return resultado


def _construir_hijas(unidad_padre, filtros):
    """
    Devuelve la lista de Unidades Hijas de `unidad_padre` con sus
    Departamentos y Cargos ya precargados (prefetch anidado, sin N+1),
    aplicando los filtros de búsqueda/categoría/rol sobre los cargos.
    Solo incluye Departamentos que, tras el filtro, quedaron con al menos
    un cargo.
    """
    if unidad_padre is None:
        return []

    cargos_qs = CargoPlantilla.objects.filter(activo=True).select_related(
        "ncargo", "ncargo__grupo_escala", "rol", "nivel_preparacion"
    )

    busqueda = filtros.get("busqueda")
    categoria = filtros.get("categoria")
    rol = filtros.get("rol")

    if busqueda:
        cargos_qs = cargos_qs.filter(ncargo__descripcion__icontains=busqueda)
    if categoria and categoria != "ALL":
        if categoria == "CUADRO":
            cargos_qs = cargos_qs.filter(ncargo__cat_ocupacional__in=["CDI", "CEJ"])
        else:
            cargos_qs = cargos_qs.filter(ncargo__cat_ocupacional=categoria)
    if rol and rol != "ALL":
        cargos_qs = cargos_qs.filter(rol__tipo=rol)

    cargos_qs = cargos_qs.order_by("orden_informe", "ncargo__descripcion")

    departamentos_qs = Departamento.objects.order_by("orden_informe", "id").prefetch_related(
        Prefetch("cargoplantilla_set", queryset=cargos_qs, to_attr="cargos_filtrados")
    )

    hijas = (
        UnidadOrganizativa.objects.filter(padre=unidad_padre, tipo__es_subunidad=True)
        .select_related("tipo")
        .order_by("orden_informe", "descripcion")
        .prefetch_related(Prefetch("departamentos", queryset=departamentos_qs, to_attr="departamentos_todos"))
    )

    resultado = []
    for hija in hijas:
        departamentos_con_cargos = [d for d in hija.departamentos_todos if d.cargos_filtrados]
        if departamentos_con_cargos:
            hija.departamentos_con_cargos = departamentos_con_cargos
            resultado.append(hija)

    unidad_hija_id = filtros.get("unidad_hija_id")
    if unidad_hija_id:
        resultado = [h for h in resultado if str(h.pk) == str(unidad_hija_id)]

    return resultado


def _calcular_kpis(hijas):
    """Suma cant_aprobada por categoría ocupacional sobre el árbol ya
    filtrado/precargado (no dispara consultas adicionales)."""
    total = 0
    conteos = {clave: 0 for clave, _, _ in CATEGORIAS_KPI}
    total_departamentos = 0

    for hija in hijas:
        for depto in hija.departamentos_con_cargos:
            total_departamentos += 1
            for cargo in depto.cargos_filtrados:
                cantidad = cargo.cant_aprobada or 0
                total += cantidad
                for clave, _, categorias in CATEGORIAS_KPI:
                    if cargo.ncargo.cat_ocupacional in categorias:
                        conteos[clave] += cantidad
                        break

    return {
        "total_cargos": total,
        "total_unidades": len(hijas),
        "total_departamentos": total_departamentos,
        "conteos": conteos,
    }


def _obtener_filtros(request):
    return {
        "busqueda": request.GET.get("q", "").strip(),
        "categoria": request.GET.get("categoria", "ALL"),
        "rol": request.GET.get("rol", "ALL"),
        "unidad_padre_id": request.GET.get("padre"),
        "unidad_hija_id": request.GET.get("unidad"),
        "director_ch_id": request.GET.get("director_ch"),
        "director_gral_id": request.GET.get("director_gral"),
    }


def _obtener_datos_reporte(request):
    """
    Construye todo el contexto de datos del Anexo 14 (árbol, KPIs,
    firmantes, metadatos institucionales) a partir de los parámetros GET de
    `request`. Función compartida entre la vista HTML y las 2 exportaciones,
    para que ambas siempre reflejen exactamente los mismos filtros.
    """
    filtros = _obtener_filtros(request)

    padres = (
        UnidadOrganizativa.objects.filter(tipo__es_principal=True, padre__isnull=True)
        .select_related("tipo", "municipio", "municipio__provincia")
        .order_by("orden_informe", "descripcion")
    )
    padres_lista = list(padres)

    padre_actual = None
    if filtros["unidad_padre_id"]:
        padre_actual = next((p for p in padres_lista if str(p.pk) == filtros["unidad_padre_id"]), None)
    if not padre_actual and padres_lista:
        padre_actual = padres_lista[0]

    # `hijas_todas` alimenta el selector de unidad (sin filtrar) y `hijas` la tabla.
    # Cuando no hay ningún filtro activo ambas listas son idénticas, así que se
    # reutiliza en vez de reconstruir el árbol completo por segunda vez.
    hay_filtros_de_cargo = any((
        filtros.get("busqueda"),
        filtros.get("categoria") not in (None, "", "ALL"),
        filtros.get("rol") not in (None, "", "ALL"),
        filtros.get("unidad_hija_id"),
    ))
    hijas_todas = _construir_hijas(padre_actual, {}) if padre_actual else []
    hijas = (_construir_hijas(padre_actual, filtros) if (padre_actual and hay_filtros_de_cargo)
             else hijas_todas)
    kpis = _calcular_kpis(hijas)

    director_ch = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_CH, "Director{sufijo} de Capital Humano", filtros["director_ch_id"]
    )
    director_gral = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_GENERAL, "Director{sufijo} General", filtros["director_gral_id"]
    )

    necesita_select_manual = not director_ch["aspirante"] or not director_gral["aspirante"]

    return {
        "configuracion": Configuracion.objects.first(),
        "padres": padres_lista,
        "padre_actual": padre_actual,
        "mostrar_selector_padre": len(padres_lista) > 1,
        "hijas_todas": hijas_todas,
        "hijas": hijas,
        "kpis": kpis,
        "categorias_kpi": CATEGORIAS_KPI,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        "opciones_filtro_categoria": OPCIONES_FILTRO_CATEGORIA,
        "filtros": filtros,
        "director_ch": director_ch,
        "director_gral": director_gral,
        "aspirantes_cuadro": _queryset_aspirantes_cuadro() if necesita_select_manual else Aspirante.objects.none(),
        "fecha_generacion": date.today(),
    }


class AnexoCatorceView(PermisoAnexoMixin, TemplateView):
    template_name = "pages/informes_anexo/anexo14.html"
    #: Solo el bloque de firmas, para las peticiones HTMX de los `<select>` de
    #: firmantes. Elegir un firmante no cambia el árbol de unidades ni los KPIs, así
    #: que repintar la página entera (lo que hacía el `form.submit()` anterior) era
    #: trabajo desperdiciado y perdía la posición de scroll.
    template_name_firmas = "pages/informes_anexo/partials/bloque_firmas.html"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return [self.template_name_firmas]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_obtener_datos_reporte(self.request))
        # Activa el `hx-swap-oob` de la botonera de exportación: sus enlaces llevan
        # los filtros en el query string y quedarían desfasados tras el intercambio.
        context["intercambio_oob"] = bool(getattr(self.request, "htmx", False))
        return context


class ExportarAnexo14ExcelView(PermisoAnexoMixin, View):
    def get(self, request, *args, **kwargs):
        # 1. Reutiliza la función que ya construiste con todo el árbol de datos y filtros
        datos = _obtener_datos_reporte(request)
        
        # 2. Delega la creación del Excel al motor especializado
        reporte = Anexo14Report()
        return reporte.export_to_response(datos)


class ExportarAnexo14PDFView(PermisoAnexoMixin, View):
    def get(self, request, *args, **kwargs):
        datos = _obtener_datos_reporte(request)
        template = get_template("pages/informes_anexo/partials/anexo14_pdf.html")
        html = template.render(datos)

        response = HttpResponse(content_type="application/pdf")
        nombre_archivo = f"Anexo_14_{date.today().isoformat()}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'

        pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), response, encoding="UTF-8")
        if pdf.err:
            return HttpResponse("Error al generar el PDF del Anexo 14.", status=500)
        return response
