"""
Vistas del módulo Informe Inteligente.
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .metadata import (
    REGISTRO_MODELOS,
    PLANTILLAS_RAPIDAS,
    agrupar_campos_por_categoria,
    mapa_valor_a_etiqueta,
)
from .motor import (
    construir_queryset,
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


@login_required
def index(request):
    """
    Pantalla principal del módulo: los paneles de configuración vacíos
    (o precargados con el último informe ejecutado, si existe) más la
    lista de favoritos del usuario en la barra lateral.
    """
    ultimo = UltimoInformeEjecutado.objects.filter(usuario=request.user).first()
    favoritos = InformeFavorito.objects.filter(usuario=request.user).select_related("informe")

    context = {
        "modelos_disponibles": {
            key: definicion["label"] for key, definicion in REGISTRO_MODELOS.items()
        },
        "modelo_raiz_inicial": MODELO_RAIZ_POR_DEFECTO,
        "ultimo_informe": ultimo,
        "favoritos": favoritos,
        # Las plantillas viajan al template como objeto Python: el filtro
        # json_script del template se encarga de serializarlas de forma segura,
        # porque quien las aplica es el JavaScript (marcar checkboxes, crear filtros).
        "plantillas": PLANTILLAS_RAPIDAS,
        "plantillas_del_modelo": PLANTILLAS_RAPIDAS.get(MODELO_RAIZ_POR_DEFECTO, []),
    }
    return render(request, "pages/informe_inteligente/index.html", context)


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
    }
    return render(request, "pages/informe_inteligente/partials/panel_campos.html", context)


@login_required
@require_POST
def generar_vista_previa(request):
    """
    Endpoint HTMX principal: recibe la configuración del informe desde
    el formulario, construye el queryset, pagina, y devuelve el
    fragmento de tabla + contador + paginación.

    También actualiza el 'último informe ejecutado' del usuario.
    """
    modelo_raiz = request.POST.get("modelo_raiz", MODELO_RAIZ_POR_DEFECTO)
    pagina_num = request.POST.get("pagina", 1)

    try:
        configuracion = _leer_configuracion(request.POST.get("configuracion"))
        definicion_modelo = _obtener_definicion(modelo_raiz)

        queryset = construir_queryset(modelo_raiz, configuracion, request.user)
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
            filas, etiqueta = calcular_desglose(queryset, definicion_modelo, key_desglose, total_registros)
            desgloses.append({"etiqueta": etiqueta, "filas": filas})

        # ---- Listado paginado ----
        paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
        pagina = paginator.get_page(pagina_num)

        # Preparar las filas: para cada registro, extraer el valor de cada
        # campo elegido según su ruta_orm (o ruta_visual si existe, como en
        # grupo_escala, donde se filtra por número pero se muestra el romano).
        # Los campos de opción se traducen a su etiqueta visible: en la tabla
        # debe leerse "Cuadro", nunca el código CDI o CEJ.
        traducciones = {
            key: mapa_valor_a_etiqueta(definicion_modelo["campos"][key])
            for key in keys_campos
            if definicion_modelo["campos"][key]["tipo"] == "opcion"
        }

        filas = []
        for objeto in pagina.object_list:
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

        # Recordar este informe como el último ejecutado por el usuario
        UltimoInformeEjecutado.objects.update_or_create(
            usuario=request.user,
            defaults={
                "modelo_raiz": modelo_raiz,
                "configuracion": configuracion,
                "total_registros": total_registros,
            }
        )

        context = {
            "indicadores": indicadores,
            "desgloses": desgloses,
            "filas": filas,
            "campos_elegidos": [
                {
                    "key": k,
                    "label": definicion_modelo["campos"][k]["label"],
                    "tipo": definicion_modelo["campos"][k]["tipo"],
                }
                for k in keys_campos
            ],
            "pagina": pagina,
            "paginator": paginator,
            "total_registros": total_registros,
        }
        return render(request, "pages/informe_inteligente/partials/resultados.html", context)

    except ConfiguracionInformeInvalida as e:
        return render(
            request,
            "pages/informe_inteligente/partials/error_configuracion.html",
            {"error": str(e)},
            status=400,
        )


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
    """
    valor = objeto
    for parte in ruta.split("__"):
        if valor is None:
            return None
        valor = getattr(valor, parte, None)
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
def eliminar_favorito(request, informe_id):
    """Elimina un informe guardado por el propio usuario."""
    informe = get_object_or_404(InformePersonalizado, pk=informe_id, usuario=request.user)
    informe.delete()  # borra en cascada su fila de InformeFavorito
    return JsonResponse({"ok": True})
