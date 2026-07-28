"""
Vistas del módulo Informe Inteligente.
"""
import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .metadata import REGISTRO_MODELOS
from .motor import construir_queryset, obtener_rutas_select_related, ConfiguracionInformeInvalida
from .models import InformePersonalizado, InformeFavorito, UltimoInformeEjecutado

REGISTROS_POR_PAGINA = 50


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
        "ultimo_informe": ultimo,
        "favoritos": favoritos,
    }
    return render(request, "pages/informe_inteligente/index.html", context)


@login_required
def campos_del_modelo(request, modelo_raiz):
    """
    Endpoint HTMX: devuelve el panel de checkboxes de campos disponibles
    para el modelo raíz elegido. Se llama cuando el usuario cambia de
    modelo (por ahora solo hay CAlta, pero esto ya queda listo para
    cuando se añadan más modelos raíz).
    """
    definicion = REGISTRO_MODELOS.get(modelo_raiz)
    if not definicion:
        return JsonResponse({"error": "Modelo no reconocido"}, status=400)

    context = {
        "modelo_raiz": modelo_raiz,
        "campos": definicion["campos"],
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
    try:
        modelo_raiz = request.POST.get("modelo_raiz", "CAlta")
        configuracion = json.loads(request.POST.get("configuracion", "{}"))
        pagina_num = request.POST.get("pagina", 1)

        queryset = construir_queryset(modelo_raiz, configuracion, request.user)

        definicion_modelo = REGISTRO_MODELOS[modelo_raiz]
        rutas_precarga = obtener_rutas_select_related(definicion_modelo, configuracion.get("campos", []))
        if rutas_precarga:
            queryset = queryset.select_related(*rutas_precarga)

        paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
        pagina = paginator.get_page(pagina_num)

        # Preparar las filas: para cada registro, extraer el valor de cada
        # campo elegido según su ruta_orm (o ruta_visual si existe, como en
        # grupo_escala, donde se filtra por número pero se muestra el romano).
        filas = []
        for objeto in pagina.object_list:
            fila = {}
            for key in configuracion.get("campos", []):
                campo = definicion_modelo["campos"][key]
                ruta_para_mostrar = campo.get("ruta_visual") or campo["ruta_orm"] or key
                fila[key] = _resolver_valor_por_ruta(objeto, ruta_para_mostrar)
            filas.append(fila)

        # Recordar este informe como el último ejecutado por el usuario
        UltimoInformeEjecutado.objects.update_or_create(
            usuario=request.user,
            defaults={
                "modelo_raiz": modelo_raiz,
                "configuracion": configuracion,
                "total_registros": paginator.count,
            }
        )

        context = {
            "filas": filas,
            "campos_elegidos": [
                {"key": k, "label": definicion_modelo["campos"][k]["label"]}
                for k in configuracion.get("campos", [])
            ],
            "pagina": pagina,
            "paginator": paginator,
            "total_registros": paginator.count,
        }
        return render(request, "pages/informe_inteligente/partials/tabla_resultados.html", context)

    except ConfiguracionInformeInvalida as e:
        return render(request, "pages/informe_inteligente/partials/error_configuracion.html", {"error": str(e)}, status=400)


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
    modelo_raiz = request.POST.get("modelo_raiz")
    configuracion = json.loads(request.POST.get("configuracion", "{}"))

    if not nombre:
        return JsonResponse({"error": "El informe necesita un nombre."}, status=400)

    informe = InformePersonalizado.objects.create(
        nombre=nombre,
        modelo_raiz=modelo_raiz,
        configuracion=configuracion,
        usuario=request.user,
        es_plantilla=False,
    )
    InformeFavorito.objects.create(usuario=request.user, informe=informe)

    return JsonResponse({"ok": True, "informe_id": informe.id, "nombre": informe.nombre})