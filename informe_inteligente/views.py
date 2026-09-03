"""
Vistas del módulo Informe Inteligente.
"""
import io
import json
import re
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

from .metadata import (
    REGISTRO_MODELOS,
    PLANTILLAS_RAPIDAS,
    DESGLOSES_ESPECIALES_POR_MODELO,
    FUENTES_HISTORICAS,
    agrupar_campos_por_categoria,
    campos_sin_historico,
    mapa_valor_a_etiqueta,
    _opciones_periodos_cerrados,
)
from .motor import (
    construir_queryset,
    resolver_definicion,
    calcular_evolucion,
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
    definicion = REGISTRO_MODELOS.get(modelo_raiz)
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

    # ---- Panel de resumen: se calcula SIEMPRE, encima de la tabla ----
    indicadores, total_registros = calcular_indicadores(queryset, definicion_modelo, modelo_raiz)

    keys_desglose = _normalizar_desglose(
        configuracion.get("desglosar_por") or definicion_modelo.get("desglose_por_defecto")
    )
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
        tarea = completar_tarea(request.user, 'primer_informe_generado')
        if tarea:
            messages.info(request, f"🧭 Nuevo en tu Guía de Orbith: {tarea.titulo}")

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
def exportar_pdf(request):
    """
    Exporta a PDF exactamente lo que el usuario configuró en pantalla
    (mismos filtros, columnas y orden que la vista previa), con el logo,
    nombre de empresa y fecha en el mismo estilo que usa la exportación
    del Informe de Puestos Claves (`informes/views.py::ExportarPuestosClavePDFView`).
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    filas = _construir_filas(datos["definicion_modelo"], datos["keys_campos"], datos["queryset"])

    config = Configuracion.objects.first()
    context = {
        "titulo_informe": datos["definicion_modelo"]["label"],
        "campos_elegidos": datos["campos_elegidos"],
        "filas": filas,
        "total_registros": datos["total_registros"],
        "config": config,
        "nombre_empresa": config.nombre_empresa if config else "Empresa Eléctrica",
        "fecha_generacion": _fecha_generacion_es(),
    }

    template = get_template("pages/informe_inteligente/partials/informe_pdf.html")
    html = template.render(context)

    response = HttpResponse(content_type="application/pdf")
    filename = f'Informe_Inteligente_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse("Hubo un error al generar el PDF", status=500)
    return response


@login_required
@require_POST
def exportar_word(request):
    """
    Igual que `exportar_pdf` pero en Word. Se genera directamente con
    python-docx (sin plantilla .docx externa) porque el mecanismo de
    plantilla que usa Puestos Claves (docxtpl) depende de un archivo
    .docx que no existe en el repositorio.
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    filas = _construir_filas(datos["definicion_modelo"], datos["keys_campos"], datos["queryset"])
    campos_elegidos = datos["campos_elegidos"]

    config = Configuracion.objects.first()
    nombre_empresa = config.nombre_empresa if config else "Empresa Eléctrica"

    documento = Document()

    if config and config.logo:
        try:
            documento.add_picture(config.logo.path, width=Inches(1.0))
        except Exception:
            pass  # sin logo físico disponible: el documento se genera igual

    encabezado = documento.add_heading(nombre_empresa, level=1)
    encabezado.runs[0].font.color.rgb = RGBColor(0x1e, 0x3a, 0x8a)

    subtitulo = documento.add_paragraph()
    run_subtitulo = subtitulo.add_run("Gestión de Capital Humano")
    run_subtitulo.font.color.rgb = RGBColor(0xea, 0x58, 0x0c)
    run_subtitulo.font.bold = True

    documento.add_heading(datos["definicion_modelo"]["label"], level=2)

    meta = documento.add_paragraph()
    meta.add_run(
        f'Generado: {_fecha_generacion_es()}  |  Total de registros: {datos["total_registros"]}'
    ).italic = True

    tabla = documento.add_table(rows=1, cols=len(campos_elegidos))
    tabla.style = "Light Grid Accent 1"

    celdas_cabecera = tabla.rows[0].cells
    for i, campo in enumerate(campos_elegidos):
        celdas_cabecera[i].text = campo["label"]
        for parrafo in celdas_cabecera[i].paragraphs:
            for run in parrafo.runs:
                run.font.bold = True

    for fila in filas:
        celdas = tabla.add_row().cells
        for i, campo in enumerate(campos_elegidos):
            valor = fila.get(campo["key"])
            celdas[i].text = "" if valor in (None, "") else str(valor)

    buffer = io.BytesIO()
    documento.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    filename = f'Informe_Inteligente_{datetime.now().strftime("%Y%m%d_%H%M")}.docx'
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def exportar_excel(request):
    """
    Igual que `exportar_pdf`/`exportar_word` pero en Excel, con `openpyxl`
    (misma librería que ya usa `contratos/views.py::exportar_contratos_excel`
    para sus exportaciones). Las columnas son dinámicas: salen de
    `campos_elegidos`, no de una lista fija como en Contratos.
    """
    try:
        datos = _preparar_datos_informe(request)
    except ConfiguracionInformeInvalida as e:
        return HttpResponse(str(e), status=400)

    filas = _construir_filas(datos["definicion_modelo"], datos["keys_campos"], datos["queryset"])
    campos_elegidos = datos["campos_elegidos"]

    wb = openpyxl.Workbook()
    ws = wb.active
    # Excel limita el nombre de hoja a 31 caracteres y prohíbe \ / * ? : [ ]
    # (el label del modelo, p. ej. "Contratos / Trabajadores Activos", trae "/").
    titulo_hoja = re.sub(r'[\\/*?:\[\]]', '-', datos["definicion_modelo"]["label"])[:31]
    ws.title = titulo_hoja

    negrita_blanca = Font(bold=True, color="FFFFFF")
    fondo_indigo = PatternFill(start_color="696CFF", end_color="696CFF", fill_type="solid")
    alineacion_centro = Alignment(horizontal="center", vertical="center")

    ws.append([campo["label"] for campo in campos_elegidos])
    for col_num, cell in enumerate(ws[1], 1):
        cell.font = negrita_blanca
        cell.fill = fondo_indigo
        cell.alignment = alineacion_centro
        ws.column_dimensions[get_column_letter(col_num)].width = 22

    for fila in filas:
        ws.append([fila.get(campo["key"]) if fila.get(campo["key"]) not in (None, "") else "" for campo in campos_elegidos])

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    filename = f'Informe_Inteligente_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
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


def _normalizar_desglose(valor):
    """
    'desglosar_por' era un string único; ahora admite varios campos a la vez.
    Esta función acepta ambas formas para que favoritos y plantillas rápidas
    guardados con el formato viejo (string) sigan funcionando sin migración:
    un string se envuelve en una lista de un elemento, una lista se usa tal cual.
    """
    if not valor:
        return []
    return [valor] if isinstance(valor, str) else list(valor)


def _obtener_definicion(modelo_raiz):
    """Busca el modelo raíz en el registro, con error controlado si no existe."""
    definicion = REGISTRO_MODELOS.get(modelo_raiz)
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
    tarea = completar_tarea(request.user, 'primer_informe_favorito')
    if tarea:
        messages.info(request, f"🧭 Nuevo en tu Guía de Orbith: {tarea.titulo}")

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
