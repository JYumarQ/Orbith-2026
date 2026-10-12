"""
Vistas del módulo Anexo: la Plantilla de Cargos en sus dos modelos oficiales.

* ANEXO 14 — Estructura Jerárquica y Plantilla Aprobada: el detalle, una fila
  por cargo con su rol, su nivel de preparación y su grupo escala.
* ANEXO 14-A — Resumen de la Plantilla de Cargos: el conteo, una fila por unidad
  o por departamento con sus plazas por categoría ocupacional. Las cifras las
  agrega `informes_anexo/anexo14a.py`; aquí vive solo su vista.

Los dos son reportes "en vivo" (sin persistencia): siempre reflejan el estado
actual de UnidadOrganizativa / Departamento / CargoPlantilla, comparten el
alcance por rol y comparten los dos firmantes institucionales.

ALCANCE
-------
Lo ven los tres roles, pero no todos ven lo mismo. La regla la decide
`usuarios.alcance` y se aplica en `_unidades_del_alcance()`, que es el ÚNICO
punto donde se acota el árbol:

* Administrador, y Observador sin unidades asignadas: la empresa entera.
* Observador con unidades asignadas, y Moderador: solo sus Unidades
  Principales, con los departamentos y cargos que cuelgan de ellas.

En ese segundo caso el Anexo 14 sale PARCIAL a propósito: los KPIs se calculan
sobre el árbol ya acotado (`_calcular_kpis` recorre lo que le llega), así que un
Moderador nunca ve los totales de la empresa. Las firmas, en cambio, siguen
siendo las institucionales —Director General y Director de Capital Humano—:
identifican quién aprueba la plantilla, no quién consulta el informe.

El acotado se hace en el SERVIDOR, no limitando los desplegables: quien edite a
mano `?padre=` con el id de una unidad ajena recibe la primera de las suyas, no
la que pidió.
"""
from datetime import date
from . import anexo14a, anexo14b
from .excel.libro import (MODO_14, MODO_14A, MODO_14B, MODO_AMBOS,
                         libro_del_anexo, nombre_de_fichero, respuesta_excel)
from .excel.libro14b import libro_del_anexo_14b
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView


from bolsa.models import Aspirante
from configuracion.models import Configuracion
from contratos.models import CAlta
from nomencladores.models import NCargo
from strorganizativa.models import CargoPlantilla, Departamento, UnidadOrganizativa
from usuarios.alcance import tiene_alcance_acotado, ve_toda_la_empresa

NOMBRE_CARGO_DIRECTOR_CH = "Director de Capital Humano"
NOMBRE_CARGO_DIRECTOR_GENERAL = "Director General"

# (clave, sigla, etiqueta, categorías NCargo.cat_ocupacional que agrupa)
#
# La SIGLA es la letra del modelo oficial y es la que rotula la tarjeta de cifra;
# la ETIQUETA es la palabra entera, que va debajo. Están separadas porque
# «Administrativos (A)» no cabe en el rótulo de una tarjeta y salía recortado a
# «ADMINISTRATI». Es el mismo reparto que usa `anexo14a.COLUMNAS_14A`.
CATEGORIAS_KPI = [
    ("cuadros", "C", "Cuadros (C)", ["CDI", "CEJ"]),
    ("tecnicos", "T", "Técnicos (T)", ["TEC"]),
    ("administrativos", "A", "Administrativos (A)", ["ADM"]),
    ("obreros", "O", "Obreros (O)", ["OPE"]),
    ("servicio", "S", "Servicio (S)", ["SER"]),
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
    """Los tres roles pueden consultar el Anexo 14; cada uno ve su alcance.

    El Moderador antes estaba bloqueado por completo. Se le abre porque el
    informe es de solo lectura y ahora sale acotado a sus unidades
    (`_unidades_del_alcance`): lo que veía de más —la plantilla de la empresa
    entera— es justo lo que el acotado impide.

    Un usuario autenticado sin ningún rol reconocido sigue fuera: no es un caso
    normal (`CustomUser.clean()` exige un rol), pero si ocurriera no debe colarse
    por la puerta de un informe.
    """

    def test_func(self):
        return ve_toda_la_empresa(self.request.user) or tiene_alcance_acotado(self.request.user)

    def handle_no_permission(self):
        raise PermissionDenied("El Anexo 14 solo está disponible para usuarios con un rol asignado.")


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


def _unidades_del_alcance(usuario):
    """Ids de las unidades que este usuario puede ver, o `None` si todas.

    Único punto de alcance del módulo, mismo contrato que
    `informes.fuentes.unidades_visibles()`: `None` significa «sin restricción» y
    NO es lo mismo que un conjunto vacío. Un usuario con el alcance acotado y
    sin ninguna unidad asignada no debe ver ni una fila.

    No hace falta expandir a las subunidades: el formulario de Usuarios guarda
    ya las hijas junto al padre (`usuarios.forms.expandir_a_subunidades`), y
    `strorganizativa.signals` mantiene esa relación al día cuando nace o se muda
    una subunidad.
    """
    if ve_toda_la_empresa(usuario):
        return None
    if tiene_alcance_acotado(usuario):
        return set(usuario.unidades.values_list("pk", flat=True))
    return set()


def _construir_hijas(unidad_padre, filtros, en_plantilla=True, permitidas=None):
    """
    Devuelve la lista de Unidades Hijas de `unidad_padre` con sus
    Departamentos y Cargos ya precargados (prefetch anidado, sin N+1),
    aplicando los filtros de búsqueda/categoría/rol sobre los cargos.
    Solo incluye Departamentos que, tras el filtro, quedaron con al menos
    un cargo.

    `en_plantilla` elige de qué lado se construye el árbol: el Anexo 14 lo llama
    dos veces, una para la plantilla aprobada (el informe de siempre) y otra para
    los cargos que quedaron fuera de ella, que se listan en una sección aparte
    con su propio subtotal y NO suman en las cifras oficiales.

    `permitidas` es el alcance del usuario (`_unidades_del_alcance`): `None` no
    acota nada, y un conjunto deja pasar solo las hijas que estén en él.

    UNIDADES HOJA
    -------------
    No toda unidad raíz tiene subunidades colgando. Una UEB (Florida, Nuevitas,
    Despacho…) no puede tenerlas —`UnidadOrganizativa.clean()` exige que el padre
    de una subunidad sea una Unidad Principal—, pero sí tiene Departamentos
    propios. Para esas unidades el árbol se construye sobre ellas mismas: se
    devuelven como su única «hija», y así el resto del módulo (tabla, KPIs,
    exportaciones) no tiene que distinguir los dos casos.
    """
    if unidad_padre is None:
        return []

    cargos_qs = CargoPlantilla.objects.filter(
        activo=True, en_plantilla=en_plantilla
    ).select_related(
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

    hijas_qs = (
        UnidadOrganizativa.objects.filter(padre=unidad_padre, tipo__es_subunidad=True)
        .select_related("tipo")
        .order_by("orden_informe", "descripcion")
        .prefetch_related(Prefetch("departamentos", queryset=departamentos_qs, to_attr="departamentos_todos"))
    )
    if permitidas is not None:
        hijas_qs = hijas_qs.filter(pk__in=permitidas)
    hijas = list(hijas_qs)

    # Unidad hoja: sin subunidades, el contenido son sus propios Departamentos.
    # La condición mira si EXISTEN subunidades, no si dieron cargos: una Unidad
    # Principal cuyas subunidades quedaron vacías tras el filtro debe salir
    # vacía, no destapar de pronto los departamentos del padre.
    if not hijas and (permitidas is None or unidad_padre.pk in permitidas):
        hijas = list(
            UnidadOrganizativa.objects.filter(pk=unidad_padre.pk)
            .select_related("tipo")
            .prefetch_related(
                Prefetch("departamentos", queryset=departamentos_qs, to_attr="departamentos_todos")
            )
        )
        # Se marca para que la pantalla NO le pinte su rótulo de subunidad: la
        # unidad ya tiene su cabecera arriba, y repetir su nombre justo debajo la
        # haría parecer una subunidad de sí misma.
        for hija in hijas:
            hija.es_la_propia_unidad = True

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
    conteos = {clave: 0 for clave, _, _, _ in CATEGORIAS_KPI}
    total_departamentos = 0

    for hija in hijas:
        for depto in hija.departamentos_con_cargos:
            total_departamentos += 1
            for cargo in depto.cargos_filtrados:
                cantidad = cargo.cant_aprobada or 0
                total += cantidad
                for clave, _, _, categorias in CATEGORIAS_KPI:
                    if cargo.ncargo.cat_ocupacional in categorias:
                        conteos[clave] += cantidad
                        break

    return {
        "total_cargos": total,
        "total_unidades": len(hijas),
        "total_departamentos": total_departamentos,
        "conteos": conteos,
    }


def _secciones_por_unidad(hijas, hijas_fuera):
    """Une las dos ramas del árbol en una sola lista, una entrada por subunidad.

    El Anexo 14 construye por separado la plantilla aprobada y los cargos que
    quedaron fuera de ella. En pantalla, sin embargo, cada subunidad es una
    PESTAÑA y necesita las dos cosas juntas: no tendría sentido navegar las
    unidades por un lado para lo aprobado y por otro para lo que no lo está.

    Cruzarlas aquí y no en la plantilla es deliberado: emparejar dos listas por
    clave dentro de un `{% for %}` obliga a recorrer la segunda entera en cada
    vuelta de la primera, y Django no tiene forma de indexar un diccionario por
    una variable sin un filtro auxiliar.

    Se listan también las subunidades que SOLO tienen cargos fuera de plantilla:
    son las que más falta hace ver, y si el recorrido partiera de `hijas` se
    quedarían fuera del informe sin que nadie lo notara.
    """
    orden = []
    indice = {}

    for hija in hijas:
        indice[hija.pk] = {
            "unidad": hija,
            "departamentos": hija.departamentos_con_cargos,
            "departamentos_fuera": [],
        }
        orden.append(hija.pk)

    for hija in hijas_fuera:
        seccion = indice.get(hija.pk)
        if seccion is None:
            seccion = {"unidad": hija, "departamentos": [], "departamentos_fuera": []}
            indice[hija.pk] = seccion
            orden.append(hija.pk)
        seccion["departamentos_fuera"] = hija.departamentos_con_cargos

    secciones = [indice[pk] for pk in orden]
    for seccion in secciones:
        seccion["total"] = sum(
            cargo.cant_aprobada or 0
            for depto in seccion["departamentos"]
            for cargo in depto.cargos_filtrados
        )
        seccion["total_fuera"] = sum(
            cargo.cant_aprobada or 0
            for depto in seccion["departamentos_fuera"]
            for cargo in depto.cargos_filtrados
        )
    return secciones


# ==========================================================================
# EL SELECTOR DE UNIDADES Y LAS PESTAÑAS
# ==========================================================================
# Los dos anexos se navegan igual: un selector MÚLTIPLE de unidades arriba y,
# debajo, una pestaña por cada unidad elegida precedida de la de «Resumen». Es
# el mismo reparto que tiene el libro de Excel, así que quien exporta ya sabe
# lo que va a recibir.
#
# El control es `base/partials/selector_unidades.html`, el mismo de fichas que
# usan el Dashboard, Informes RRHH, Informe Inteligente, Contratos, Pre-Nómina y
# Subsanación. No se construye nada aquí: solo se le pasan las unidades y el
# texto de su estado vacío.

#: `name` del <select> oculto del selector. Cada pantalla de Orbith usa el suyo
#: (`uo` en el Dashboard, `ueb` en Informes RRHH); el de los anexos es este.
CAMPO_UNIDADES = "uo"


def _raices_del_alcance(usuario):
    """Las unidades RAÍZ que este usuario puede ver, en orden de organigrama.

    Solo raíces, y no también las subunidades como hace el selector de Informes
    RRHH: aquí cada cosa que se elige es una pestaña en pantalla y una hoja en el
    Excel, y una subunidad no es ninguna de las dos. Ofrecerlas rompería esa
    equivalencia sin dar nada a cambio.

    Se les pone `nivel = 0` porque es lo que el parcial del selector espera para
    decidir la sangría; aquí son todas del mismo nivel por construcción.
    """
    permitidas = _unidades_del_alcance(usuario)

    consulta = (
        UnidadOrganizativa.objects.filter(padre__isnull=True)
        .select_related("tipo", "municipio")
        .order_by("orden_informe", "descripcion")
    )
    if permitidas is not None:
        consulta = consulta.filter(pk__in=permitidas)

    raices = list(consulta)
    for raiz in raices:
        raiz.nivel = 0
    return raices


def _marcador_de_unidades(usuario, raices):
    """Qué dice la caja del selector cuando no hay ninguna unidad marcada.

    No es un adorno: en este control «nada marcado» significa «todo lo que tu rol
    te deja ver», y esa frase no es la misma para todos. Un Administrador ve la
    empresa entera; un Moderador, sus unidades. Decirle «Todas las unidades» al
    segundo le haría creer que está mirando la empresa.
    """
    if ve_toda_la_empresa(usuario):
        return "Toda la Empresa"
    if len(raices) == 1:
        return raices[0].descripcion
    return "Todas mis unidades"


def _unidades_elegidas(request, raices):
    """Las unidades sobre las que va el informe, cruzadas con el alcance.

    Nada marcado significa TODO el alcance del usuario, que es como se comporta
    este selector en el resto de Orbith y lo que evita que el informe aparezca en
    blanco al entrar.

    El cruce con `raices` —que ya viene acotada por rol— es la barrera de verdad:
    quien escriba a mano `?uo=` con el id de una unidad ajena no la recibe, se la
    ignoramos en silencio.
    """
    pedidas = {v for v in request.GET.getlist(CAMPO_UNIDADES) if v.isdigit()}

    # Compatibilidad: hasta que el selector fue múltiple, la unidad viajaba en
    # `?padre=` y valía por una sola. Los enlaces guardados o compartidos con esa
    # forma se siguen entendiendo en vez de devolver el informe entero.
    if not pedidas:
        antiguo = request.GET.get("padre")
        if antiguo and antiguo.isdigit():
            pedidas = {antiguo}

    elegidas = [r for r in raices if str(r.pk) in pedidas]
    return elegidas or raices


def _contexto_de_unidades(request):
    """El selector, las pestañas y las cifras de cabecera. Común a los dos anexos.

    Las cifras salen de `anexo14a.filas_de_empresa()` y no de recorrer el árbol:
    es una sola consulta agregada sobre las unidades elegidas, así que abrir la
    pantalla no depende de cuántos cargos tenga la plantilla.
    """
    permitidas = _unidades_del_alcance(request.user)
    raices = _raices_del_alcance(request.user)
    elegidas = _unidades_elegidas(request, raices)

    # Los filtros de cargo mandan también aquí. Si el Anexo 14 está filtrado por
    # «Obrero», las tarjetas de cifra y el Resumen tienen que contar obreros: son
    # el encabezado de lo que se está mirando, no un total ajeno al filtro. El
    # 14-A no tiene estos filtros, así que allí esto no acota nada.
    filtros = _obtener_filtros(request)

    resumen = anexo14a.filas_de_empresa(elegidas, permitidas, filtros=filtros)
    resumen_fuera = anexo14a.filas_de_empresa(
        elegidas, permitidas, en_plantilla=False, filtros=filtros)

    return {
        "campo_unidades": CAMPO_UNIDADES,
        "unidades_selector": raices,
        "unidades_marcadas": [str(u.pk) for u in elegidas] if len(elegidas) != len(raices) else [],
        "marcador_unidades": _marcador_de_unidades(request.user, raices),
        "unidades": elegidas,
        "columnas_14a": anexo14a.COLUMNAS_14A,
        "resumen": resumen,
        "resumen_fuera": resumen_fuera,
    }


def _hay_filtros_de_cargo(filtros):
    """Si hay algún filtro de CARGO puesto (búsqueda, categoría o rol).

    La unidad no cuenta como filtro: es el alcance del informe, no un recorte
    dentro de él. Por eso exportar con dos unidades marcadas no pregunta nada,
    y exportar con la categoría en «Obrero» sí.
    """
    return any((
        filtros.get("busqueda"),
        filtros.get("categoria") not in (None, "", "ALL"),
        filtros.get("rol") not in (None, "", "ALL"),
    ))


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

    # Alcance del usuario: acota tanto las Unidades Principales del selector
    # como las hijas del árbol. Se resuelve UNA vez y se pasa hacia abajo, para
    # no repetir la misma consulta en cada llamada a `_construir_hijas`.
    permitidas = _unidades_del_alcance(request.user)

    # Toda unidad RAÍZ, no solo las marcadas como Principales. Antes se exigía
    # `tipo__es_principal=True` y eso dejaba fuera del informe a las UEB —que no
    # son Principales ni subunidades, y cuelgan de nadie—: ni salían en el
    # selector ni se podían consultar, aunque tuvieran plantilla aprobada. El
    # Anexo 14-A las necesita porque su Resumen es, precisamente, una fila por
    # unidad raíz.
    padres = (
        UnidadOrganizativa.objects.filter(padre__isnull=True)
        .select_related("tipo", "municipio", "municipio__provincia")
        .order_by("orden_informe", "descripcion")
    )
    if permitidas is not None:
        padres = padres.filter(pk__in=permitidas)
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
    hijas_todas = (_construir_hijas(padre_actual, {}, permitidas=permitidas)
                   if padre_actual else [])
    hijas = (_construir_hijas(padre_actual, filtros, permitidas=permitidas)
             if (padre_actual and hay_filtros_de_cargo) else hijas_todas)
    # Los KPIs son los del informe oficial: se calculan solo sobre la plantilla
    # aprobada, nunca sobre la sección de fuera de plantilla.
    kpis = _calcular_kpis(hijas)

    # Sección aparte: mismos filtros y misma estructura (unidad -> departamento),
    # pero con los cargos que NO están en la plantilla aprobada.
    hijas_fuera = (_construir_hijas(padre_actual, filtros, en_plantilla=False,
                                    permitidas=permitidas)
                   if padre_actual else [])
    kpis_fuera = _calcular_kpis(hijas_fuera)

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
        "hijas_fuera_plantilla": hijas_fuera,
        "kpis_fuera_plantilla": kpis_fuera,
        # Las dos ramas ya emparejadas: una entrada por subunidad, que es lo que
        # recorre la pantalla para pintar una pestaña por cada una.
        "secciones": _secciones_por_unidad(hijas, hijas_fuera),
        "categorias_kpi": CATEGORIAS_KPI,
        # Las tarjetas de cifra las alimenta la MISMA definición que usa el 14-A
        # (`anexo14a.COLUMNAS_14A`), que trae para cada categoría su letra del
        # modelo oficial y su nombre entero. `CATEGORIAS_KPI` solo tiene el nombre
        # largo, y en una tarjeta de 9 píxeles «Administrativos (A)» no cabe:
        # salía recortado a la letra final por puro desbordamiento, no por
        # decisión de nadie. Las claves son las mismas, así que `kpis.conteos`
        # responde igual a las dos listas.
        "columnas_14a": anexo14a.COLUMNAS_14A,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        "opciones_filtro_categoria": OPCIONES_FILTRO_CATEGORIA,
        "filtros": filtros,
        "director_ch": director_ch,
        "director_gral": director_gral,
        "aspirantes_cuadro": _queryset_aspirantes_cuadro() if necesita_select_manual else Aspirante.objects.none(),
        "fecha_generacion": date.today(),
        # El bloque de firmas es el mismo parcial en el Anexo 14 y en el 14-A.
        # Lo único que cambia entre los dos es a qué vista apunta el HTMX de los
        # `<select>` y qué botonera de exportación se reinyecta con él, así que
        # ambos viajan por contexto en vez de duplicar la plantilla.
        "url_firmas": reverse("informes_anexo:anexo14"),
        "url_excel_propio": "informes_anexo:anexo14_excel",
        "nombre_informe": "Anexo 14",
        # Con filtros de cargo puestos, exportar deja de ser una sola cosa: puede
        # querer decir «la plantilla» o «lo que estoy viendo». La pantalla lo
        # pregunta antes de descargar en vez de elegir por su cuenta.
        "hay_filtros_activos": _hay_filtros_de_cargo(filtros),
    }


class _PanelDeUnidadMixin(PermisoAnexoMixin):
    """Base de las dos vistas que sirven UNA pestaña.

    Las pestañas de unidad se cargan al pulsarlas, no al abrir la pantalla: con
    treinta unidades y miles de cargos, mandarlas todas de golpe hace que la
    página tarde en aparecer para enseñar algo que casi nunca se mira entero.

    Resuelve la unidad contra el alcance del usuario y no contra la base a secas:
    esta URL se puede escribir a mano, y es la misma puerta que la pantalla.
    """

    def unidad_o_404(self, request, codigo):
        raices = _raices_del_alcance(request.user)
        unidad = next((r for r in raices if r.pk == codigo), None)
        if unidad is None:
            raise Http404("La unidad no existe o está fuera de su alcance.")
        return unidad


class PanelUnidadAnexo14View(_PanelDeUnidadMixin, TemplateView):
    """El contenido de una pestaña del Anexo 14: sus subunidades y sus cargos."""

    template_name = "pages/informes_anexo/partials/panel_unidad_14.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        unidad = self.unidad_o_404(request, kwargs["codigo"])

        permitidas = _unidades_del_alcance(request.user)
        filtros = _obtener_filtros(request)

        hijas = _construir_hijas(unidad, filtros, permitidas=permitidas)
        hijas_fuera = _construir_hijas(unidad, filtros, en_plantilla=False,
                                       permitidas=permitidas)

        context.update({
            "unidad": unidad,
            "secciones": _secciones_por_unidad(hijas, hijas_fuera),
            "kpis": _calcular_kpis(hijas),
            "kpis_fuera_plantilla": _calcular_kpis(hijas_fuera),
            "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        })
        return context


class PanelUnidadAnexo14AView(_PanelDeUnidadMixin, TemplateView):
    """El contenido de una pestaña del Anexo 14-A: el conteo de esa unidad."""

    template_name = "pages/informes_anexo/partials/panel_unidad_14a.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        unidad = self.unidad_o_404(request, kwargs["codigo"])
        permitidas = _unidades_del_alcance(request.user)

        aprobada = anexo14a.filas_de_unidad(unidad, permitidas)
        fuera = anexo14a.filas_de_unidad(unidad, permitidas, en_plantilla=False)

        context.update({
            "unidad": unidad,
            "columnas_14a": anexo14a.COLUMNAS_14A,
            "filas": aprobada["filas"],
            "total": aprobada["total"],
            "filas_fuera": fuera["filas"],
            "total_fuera": fuera["total"],
        })
        return context


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
        # El selector múltiple y las pestañas, que son iguales en los dos anexos.
        # Van DESPUÉS para que sus cifras —las del alcance elegido— ganen a las
        # que `_obtener_datos_reporte` calcula todavía sobre una sola unidad.
        context.update(_contexto_de_unidades(self.request))
        # Activa el `hx-swap-oob` de la botonera de exportación: sus enlaces llevan
        # los filtros en el query string y quedarían desfasados tras el intercambio.
        context["intercambio_oob"] = bool(getattr(self.request, "htmx", False))
        return context


# ==========================================================================
# ANEXO 14-A — Resumen cuantitativo de la Plantilla de Cargos
# ==========================================================================
# Comparte con el Anexo 14 el alcance por rol, el selector de unidad y los dos
# firmantes institucionales; cambia el CONTENIDO: aquí no se lista ni un cargo,
# solo se cuentan plazas por categoría ocupacional. El detalle de cómo se
# agregan las cifras está en `informes_anexo/anexo14a.py`.
#
# Tampoco lleva los filtros de búsqueda, categoría y rol del Anexo 14: filtrar
# por categoría un informe cuyas columnas SON las categorías vaciaría el resto
# del modelo y el papel dejaría de cuadrar.


def _cabecera_institucional(config, unidad):
    """Las seis líneas que encabezan el modelo oficial, desde Parámetros Generales.

    Nada va quemado en la plantilla `.xlsx`: el fichero que entregó Capital
    Humano traía la empresa, el organismo y la provincia escritos a mano, y así
    Orbith solo serviría a una entidad. El municipio sale de la unidad, no de la
    configuración, porque es lo que identifica a ESA unidad; cuando el informe va
    de la empresa entera no hay un municipio que sea «el» del informe.
    """
    provincia = ""
    if config and config.provincia_entidad_id:
        provincia = config.provincia_entidad.nombre

    return {
        "cab_empresa": config.nombre_empresa if config else "",
        "cab_organismo": (config.org_superior if config else "") or "",
        "cab_reup": (config.reup if config else "") or "",
        "cab_provincia": provincia,
        "cab_municipio": (unidad.municipio.nombre
                          if unidad and unidad.municipio_id else ""),
        "cab_unidad": (unidad.descripcion if unidad
                       else (config.nombre_empresa if config else "")),
    }


def _datos_anexo14a(request):
    """Todo el contexto del Anexo 14-A, compartido por la pantalla y el Excel.

    Sin `?padre=` sale el RESUMEN DE EMPRESA —una fila por unidad raíz—, y con
    él, el 14-A de esa unidad. Es la diferencia con el Anexo 14, que sin unidad
    elegida cae en la primera: allí el informe no existe sin una unidad, y aquí
    el nivel de empresa es un informe por derecho propio.
    """
    permitidas = _unidades_del_alcance(request.user)

    padres = (
        UnidadOrganizativa.objects.filter(padre__isnull=True)
        .select_related("tipo", "municipio")
        .order_by("orden_informe", "descripcion")
    )
    if permitidas is not None:
        padres = padres.filter(pk__in=permitidas)
    padres_lista = list(padres)

    # Solo se acepta una unidad que esté en la lista ya acotada: quien escriba a
    # mano `?padre=` con el id de una unidad ajena cae en el resumen de empresa
    # de SU alcance, no en la unidad que pidió.
    unidad_pedida = request.GET.get("padre")
    padre_actual = None
    if unidad_pedida:
        padre_actual = next(
            (p for p in padres_lista if str(p.pk) == unidad_pedida), None)

    if padre_actual:
        aprobada = anexo14a.filas_de_unidad(padre_actual, permitidas)
        fuera = anexo14a.filas_de_unidad(padre_actual, permitidas, en_plantilla=False)
    else:
        aprobada = anexo14a.filas_de_empresa(padres_lista, permitidas)
        fuera = anexo14a.filas_de_empresa(padres_lista, permitidas, en_plantilla=False)

    director_ch_id = request.GET.get("director_ch")
    director_gral_id = request.GET.get("director_gral")
    director_ch = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_CH, "Director{sufijo} de Capital Humano", director_ch_id)
    director_gral = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_GENERAL, "Director{sufijo} General", director_gral_id)
    necesita_select_manual = not director_ch["aspirante"] or not director_gral["aspirante"]

    config = Configuracion.objects.select_related("provincia_entidad").first()

    contexto = {
        "configuracion": config,
        "padres": padres_lista,
        "padre_actual": padre_actual,
        "es_resumen_empresa": padre_actual is None,
        "columnas_14a": anexo14a.COLUMNAS_14A,
        "filas": aprobada["filas"],
        "total": aprobada["total"],
        "filas_fuera_plantilla": fuera["filas"],
        "total_fuera_plantilla": fuera["total"],
        # El bloque de firmas es el mismo parcial que el del Anexo 14; estas dos
        # claves son las que lo redirigen a esta vista.
        "filtros": {"director_ch_id": director_ch_id,
                    "director_gral_id": director_gral_id},
        "director_ch": director_ch,
        "director_gral": director_gral,
        "aspirantes_cuadro": (_queryset_aspirantes_cuadro()
                              if necesita_select_manual else Aspirante.objects.none()),
        "url_firmas": reverse("informes_anexo:anexo14a"),
        "url_excel_propio": "informes_anexo:anexo14a_excel",
        "nombre_informe": "Anexo 14A",
        "fecha_generacion": date.today(),
    }
    contexto.update(_cabecera_institucional(config, padre_actual))
    return contexto


class AnexoCatorceAView(PermisoAnexoMixin, TemplateView):
    """El 14-A en pantalla. Mismo alcance por rol que el Anexo 14."""

    template_name = "pages/informes_anexo/anexo14a.html"
    #: Solo el bloque de firmas, para las peticiones HTMX de los `<select>` de
    #: firmantes: elegir un firmante no cambia ni una cifra del resumen.
    template_name_firmas = "pages/informes_anexo/partials/bloque_firmas.html"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return [self.template_name_firmas]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_datos_anexo14a(self.request))
        context.update(_contexto_de_unidades(self.request))
        context["intercambio_oob"] = bool(getattr(self.request, "htmx", False))
        return context


# ==========================================================================
# LAS EXPORTACIONES: TRES LIBROS DEL MISMO MOLDE
# ==========================================================================

def _alcance_del_fichero(request, raices, elegidas):
    """Cómo se llama en el fichero lo que se está exportando.

    Desde que el selector admite varias unidades, el nombre no puede ser el de
    «la» unidad: con dos marcadas, cualquiera de los dos mentiría. Se dice lo que
    hay, y así el fichero archivado se explica solo sin tener que abrirlo.
    """
    if len(elegidas) == len(raices):
        return _marcador_de_unidades(request.user, raices)
    if len(elegidas) == 1:
        return elegidas[0].descripcion
    return "%d unidades" % len(elegidas)


def _datos_del_libro(request, modo):
    """Todo lo que necesita `excel.libro` para escribir, ya consultado.

    Aquí se consulta y allí se escribe. Es la misma separación que en el resto de
    Orbith: un módulo que sabe de ORM y otro que sabe de celdas.

    Las unidades SIN plantilla se dejan fuera del libro. Una hoja en blanco en un
    documento que se archiva no se lee como «esta unidad no tiene plazas», se lee
    como «aquí falta algo».
    """
    permitidas = _unidades_del_alcance(request.user)
    raices = _raices_del_alcance(request.user)
    elegidas = _unidades_elegidas(request, raices)
    filtros = _obtener_filtros(request)

    resumen = anexo14a.filas_de_empresa(elegidas, permitidas, filtros=filtros)
    resumen_fuera = anexo14a.filas_de_empresa(
        elegidas, permitidas, en_plantilla=False, filtros=filtros)

    # El detalle solo se construye si el libro lo lleva: cargar el árbol de cargos
    # de treinta unidades para un libro que solo trae conteos sería tirar el
    # trabajo, y es lo caro de toda la exportación.
    necesita_detalle = modo in (MODO_14, MODO_AMBOS)

    unidades = []
    for unidad in elegidas:
        conteo = anexo14a.filas_de_unidad(unidad, permitidas, filtros=filtros)
        conteo_fuera = anexo14a.filas_de_unidad(
            unidad, permitidas, en_plantilla=False, filtros=filtros)

        if not conteo["total"]["total"] and not conteo_fuera["total"]["total"]:
            continue

        entrada = {"unidad": unidad, "conteo": conteo, "conteo_fuera": conteo_fuera}
        if necesita_detalle:
            entrada["secciones"] = _secciones_por_unidad(
                _construir_hijas(unidad, filtros, permitidas=permitidas),
                _construir_hijas(unidad, filtros, en_plantilla=False,
                                 permitidas=permitidas),
            )
        unidades.append(entrada)

    config = Configuracion.objects.select_related("provincia_entidad").first()
    hoy = date.today()

    datos = {
        "unidades": unidades,
        "resumen": resumen,
        "resumen_fuera": resumen_fuera,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA,
        "fecha_generacion": hoy,
        "fecha_texto": hoy.strftime("%d/%m/%Y"),
        "alcance_fichero": _alcance_del_fichero(request, raices, elegidas),
        "filtrado": _hay_filtros_de_cargo(filtros),

        # Lo que `informes.excel._escribir_portada()` espera encontrar. Se
        # reutiliza esa función tal cual para que la portada de un Anexo sea la
        # misma que la de los siete informes de RRHH.
        "config": config,
        "nombre_empresa": config.nombre_empresa if config else "",
        "cab_unidades": [u["unidad"].descripcion for u in unidades],
        "municipio_resumen": (elegidas[0].municipio.nombre
                              if len(elegidas) == 1 and elegidas[0].municipio_id
                              else "—"),
        "cab_exportado_por": (getattr(request.user, "nombre_completo", None)
                              or getattr(request.user, "username", "") or "—"),
        "cifras_portada": [(nombre, resumen["total"][clave])
                           for clave, _, nombre, _ in anexo14a.COLUMNAS_14A],

        "director_ch": _resolver_firmante(
            NOMBRE_CARGO_DIRECTOR_CH, "Director{sufijo} de Capital Humano",
            filtros["director_ch_id"]),
        "director_gral": _resolver_firmante(
            NOMBRE_CARGO_DIRECTOR_GENERAL, "Director{sufijo} General",
            filtros["director_gral_id"]),
    }
    datos.update(_cabecera_institucional(config, elegidas[0] if len(elegidas) == 1 else None))

    # El total va el PRIMERO de las cifras de portada: es la que se busca.
    datos["cifras_portada"].insert(0, ("Total de plazas aprobadas",
                                       resumen["total"]["total"]))
    return datos


class ExportarAnexoExcelView(PermisoAnexoMixin, View):
    """Los tres libros: el Anexo 14 solo, el 14-A solo, y los dos juntos.

    Una sola vista y no tres porque lo único que cambia entre ellos es qué hojas
    de unidad se escriben; la portada, el Resumen y el alcance son idénticos.

    El libro trae lo elegido en el selector. Sin nada elegido, todo el alcance del
    usuario —que es el libro completo de siempre—: el selector dejó de ser un
    mando solo de pantalla el día que pudo marcar varias unidades.
    """

    #: Lo pone la URL. `MODO_AMBOS` es el fichero que imita al original de
    #: Capital Humano, con el 14 y el 14-A de cada unidad en el mismo libro.
    modo = MODO_14A

    def get(self, request, *args, **kwargs):
        modo = kwargs.get("modo") or self.modo
        datos = _datos_del_libro(request, modo)
        libro = libro_del_anexo(datos, modo)
        return respuesta_excel(
            libro, nombre_de_fichero(datos, modo, filtrado=datos["filtrado"]))


# ==========================================================================
# ANEXO 14-B — La plantilla de cargos con el registro de trabajadores
# ==========================================================================
# Se navega igual que los otros dos —mismo selector múltiple y mismas pestañas
# por unidad— pero su libro va APARTE: no entra en el combinado de 14 + 14A.
# Las cifras las arma `informes_anexo/anexo14b.py`.


def _datos_anexo14b(request):
    """El contexto de la pantalla del 14-B."""
    director_ch_id = request.GET.get("director_ch")
    director_gral_id = request.GET.get("director_gral")
    config = Configuracion.objects.select_related("provincia_entidad").first()

    director_ch = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_CH, "Director{sufijo} de Capital Humano", director_ch_id)
    director_gral = _resolver_firmante(
        NOMBRE_CARGO_DIRECTOR_GENERAL, "Director{sufijo} General", director_gral_id)
    necesita_select_manual = not director_ch["aspirante"] or not director_gral["aspirante"]

    contexto = {
        "configuracion": config,
        "filtros": {"director_ch_id": director_ch_id,
                    "director_gral_id": director_gral_id},
        "director_ch": director_ch,
        "director_gral": director_gral,
        "aspirantes_cuadro": (_queryset_aspirantes_cuadro()
                              if necesita_select_manual else Aspirante.objects.none()),
        "url_firmas": reverse("informes_anexo:anexo14b"),
        "url_excel_propio": "informes_anexo:anexo14b_excel",
        "nombre_informe": "Anexo 14B",
        "sin_combinado": True,
        # El 14-B no tiene filtros de cargo, así que su botón nunca pregunta.
        "hay_filtros_activos": False,
        "fecha_generacion": date.today(),
    }
    contexto.update(_cabecera_institucional(config, None))
    return contexto


class AnexoCatorceBView(PermisoAnexoMixin, TemplateView):
    """El 14-B en pantalla. Mismo alcance por rol que los otros dos."""

    template_name = "pages/informes_anexo/anexo14b.html"
    template_name_firmas = "pages/informes_anexo/partials/bloque_firmas.html"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return [self.template_name_firmas]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_datos_anexo14b(self.request))
        context.update(_contexto_de_unidades(self.request))
        context["intercambio_oob"] = bool(getattr(self.request, "htmx", False))
        return context


class PanelUnidadAnexo14BView(_PanelDeUnidadMixin, TemplateView):
    """El contenido de una pestaña del 14-B: las hojas de esa unidad."""

    template_name = "pages/informes_anexo/partials/panel_unidad_14b.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        unidad = self.unidad_o_404(request, kwargs["codigo"])
        permitidas = _unidades_del_alcance(request.user)

        context.update({
            "unidad": unidad,
            "hojas": anexo14b.hojas_de_unidad(unidad, permitidas),
        })
        return context


class ExportarAnexo14BExcelView(PermisoAnexoMixin, View):
    """El libro del 14-B: portada y una hoja por departamento de cada unidad.

    Va aparte del de 14 + 14A por decisión expresa. Y sin hoja de Resumen: ese
    conteo es el del 14-A y en un registro de trabajadores no dice gran cosa.
    """

    def get(self, request, *args, **kwargs):
        permitidas = _unidades_del_alcance(request.user)
        raices = _raices_del_alcance(request.user)
        elegidas = _unidades_elegidas(request, raices)
        config = Configuracion.objects.select_related("provincia_entidad").first()
        hoy = date.today()

        hojas = []
        for unidad in elegidas:
            for hoja in anexo14b.hojas_de_unidad(unidad, permitidas):
                hoja["unidad"] = unidad
                hojas.append(hoja)

        plazas = sum(len(h["filas"]) for h in hojas)
        ocupadas = sum(1 for h in hojas for f in h["filas"] if not f["vacante"])

        datos = {
            "hojas": hojas,
            "fecha_generacion": hoy,
            "fecha_texto": hoy.strftime("%d/%m/%Y"),
            "alcance_fichero": _alcance_del_fichero(request, raices, elegidas),
            # El divisor de la tarifa horaria. `CAlta` no la guarda: se deriva,
            # con la misma función que usa Pre-Nómina.
            "fondo_tiempo": (config.fondo_tiempo_calc_tarif if config else None),

            "config": config,
            "nombre_empresa": config.nombre_empresa if config else "",
            "cab_unidades": [u.descripcion for u in elegidas],
            "municipio_resumen": (elegidas[0].municipio.nombre
                                  if len(elegidas) == 1 and elegidas[0].municipio_id
                                  else "—"),
            "cab_exportado_por": (getattr(request.user, "nombre_completo", None)
                                  or getattr(request.user, "username", "") or "—"),
            "cifras_portada": [
                ("Plazas registradas", plazas),
                ("Cubiertas", ocupadas),
                ("Vacantes", plazas - ocupadas),
            ],
        }
        datos.update(_cabecera_institucional(
            config, elegidas[0] if len(elegidas) == 1 else None))

        libro = libro_del_anexo_14b(datos)
        nombre = nombre_de_fichero(datos, MODO_14B)
        return respuesta_excel(libro, nombre)
