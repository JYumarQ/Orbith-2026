"""
Vistas del módulo Informe Inteligente.
"""
import io
import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import get_template
from django.views.decorators.http import require_POST

from docx import Document
from docx.shared import Inches, RGBColor
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from xhtml2pdf import pisa

from configuracion.models import Configuracion
from nomencladores.models import SIGLAS_NIVEL_EDUCACIONAL
from strorganizativa.models import UnidadOrganizativa

from . import exportacion
from .documentos import documento_word_del_informe, libro_excel_del_informe
from .metadata import (
    REGISTRO_MODELOS,
    definicion_viva,
    PLANTILLAS_RAPIDAS,
    DESGLOSES_ESPECIALES_POR_MODELO,
    FUENTES_HISTORICAS,
    agrupar_campos_por_categoria,
    campos_sin_historico,
    es_campo_corto,
    mapa_valor_a_etiqueta,
    _opciones_periodos_cerrados,
)
from .motor import (
    construir_queryset,
    resolver_definicion,
    calcular_evolucion,
    indicadores_disponibles,
    indicadores_graficables,
    annos_con_cierre,
    calcular_indicadores,
    calcular_desglose,
    obtener_rutas_select_related,
    ConfiguracionInformeInvalida,
)
from .models import InformePersonalizado, InformeFavorito, UltimoInformeEjecutado

REGISTROS_POR_PAGINA = 50
MODELO_RAIZ_POR_DEFECTO = "CAlta"

MESES_ABREVIADOS = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AGO", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC",
}


from strorganizativa.jerarquia import ordenar_con_jerarquia
from strorganizativa.models import UnidadOrganizativa


def _contexto_index(request):
    """Contexto común de la pantalla principal.

    Extraído para que `ver_informe_compartido` renderice exactamente el mismo
    módulo (con sus favoritos, plantillas y paneles) y solo añada encima el
    informe que le compartieron, en vez de mantener una segunda pantalla casi
    idéntica que se iría desincronizando.
    """
    from usuarios.models import CustomUser

    return {
        "modelos_disponibles": {
            key: definicion["label"] for key, definicion in REGISTRO_MODELOS.items()
        },
        "modelo_raiz_inicial": MODELO_RAIZ_POR_DEFECTO,
        "ultimo_informe": UltimoInformeEjecutado.objects.filter(usuario=request.user).first(),
        "favoritos": InformeFavorito.objects.filter(
            usuario=request.user).select_related("informe"),
        # Las plantillas viajan al template como objeto Python: el filtro
        # json_script del template se encarga de serializarlas de forma segura,
        # porque quien las aplica es el JavaScript (marcar checkboxes, crear filtros).
        "plantillas": PLANTILLAS_RAPIDAS,
        "plantillas_del_modelo": PLANTILLAS_RAPIDAS.get(MODELO_RAIZ_POR_DEFECTO, []),
        # Destinatarios posibles al compartir. Cualquier usuario activo puede
        # recibir un informe: no hay riesgo de datos porque el alcance por rol se
        # aplica al ejecutarlo, según quién lo abre.
        "usuarios_para_compartir": CustomUser.objects.filter(
            is_active=True).exclude(pk=request.user.pk).order_by("username"),

        # --- Selector de período (parte superior de la pantalla) ---
        # Solo se ofrecen meses con un cierre realmente declarado: pedir uno
        # que nadie cerró devolvería un informe vacío sin explicación.
        "periodos_cerrados": _opciones_periodos_cerrados(),
        # Qué fuentes admiten consultar un mes pasado, y qué campos deja de
        # poder ofrecer cada una al hacerlo. El JavaScript lo usa para apagar
        # el selector o los checkboxes en vez de dejar que el usuario pida algo
        # que la fotografía no guardó.
        "soporte_historico": {
            clave: sorted(campos_sin_historico(clave)) for clave in FUENTES_HISTORICAS
        },
        # Medidas que el panel de evolución puede dibujar, por fuente.
        "medidas_evolucion": {
            clave: indicadores_graficables(clave) for clave in FUENTES_HISTORICAS
        },
        # Tarjetas de resumen que ofrece cada modelo. El usuario elige cuáles
        # quiere ver; antes se pintaban las dieciséis siempre y no había forma
        # de quitar las que no interesaban.
        "tarjetas_disponibles": {
            clave: indicadores_disponibles(clave) for clave in REGISTRO_MODELOS
        },

        # --- Selector de Unidad Organizativa (fila superior) ---
        # La unidad dejó de ser un filtro más de la lista y pasó a ser un
        # control fijo, junto a la fuente de datos y al desglose. El motivo es
        # que casi ningún informe se mira de la empresa entera: acotar por
        # unidad es la primera decisión que se toma, no una condición más.
        #
        # Ordenadas padre → hijas y con `nivel`, para que el desplegable pueda
        # indentar las subunidades. El alcance por rol NO se aplica aquí: lo
        # hace `motor._aplicar_alcance_por_rol` al ejecutar el informe, que es
        # donde no se puede esquivar.
        "unidades_organizativas": ordenar_con_jerarquia(
            UnidadOrganizativa.objects.select_related("padre")),
    }


@login_required
def index(request):
    """
    Pantalla principal del módulo: los paneles de configuración vacíos
    (o precargados con el último informe ejecutado, si existe) más la
    lista de favoritos del usuario en la barra lateral.
    """
    return render(request, "pages/informe_inteligente/index.html", _contexto_index(request))


@login_required
def campos_del_modelo(request, modelo_raiz):
    """
    Endpoint HTMX: devuelve el panel de checkboxes de campos disponibles
    para el modelo raíz elegido, agrupados por categoría. Se llama cuando
    el usuario cambia de modelo (por ahora solo hay CAlta, pero esto ya
    queda listo para cuando se añadan más modelos raíz).
    """
    definicion = definicion_viva(modelo_raiz)
    if not definicion:
        return JsonResponse({"error": "Modelo no reconocido"}, status=400)

    context = {
        "modelo_raiz": modelo_raiz,
        "categorias": agrupar_campos_por_categoria(definicion),
        "total_campos": len(definicion["campos"]),
        "desgloses_especiales": DESGLOSES_ESPECIALES_POR_MODELO.get(modelo_raiz, []),
    }
    return render(request, "pages/informe_inteligente/partials/panel_campos.html", context)


def _preparar_datos_informe(request):
    """
    Lee la configuración enviada por POST (modelo raíz + configuración JSON)
    y arma todo lo necesario para pintar o exportar un informe: definición
    del modelo, queryset ya filtrado, columnas elegidas e indicadores/
    desgloses. No pagina ni resuelve las filas — eso lo decide cada
    llamador (la vista previa solo necesita una página; las exportaciones
    necesitan el queryset completo).
    """
    modelo_raiz = request.POST.get("modelo_raiz", MODELO_RAIZ_POR_DEFECTO)
    configuracion = _leer_configuracion(request.POST.get("configuracion"))
    _obtener_definicion(modelo_raiz)  # valida que el modelo exista

    # Período del cierre elegido en el selector superior. Vacío = datos vivos,
    # que es como se comporta el módulo por defecto.
    periodo = (request.POST.get("periodo") or "").strip() or None
    if periodo and periodo not in dict(_opciones_periodos_cerrados()):
        raise ConfiguracionInformeInvalida(
            "El período seleccionado no tiene un cierre declarado.")

    # Con período, el informe se construye sobre la fotografía de ese mes: la
    # definición que manda a partir de aquí es la de la gemela histórica, no la
    # de la fuente viva (sus campos tienen otras rutas ORM).
    definicion_modelo, _ = resolver_definicion(modelo_raiz, periodo)

    queryset = construir_queryset(modelo_raiz, configuracion, request.user, periodo)
    keys_campos = configuracion["campos"]

    rutas_precarga = obtener_rutas_select_related(definicion_modelo, keys_campos)
    if rutas_precarga:
        queryset = queryset.select_related(*rutas_precarga)

    # ---- Panel de resumen: solo las tarjetas que el usuario haya pedido ----
    keys_tarjetas = _normalizar_lista(configuracion.get("tarjetas"))
    indicadores, total_registros = calcular_indicadores(
        queryset, definicion_modelo, modelo_raiz, keys_tarjetas)

    # Solo los desgloses que el usuario haya pedido. Antes, si no elegía
    # ninguno, se imponía el `desglose_por_defecto` del modelo —categoría
    # ocupacional en Contratos, causa de baja en Bajas—, y aparecía un desglose
    # que nadie había pedido y que no había forma de quitar: elegir «ninguno» no
    # se distinguía de no haber elegido todavía.
    keys_desglose = _normalizar_desglose(configuracion.get("desglosar_por"))
    desgloses = []
    for key_desglose in keys_desglose:
        filas_desglose, etiqueta = calcular_desglose(
            queryset, definicion_modelo, key_desglose, total_registros, modelo_raiz
        )
        desgloses.append({"clave": key_desglose, "etiqueta": etiqueta, "filas": filas_desglose})

    campos_elegidos = [
        {
            "key": k,
            "label": definicion_modelo["campos"][k]["label"],
            "tipo": definicion_modelo["campos"][k]["tipo"],
            # Los de contenido corto se centran, en la pantalla y en las tres
            # exportaciones. Se decide aquí, una vez, para que las cuatro
            # salidas alineen igual la misma columna.
            "corto": es_campo_corto(definicion_modelo["campos"][k], k),
        }
        for k in keys_campos
    ]

    return {
        "modelo_raiz": modelo_raiz,
        "periodo": periodo,
        "configuracion": configuracion,
        "definicion_modelo": definicion_modelo,
        "queryset": queryset,
        "keys_campos": keys_campos,
        "campos_elegidos": campos_elegidos,
        "indicadores": indicadores,
        "desgloses": desgloses,
        "total_registros": total_registros,
    }


# Campos que NO se traducen a su etiqueta larga sino a una forma corta, la
# misma en la pantalla y en los tres exportables. Las tablas viven en
# `nomencladores.models`, que es de donde las leen también los informes de RRHH.
_SIGLAS_POR_CAMPO = {
    "nivel_educ": dict(SIGLAS_NIVEL_EDUCACIONAL),
    "categoria_ocupacional": {"OPE": "O", "TEC": "T", "ADM": "A",
                              "SER": "S", "CDI": "C", "CEJ": "C"},
}


def _construir_filas(definicion_modelo, keys_campos, objetos):
    """
    Traduce cada objeto del queryset a un dict {clave_campo: valor_a_mostrar}.

    Para cada registro, extrae el valor de cada campo elegido según su
    ruta_orm (o ruta_visual si existe, como en grupo_escala, donde se
    filtra por número pero se muestra el romano). Los campos de opción se
    traducen a su etiqueta visible: en la tabla debe leerse "Cuadro", nunca
    el código CDI o CEJ. La usan tanto la vista previa como las
    exportaciones, para que muestren siempre lo mismo.
    """
    traducciones = {
        key: mapa_valor_a_etiqueta(definicion_modelo["campos"][key])
        for key in keys_campos
        if definicion_modelo["campos"][key]["tipo"] == "opcion"
    }

    # Tres campos NO se traducen a su etiqueta larga, sino a la forma corta que
    # usa la empresa. Se decide aquí, en el único sitio por el que pasan las
    # cuatro salidas —pantalla, Word, PDF y Excel—, para que digan lo mismo:
    #
    #   sexo                  «F» y «M», nunca «Femenino» ni «Masculino».
    #   nivel_educ            siglas, con MS(TM) y MS(DG) distinguiendo las dos
    #                         ramas de Medio Superior.
    #   categoria_ocupacional la inicial (O, T, A, S, C).
    #
    # El código guardado ya ES la sigla del sexo, así que basta con no traducir.
    for key in ("sexo", "cat_ocupacional"):
        traducciones.pop(key, None)
    for key in keys_campos:
        if key in ("nivel_educ", "categoria_ocupacional"):
            traducciones[key] = _SIGLAS_POR_CAMPO[key]
    # Los campos booleanos se muestran como "Sí"/"No" (más amigable que
    # True/False) en las 4 salidas del informe: tabla, PDF, Word y Excel.
    traducciones.update({
        key: {True: "Sí", False: "No"}
        for key in keys_campos
        if definicion_modelo["campos"][key]["tipo"] == "booleano"
    })

    filas = []
    for objeto in objetos:
        fila = {}
        for key in keys_campos:
            if key == "cumpleanos":
                # Campo compuesto (mes_nacimiento + dia_nacimiento, ver
                # motor.py): no tiene una única ruta ORM que recorrer.
                mes = getattr(objeto, "mes_nacimiento", None)
                dia = getattr(objeto, "dia_nacimiento", None)
                fila[key] = f"{dia:02d} {MESES_ABREVIADOS.get(mes, '')}" if mes and dia else None
                continue
            campo = definicion_modelo["campos"][key]
            ruta_para_mostrar = campo.get("ruta_visual") or campo["ruta_orm"] or key
            valor = _resolver_valor_por_ruta(objeto, ruta_para_mostrar)
            fila[key] = traducciones.get(key, {}).get(valor, valor)
        filas.append(fila)
    return filas


def _fecha_generacion_es():
    """Fecha/hora actual en español, mismo formato que usa el informe de Puestos Claves."""
    dt = datetime.now()
    meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
             'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return f"{dias[dt.weekday()]}, {dt.day:02d} de {meses[dt.month - 1]} de {dt.year} | {dt.strftime('%I:%M %p')}"


@login_required
@require_POST
def generar_vista_previa(request):
    """
    Endpoint HTMX principal: recibe la configuración del informe desde
    el formulario, construye el queryset, pagina, y devuelve el
    fragmento de tabla + contador + paginación.

    También actualiza el 'último informe ejecutado' del usuario.
    """
    pagina_num = request.POST.get("pagina", 1)

    try:
        datos = _preparar_datos_informe(request)

        # ---- Listado paginado ----
        paginator = Paginator(datos["queryset"], REGISTROS_POR_PAGINA)
        pagina = paginator.get_page(pagina_num)
        filas = _construir_filas(datos["definicion_modelo"], datos["keys_campos"], pagina.object_list)

        # Recordar este informe como el último ejecutado por el usuario
        UltimoInformeEjecutado.objects.update_or_create(
            usuario=request.user,
            defaults={
                "modelo_raiz": datos["modelo_raiz"],
                "configuracion": datos["configuracion"],
                "total_registros": datos["total_registros"],
            }
        )

        context = {
            "indicadores": datos["indicadores"],
            "desgloses": datos["desgloses"],
            "filas": filas,
            "campos_elegidos": datos["campos_elegidos"],
            "pagina": pagina,
            "paginator": paginator,
            "total_registros": datos["total_registros"],
        }

        from progreso.servicios import completar_tarea
        completar_tarea(request.user, 'primer_informe_generado')
        # Cambiar de página no es generar otro informe.
        if str(pagina_num) == '1':
            from ranking.models import Actividad
            from ranking.servicios import registrar_actividad
            registrar_actividad(request.user, Actividad.INFORME,
                                detalle=f'Informe Inteligente: {datos["modelo_raiz"]}')

        return render(request, "pages/informe_inteligente/partials/resultados.html", context)

    except ConfiguracionInformeInvalida as e:
        return render(
            request,
            "pages/informe_inteligente/partials/error_configuracion.html",
            {"error": str(e)},
            status=400,
        )


@login_required
@require_POST
def comprobar_exportacion(request):
    """Dice si el informe cabe en un documento, ANTES de generarlo.

    Lo consulta el navegador para poder preguntar en vez de que el usuario lo
    descubra con el fichero ya descargado y las columnas ilegibles. La medida
    del ancho necesita TODAS las filas, y el navegador solo tiene la primera
    página de la tabla, así que se resuelve aquí.
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return JsonResponse({"error": str(e)}, status=400)

    filas = _construir_filas(datos["definicion_modelo"], datos["keys_campos"],
                             datos["queryset"][:exportacion.LIMITE_DE_FILAS])
    return JsonResponse(exportacion.diagnostico(
        datos["campos_elegidos"],
        [[fila.get(c["key"]) for c in datos["campos_elegidos"]] for fila in filas],
        datos["total_registros"]))


def _contexto_de_exportacion(request, datos):
    """Todo lo que comparten el PDF, el Word y el Excel del módulo.

    La cabecera imita a la de Informes RRHH: logo, empresa, territorio, quién
    exporta y cuándo. El territorio se resuelve distinto porque aquí los filtros
    son libres: siempre la provincia de Parámetros Generales y, si entre las
    condiciones hay una de Unidad Organizativa, también la unidad.

    El MODO lo decide el usuario en el aviso previo:
      'completo'   todas las filas (informes pequeños);
      'recortado'  las primeras `LIMITE_DE_FILAS`, avisando de cuántas faltan;
      'resumen'    sin tabla: solo cifras y desgloses.
    """
    config = Configuracion.objects.first()
    definicion = datos["definicion_modelo"]

    modo = request.POST.get("modo") or "completo"
    if modo == "resumen":
        filas = []
    elif modo == "recortado":
        filas = _construir_filas(definicion, datos["keys_campos"],
                                 datos["queryset"][:exportacion.LIMITE_DE_FILAS])
    else:
        filas = _construir_filas(definicion, datos["keys_campos"],
                                 datos["queryset"])

    columnas = datos["campos_elegidos"]
    matriz = [[fila.get(c["key"]) for c in columnas] for fila in filas]
    pesos, _ = exportacion.repartir_anchos(columnas, matriz)

    # El ancho de cada columna en tanto por ciento, para la tabla del PDF.
    for columna, peso in zip(columnas, pesos):
        columna["ancho"] = round(peso * 100, 2)

    unidades = _unidades_del_informe(request, datos)

    return {
        "titulo_informe": definicion["label"],
        "informe_nombre": (request.POST.get("informe_nombre") or "").strip(),
        "informe_descripcion": (request.POST.get("informe_descripcion") or "").strip(),
        "filtros_aplicados": exportacion.describir_filtros(
            definicion, datos["configuracion"]),

        "campos_elegidos": columnas,
        "filas": filas,
        "matriz": matriz,
        "indicadores": datos["indicadores"],
        "desgloses": datos["desgloses"],
        "total_registros": datos["total_registros"],

        "modo": modo,
        "filas_mostradas": len(filas),
        "filas_omitidas": max(datos["total_registros"] - len(filas), 0),

        "config": config,
        "nombre_empresa": config.nombre_empresa if config else "Empresa Eléctrica",
        "cab_provincia": (config.provincia_entidad.nombre
                          if config and config.provincia_entidad_id else ""),
        "cab_unidades": unidades,
        "cab_unidades_resumen": ", ".join(unidades) if unidades else "Todas las unidades",
        "cab_exportado_por": (getattr(request.user, "nombre_completo", None)
                              or getattr(request.user, "username", "") or ""),
        "fecha_generacion": exportacion.fecha_generacion_es(),
        "periodo_texto": datos["periodo"] or "Información actual",
    }


def _unidades_del_informe(request, datos):
    """Las unidades filtradas, si las hay. Para la cabecera del documento.

    En Informes RRHH la unidad es un control fijo y siempre se sabe cuál es.
    Aquí viaja como un filtro más, así que hay que buscarla entre las
    condiciones; si no está, el informe es de toda la empresa.
    """
    ids = []
    for filtro in (datos["configuracion"].get("filtros") or []):
        if isinstance(filtro, dict) and filtro.get("campo") == "unidad_organizativa":
            valor = filtro.get("valor")
            ids.extend(valor if isinstance(valor, (list, tuple)) else [valor])

    ids = [str(v) for v in ids if str(v).isdigit()]
    if not ids:
        return []
    return list(UnidadOrganizativa.objects.filter(pk__in=ids)
                .order_by("orden_informe", "descripcion")
                .values_list("descripcion", flat=True))


def _nombre_de_descarga(context, extension):
    """«Escala_Salarial_24-10-2026.xlsx»: el nombre del informe, si lo tiene, y la
    fecha (core/nombres_descarga.py, 24-10-2026)."""
    from core.nombres_descarga import nombre_de_informe
    return nombre_de_informe(context["informe_nombre"] or "Informe_Inteligente",
                             extension=extension)


@login_required
@require_POST
def exportar_pdf(request):
    """El informe en PDF, con la misma imagen que los de RRHH."""
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    context = _contexto_de_exportacion(request, datos)
    html = get_template("pages/informe_inteligente/partials/informe_pdf.html").render(context)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        'attachment; filename="%s"' % _nombre_de_descarga(context, "pdf"))
    if pisa.CreatePDF(html, dest=response).err:
        return HttpResponse("Hubo un error al generar el PDF", status=500)
    return response


@login_required
@require_POST
def exportar_word(request):
    """El informe en Word.

    Se construye por código y no desde una plantilla `.docx` como los de RRHH:
    las plantillas de docxtpl repiten FILAS, y aquí el número de COLUMNAS lo
    elige el usuario en el panel de campos. No hay forma de expresar eso en una
    plantilla, así que la imagen se replica aquí.
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    context = _contexto_de_exportacion(request, datos)
    documento = documento_word_del_informe(context)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    response["Content-Disposition"] = (
        'attachment; filename="%s"' % _nombre_de_descarga(context, "docx"))
    documento.save(response)
    return response


@login_required
@require_POST
def exportar_excel(request):
    """El informe en Excel: portada, resumen y datos, como los de RRHH.

    Sin avisos de tamaño: una hoja de cálculo no pagina ni tiene ancho de papel,
    así que es justamente la salida a la que se invita cuando el informe no cabe
    en un documento. Va siempre completo.
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    # El modo que eligió el usuario vale para el PDF y el Word; aquí se ignora
    # a propósito. Si el Excel también recortara, el usuario se quedaría sin
    # NINGUNA forma de obtener el listado completo.
    request.POST = request.POST.copy()
    request.POST['modo'] = 'completo'

    context = _contexto_de_exportacion(request, datos)
    libro = libro_excel_del_informe(context)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = (
        'attachment; filename="%s"' % _nombre_de_descarga(context, "xlsx"))
    libro.save(response)
    return response

def _leer_configuracion(configuracion_cruda):
    """
    Convierte el JSON recibido del formulario en un diccionario validado.
    Lanza ConfiguracionInformeInvalida (nunca un error 500) si viene mal
    formado o vacío, para que el usuario reciba un mensaje en español.
    """
    try:
        configuracion = json.loads(configuracion_cruda or "{}")
    except (TypeError, ValueError):
        raise ConfiguracionInformeInvalida(
            "La configuración del informe llegó dañada. Vuelva a cargar la página."
        )

    if not isinstance(configuracion, dict):
        raise ConfiguracionInformeInvalida("La configuración del informe no tiene el formato esperado.")

    if not configuracion.get("campos"):
        raise ConfiguracionInformeInvalida("Debe seleccionar al menos un campo para mostrar en el informe.")

    return configuracion


def _normalizar_lista(valor):
    """Un valor de configuración que puede venir suelto o en lista, siempre en lista.

    'desglosar_por' era un string único antes de admitir varios campos, y hay
    favoritos y plantillas guardados con el formato viejo. Aceptar las dos
    formas evita una migración de datos y que un informe guardado hace meses
    deje de abrirse. 'tarjetas' nació ya como lista, pero usa la misma función
    para no tener dos maneras de leer lo mismo.
    """
    if not valor:
        return []
    return [valor] if isinstance(valor, str) else list(valor)


# Nombre anterior, conservado porque el resto del módulo lo usa por su nombre.
_normalizar_desglose = _normalizar_lista


def _obtener_definicion(modelo_raiz):
    """Busca el modelo raíz en el registro, con error controlado si no existe."""
    definicion = definicion_viva(modelo_raiz)
    if not definicion:
        raise ConfiguracionInformeInvalida(
            "El tipo de informe seleccionado ya no está disponible en el sistema."
        )
    return definicion


def _resolver_valor_por_ruta(objeto, ruta):
    """
    Recorre una ruta tipo 'aspirante__nombre' sobre un objeto Django,
    o la lee directamente si es un atributo simple o una anotación
    (como 'edad' o 'salario_actual').

    Si un paso intermedio es una relación ManyToMany (ej. 'familias' en
    Familia de Cargos), getattr devuelve un RelatedManager, no un valor:
    en ese caso se resuelve el resto de la ruta sobre cada elemento
    relacionado y se unen los resultados con coma.
    """
    valor = objeto
    partes = ruta.split("__")
    for i, parte in enumerate(partes):
        if valor is None:
            return None
        valor = getattr(valor, parte, None)
        if hasattr(valor, "all") and callable(valor.all):
            resto = partes[i + 1:]
            elementos = valor.all()
            if not resto:
                return ", ".join(str(e) for e in elementos)
            return ", ".join(str(_resolver_valor_por_ruta(e, "__".join(resto))) for e in elementos)
    return valor


@login_required
@require_POST
def guardar_favorito(request):
    """
    Guarda la configuración actual como InformePersonalizado y lo marca
    como favorito del usuario, en un solo paso (así lo pide el flujo del
    mockup: "Guardar como favorito" es una sola acción).
    """
    nombre = request.POST.get("nombre", "").strip()
    descripcion = request.POST.get("descripcion", "").strip()
    modelo_raiz = request.POST.get("modelo_raiz", MODELO_RAIZ_POR_DEFECTO)

    if not nombre:
        return JsonResponse({"error": "El informe necesita un nombre."}, status=400)
    if len(nombre) > 150:
        return JsonResponse({"error": "El nombre no puede superar los 150 caracteres."}, status=400)
    if modelo_raiz not in REGISTRO_MODELOS:
        return JsonResponse({"error": "El tipo de informe no es válido."}, status=400)

    try:
        configuracion = _leer_configuracion(request.POST.get("configuracion"))
    except ConfiguracionInformeInvalida as e:
        return JsonResponse({"error": str(e)}, status=400)

    informe = InformePersonalizado.objects.create(
        nombre=nombre,
        descripcion=descripcion or None,
        modelo_raiz=modelo_raiz,
        configuracion=configuracion,
        usuario=request.user,
        es_plantilla=False,
    )
    InformeFavorito.objects.create(usuario=request.user, informe=informe)

    from progreso.servicios import completar_tarea
    completar_tarea(request.user, 'primer_informe_favorito')

    return JsonResponse({"ok": True, "informe_id": informe.id, "nombre": informe.nombre})


@login_required
def cargar_favorito(request, informe_id):
    """
    Devuelve la configuración de un informe favorito para que el
    JavaScript repueble los paneles. Solo se puede cargar un informe
    que pertenezca al propio usuario.
    """
    informe = get_object_or_404(InformePersonalizado, pk=informe_id, usuario=request.user)
    return JsonResponse({
        "ok": True,
        "nombre": informe.nombre,
        "modelo_raiz": informe.modelo_raiz,
        "configuracion": informe.configuracion,
    })


@login_required
@require_POST
def editar_favorito(request, informe_id):
    """Renombra un informe guardado y, si se pide, reemplaza su configuración.

    Este endpoint es el que faltaba: `guardar_favorito` siempre hace `create()`,
    así que hasta ahora «editar» un favorito significaba guardarlo de nuevo y
    quedarse con dos copias del mismo informe.

    Renombrar y reemplazar la configuración son dos acciones separadas a
    propósito. Lo que hay en pantalla no tiene por qué ser este informe (se
    puede abrir el lápiz de un favorito teniendo cargado otro), así que
    arrastrar la configuración actual sin preguntar sobrescribiría el informe
    con algo que el usuario no pidió.
    """
    informe = get_object_or_404(InformePersonalizado, pk=informe_id, usuario=request.user)

    nombre = request.POST.get("nombre", "").strip()
    descripcion = request.POST.get("descripcion", "").strip()

    if not nombre:
        return JsonResponse({"error": "El informe necesita un nombre."}, status=400)
    if len(nombre) > 150:
        return JsonResponse({"error": "El nombre no puede superar los 150 caracteres."}, status=400)
    if len(descripcion) > 300:
        return JsonResponse({"error": "La descripción no puede superar los 300 caracteres."}, status=400)

    informe.nombre = nombre
    informe.descripcion = descripcion or None

    if request.POST.get("reemplazar_configuracion") == "true":
        modelo_raiz = request.POST.get("modelo_raiz", MODELO_RAIZ_POR_DEFECTO)
        if modelo_raiz not in REGISTRO_MODELOS:
            return JsonResponse({"error": "El tipo de informe no es válido."}, status=400)
        try:
            configuracion = _leer_configuracion(request.POST.get("configuracion"))
        except ConfiguracionInformeInvalida as e:
            return JsonResponse({"error": str(e)}, status=400)

        # `modelo_raiz` y `configuracion` se actualizan siempre juntos: los
        # campos y filtros guardados solo tienen sentido dentro de su propio
        # modelo, y dejar uno viejo con la otra nueva rompería el informe.
        informe.modelo_raiz = modelo_raiz
        informe.configuracion = configuracion

    informe.save()
    return JsonResponse({"ok": True, "informe_id": informe.id, "nombre": informe.nombre})


@login_required
@require_POST
def datos_evolucion(request):
    """Serie del gráfico de evolución mensual: un valor por cada mes cerrado.

    Va aparte de la vista previa porque es una lectura distinta: el informe
    mira un momento concreto y esto recorre todos los cierres. Solo se pide
    cuando el usuario despliega el panel, así que no encarece el informe normal.
    """
    modelo_raiz = request.POST.get("modelo_raiz", MODELO_RAIZ_POR_DEFECTO)
    _obtener_definicion(modelo_raiz)

    annos = annos_con_cierre()
    try:
        anno = int(request.POST.get("anno") or (annos[-1] if annos else 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "El año indicado no es válido."}, status=400)

    if anno not in annos:
        return JsonResponse({"error": "Ese año no tiene ningún cierre declarado."},
                            status=400)

    try:
        configuracion = _leer_configuracion(request.POST.get("configuracion"))
        puntos, etiqueta, formato = calcular_evolucion(
            modelo_raiz, configuracion, request.user,
            request.POST.get("indicador", "_total"), anno)
    except ConfiguracionInformeInvalida as e:
        return JsonResponse({"error": str(e)}, status=400)

    return JsonResponse({
        "ok": True,
        "anno": anno,
        "annos_disponibles": annos,
        "etiqueta": etiqueta,
        "formato": formato,
        "puntos": puntos,
    })


@login_required
@require_POST
def compartir_favorito(request, informe_id):
    """Envía un informe guardado a otros usuarios como notificación.

    No se crea una copia en los favoritos del receptor: eso le llenaría la lista
    de cosas que no pidió. Lo que recibe es un aviso con un botón «Ver informe»;
    si le interesa, lo guarda él mismo con «Guardar como favorito», que ya crea
    su propia copia independiente.

    La `Notificacion` es a la vez el aviso Y el permiso: `ver_informe_compartido`
    comprueba que exista una dirigida a quien intenta abrirlo, así que no hace
    falta un modelo aparte de «informes compartidos».

    Compartir no expone datos: el alcance por rol se aplica al EJECUTAR el
    informe (`motor._aplicar_alcance_por_rol`), según quién lo ejecuta y no
    según quién lo creó. Un Moderador que reciba un informe de otra unidad
    seguirá viendo solo los registros de las suyas.
    """
    from django.contrib.contenttypes.models import ContentType
    from notificaciones.models import Notificacion
    from usuarios.models import CustomUser

    informe = get_object_or_404(InformePersonalizado, pk=informe_id, usuario=request.user)

    ids_crudos = request.POST.getlist("destinatarios")
    ids = {int(i) for i in ids_crudos if str(i).isdigit()}
    ids.discard(request.user.pk)  # compartir consigo mismo no tiene sentido

    if not ids:
        return JsonResponse({"error": "Seleccione al menos un usuario."}, status=400)

    destinatarios = list(CustomUser.objects.filter(pk__in=ids, is_active=True))
    if not destinatarios:
        return JsonResponse({"error": "Los usuarios seleccionados ya no están activos."}, status=400)

    quien = request.user.get_full_name() or request.user.username
    tipo_ct = ContentType.objects.get_for_model(InformePersonalizado)
    etiqueta_modelo = REGISTRO_MODELOS.get(informe.modelo_raiz, {}).get("label", informe.modelo_raiz)

    mensaje = (
        f'{quien} le compartió el informe «{informe.nombre}» '
        f'({etiqueta_modelo}). Ábralo con «Ver informe»; si le resulta útil, '
        f'puede guardarlo en sus propios favoritos.'
    )
    if informe.descripcion:
        mensaje = f'{mensaje}\n\n{informe.descripcion}'

    # `codigo_regla` vacío (es un EVENTO, no un hallazgo): la restricción de
    # unicidad de Notificacion no aplica, así que compartir dos veces el mismo
    # informe genera dos avisos — y está bien, son dos hechos distintos.
    Notificacion.objects.bulk_create([
        Notificacion(
            titulo=f'Informe compartido: {informe.nombre}'[:150],
            mensaje=mensaje,
            tipo=Notificacion.Tipo.EVENTO,
            content_type=tipo_ct,
            object_id=str(informe.pk),
            destinatario=usuario,
        )
        for usuario in destinatarios
    ])

    return JsonResponse({"ok": True, "enviados": len(destinatarios)})


@login_required
def ver_informe_compartido(request, informe_id):
    """Abre el módulo con un informe que otro usuario compartió.

    El permiso es la propia notificación: solo puede abrirlo quien tenga una
    dirigida a él apuntando a este informe. Sin ella responde 404, igual que si
    intentara abrir un favorito ajeno.
    """
    from django.contrib.contenttypes.models import ContentType
    from notificaciones.models import Notificacion

    informe = get_object_or_404(InformePersonalizado, pk=informe_id)

    le_fue_compartido = Notificacion.objects.filter(
        content_type=ContentType.objects.get_for_model(InformePersonalizado),
        object_id=str(informe.pk),
        destinatario=request.user,
    ).exists()

    # El dueño siempre puede abrir el suyo, aunque nadie se lo haya compartido.
    if not le_fue_compartido and informe.usuario_id != request.user.pk:
        raise Http404("Este informe no está compartido con usted.")

    contexto = _contexto_index(request)
    contexto["informe_compartido"] = informe
    contexto["compartido_por"] = (
        informe.usuario.get_full_name() or informe.usuario.username
    ) if informe.usuario else "Orbith"
    return render(request, "pages/informe_inteligente/index.html", contexto)


@login_required
@require_POST
def eliminar_favorito(request, informe_id):
    """Elimina un informe guardado por el propio usuario."""
    informe = get_object_or_404(InformePersonalizado, pk=informe_id, usuario=request.user)
    informe.delete()  # borra en cascada su fila de InformeFavorito
    return JsonResponse({"ok": True})
