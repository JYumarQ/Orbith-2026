from django.contrib import messages

from .servicios import completar_tarea

# Content-Type real y consistente verificado en las vistas de exportación de
# informe_inteligente, informes_anexo y subsanacion. Se compara por
# Content-Type exacto en vez de parsear el nombre de archivo de
# Content-Disposition: 5 apps distintas escriben esa cabecera a mano con
# formatos ligeramente distintos, así que el Content-Type es la señal robusta.
MAPA_CONTENT_TYPE = {
    'application/pdf': 'primera_exportacion_pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'primera_exportacion_word',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'primera_exportacion_excel',
}


class DeteccionExportacionMiddleware:
    """Detecta la primera exportación PDF/Word/Excel del usuario sin tocar
    las 13 vistas de exportación repartidas por la aplicación.

    Colocado al final de MIDDLEWARE, después de MessageMiddleware (ver
    core/settings.py): messages.info() solo se persiste correctamente si se
    llama desde una capa que se ejecuta "después" de MessageMiddleware en la
    fase de respuesta.

    Nota UX: como la respuesta interceptada es una descarga binaria, el toast
    no aparece sobre la propia descarga — el usuario lo verá en su siguiente
    carga de página normal. Efecto secundario aceptable y conocido, no un bug.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        usuario = getattr(request, 'user', None)
        if usuario is None or not usuario.is_authenticated:
            return response

        if 'attachment' not in response.get('Content-Disposition', ''):
            return response

        content_type = response.get('Content-Type', '').split(';')[0].strip()
        codigo = MAPA_CONTENT_TYPE.get(content_type)
        if not codigo:
            return response

        tarea = completar_tarea(usuario, codigo)
        if tarea:
            messages.info(request, f"🧭 Nuevo en tu Guía de Orbith: {tarea.titulo}")

        return response
