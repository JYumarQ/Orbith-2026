import json
from urllib.parse import quote, unquote

from django.conf import settings

from .servicios import abrir_logros, cerrar_logros, completar_parte, completar_tarea

# Cookie con los logros recién conseguidos. La lee `static/js/progreso_guia.js`
# (por eso NO es HttpOnly), muestra el aviso y la borra. Solo lleva títulos de
# tareas de la Guía, nada sensible, y caduca sola en dos minutos.
COOKIE_LOGROS = 'orbith_logros'
DURACION_COOKIE_LOGROS = 120

# Formato de cada documento por su Content-Type. Se mira el Content-Type y no
# el nombre del fichero: cada app escribe Content-Disposition a su manera.
FORMATO_POR_CONTENT_TYPE = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
}

# Tareas de la categoría "Exportar" que se reconocen por la RUTA de la vista
# (`request.resolver_match.view_name`). El valor es (código de tarea, parte):
# la parte es None si la tarea no tiene avance, una lista si una descarga
# cuenta para varias partes, o una función del request.
EXPORTACION_POR_RUTA = {
    'exportar_contratos_excel': ('exportar_lista_contratos', None),
    # El mismo formulario exporta el Contrato de Trabajo o la Modificación.
    'exportar_contrato_word': ('exportar_contrato_modificacion',
                               lambda request: 'modificacion'
                               if request.POST.get('tipo_documento') == 'modificacion' else 'creacion'),
    # El documento del movimiento de nómina: desde el histórico ("Exportar
    # Movimiento") o al confirmar un alta, un movimiento o una baja.
    'imprimir_modelo_movimiento': ('exportar_movimiento_nomina', None),
    'imprimir_movimiento': ('exportar_movimiento_nomina', None),
    # "Exportar Todo" del histórico. Se abre en otra pestaña (inline): por eso
    # no se exige `attachment`.
    'exportar_historico_pdf': ('exportar_historico_trabajador', None),
    'informes_anexo:anexo17_excel': ('exportar_anexos', '17'),
    'informes_anexo:anexo17_1_excel': ('exportar_anexos', '17_1'),
    'informes_anexo:anexo17_2_excel': ('exportar_anexos', '17_2'),
    # El libro combinado lleva el 17 y el 17.1.
    'informes_anexo:anexo_excel_combinado': ('exportar_anexos', ['17', '17_1']),
    'prenomina:exportar_reporte': ('exportar_prenomina', None),
}

# Secciones cuyas exportaciones cuentan por FORMATO (PDF, Word y Excel): se
# reconocen por el módulo de la vista, que es el mismo para todas las suyas.
EXPORTACION_POR_MODULO = {
    'informe_inteligente.views': 'exportar_informe_inteligente',
    'informes.views': 'exportar_informes_rrhh',
}


# Buscadores con prefijos (E:, N:, CI:…, ver `core/busqueda.py`): la ruta que
# atiende cada uno, el parámetro con lo escrito y los prefijos que entiende
# (los mismos que `bolsa.views.PREFIJOS_*`, `contratos.views.PREFIJOS_CONTRATOS`
# y el `data-prefijos` del buscador de Subsanación). Un prefijo que esa pantalla
# no entiende no filtra nada, así que no cuenta.
BUSQUEDA_POR_RUTA = {
    'search_aspirantes': ('filter_aspirante', {'N', 'CI', 'U'}),
    'search_bajas': ('filter_aspirante', {'E', 'N', 'CI', 'CA', 'U'}),
    'search_contrato': ('filter_contrato', {'E', 'N', 'CI', 'CA', 'U'}),
    'subsanacion:panel_hallazgos': ('q', {'E', 'N', 'CI', 'CA', 'U', 'COD'}),
}


def busco_con_prefijo(request):
    """True si la petición es una búsqueda que usa un prefijo válido en su pantalla."""
    coincidencia = getattr(request, 'resolver_match', None)
    regla = coincidencia and BUSQUEDA_POR_RUTA.get(coincidencia.view_name)
    if not regla:
        return False
    parametro, validos = regla
    texto = request.GET.get(parametro, '')
    if ':' not in texto:
        return False
    from core.busqueda import interpretar
    return bool(set(interpretar(texto).prefijos) & validos)


def partes_de_exportacion(request, formato):
    """Lista de (código de tarea, parte) que cuenta esta descarga."""
    coincidencia = getattr(request, 'resolver_match', None)
    if coincidencia is None:
        return []
    regla = EXPORTACION_POR_RUTA.get(coincidencia.view_name)
    if regla:
        codigo, parte = regla
        if callable(parte):
            parte = parte(request)
        partes = parte if isinstance(parte, list) else [parte]
        return [(codigo, p) for p in partes]
    codigo = EXPORTACION_POR_MODULO.get(getattr(coincidencia.func, '__module__', ''))
    return [(codigo, formato)] if codigo else []


class DeteccionExportacionMiddleware:
    """Reconoce las exportaciones de la categoría "Exportar" de la Guía sin
    tocar las vistas de exportación repartidas por la aplicación.

    Cuenta una respuesta correcta (200) con un documento PDF, Word o Excel, y
    la atribuye a su sección por la ruta de la vista: un PDF de Informes RRHH
    no cuenta para el Informe Inteligente.

    Va DESPUÉS de `LogrosGuiaMiddleware` en MIDDLEWARE (ver core/settings.py):
    así esta detección ocurre mientras aquel sigue recogiendo logros, y el
    aviso llega al navegador con la propia descarga.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated or response.status_code != 200:
            return response

        # Tarea "Busca con prefijos" (Explorar): aquí y no en las vistas de
        # búsqueda, igual que las exportaciones, para no tocar cuatro vistas.
        if busco_con_prefijo(request):
            completar_tarea(usuario, 'primera_busqueda_prefijos')
            return response

        content_type = response.get('Content-Type', '').split(';')[0].strip()
        formato = FORMATO_POR_CONTENT_TYPE.get(content_type)
        if not formato:
            return response

        for codigo, parte in partes_de_exportacion(request, formato):
            completar_parte(usuario, codigo, parte)

        return response


class LogrosGuiaMiddleware:
    """Entrega al navegador, al momento, los logros de la Guía conseguidos en
    cada petición.

    `completar_tarea` anota los logros mientras este middleware los recoge
    (ver `progreso.servicios.abrir_logros`). Al terminar la petición, si hubo
    alguno, se guardan en la cookie `orbith_logros`.

    Una cookie y no `messages.info()` porque muchas tareas se completan en
    peticiones que no pintan una página: un fragmento HTMX (abrir la columna
    de Contratos), un JSON (enviar un reporte) o una descarga (exportar a
    PDF). Con `messages` el aviso esperaba a la siguiente página completa.
    El navegador recibe la cookie con CUALQUIER respuesta, incluida una
    descarga o una redirección, y `progreso_guia.js` la mira una vez por
    segundo sin hacer ninguna petición: el aviso sale al instante y la
    aplicación no se vuelve más pesada.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated:
            return self.get_response(request)

        token = abrir_logros(usuario)
        try:
            response = self.get_response(request)
        finally:
            logros = cerrar_logros(token)

        if logros:
            # Puede quedar en la cookie un logro que el navegador aún no leyó
            # (dos peticiones seguidas): se suman en vez de pisarse. El
            # navegador recuerda los `id` ya mostrados, así que no se repiten.
            try:
                anteriores = json.loads(unquote(request.COOKIES.get(COOKIE_LOGROS, '') or '[]'))
            except ValueError:
                anteriores = []
            if not isinstance(anteriores, list):
                anteriores = []
            response.set_cookie(
                COOKIE_LOGROS,
                quote(json.dumps(anteriores + logros, ensure_ascii=False)),
                max_age=DURACION_COOKIE_LOGROS,
                samesite='Lax',
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=False,
            )
        return response
