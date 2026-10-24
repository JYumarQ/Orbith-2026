from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import ImagenReporteProblema, ReporteProblema


class ImagenReporteProblemaInline(admin.TabularInline):
    model = ImagenReporteProblema
    extra = 0
    readonly_fields = ('imagen', 'fecha_subida')
    can_delete = False


@admin.register(ReporteProblema)
class ReporteProblemaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'soporte'
    list_display = ('fecha_creado', 'usuario', 'estado', 'url_origen')
    list_filter = ('estado', 'fecha_creado')
    search_fields = ('mensaje', 'error_consola', 'usuario__username')
    list_select_related = ('usuario',)
    readonly_fields = (
        'usuario', 'mensaje', 'error_consola', 'url_origen',
        'fecha_creado', 'fecha_actualizado',
    )
    inlines = (ImagenReporteProblemaInline,)


from django.http import FileResponse, Http404  # noqa: E402
from django.template.response import TemplateResponse  # noqa: E402
from django.urls import path  # noqa: E402

from core import registro_errores  # noqa: E402

from .models import RegistroErrores  # noqa: E402

#: Lo que se muestra en pantalla de un fichero grande: el final, que es lo último.
MAXIMO_EN_PANTALLA = 200_000


@admin.register(RegistroErrores)
class RegistroErroresAdmin(admin.ModelAdmin):
    """Los ficheros del registro de errores: lista de días, contenido y descarga.
    Solo para el Administrador de Orbith (o un superusuario de Django)."""

    def _puede(self, request):
        usuario = request.user
        return usuario.is_active and (usuario.is_superuser or getattr(usuario, 'es_admin', False))

    def has_module_permission(self, request):
        return self._puede(request)

    def has_view_permission(self, request, obj=None):
        return self._puede(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path('descargar/<str:nombre>/', self.admin_site.admin_view(self.descargar),
                 name='soporte_registroerrores_descargar'),
        ] + super().get_urls()

    def _fichero(self, nombre):
        for fichero in registro_errores.ficheros():
            if fichero.name == nombre:  # solo nombres de la lista: nada de rutas
                return fichero
        return None

    def changelist_view(self, request, extra_context=None):
        if not self._puede(request):
            raise Http404
        registro_errores.borrar_antiguos()
        ficheros = registro_errores.ficheros()
        elegido = self._fichero(request.GET.get('f', '')) or (ficheros[0] if ficheros else None)
        contenido, recortado = '', False
        if elegido:
            datos = elegido.read_bytes()
            recortado = len(datos) > MAXIMO_EN_PANTALLA
            contenido = datos[-MAXIMO_EN_PANTALLA:].decode('utf-8', errors='replace')
        contexto = {
            **self.admin_site.each_context(request),
            'title': 'Registro de errores',
            'opts': self.model._meta,
            'ficheros': [{'nombre': f.name, 'kb': max(1, round(f.stat().st_size / 1024))}
                         for f in ficheros],
            'elegido': elegido.name if elegido else '',
            'contenido': contenido,
            'recortado': recortado,
            'dias': registro_errores.DIAS_QUE_SE_GUARDAN,
            'carpeta_ok': bool(str(registro_errores.carpeta())) and registro_errores.carpeta().is_dir(),
        }
        return TemplateResponse(request, 'admin/soporte/registro_errores.html', contexto)

    def descargar(self, request, nombre):
        if not self._puede(request):
            raise Http404
        fichero = self._fichero(nombre)
        if fichero is None:
            raise Http404
        return FileResponse(open(fichero, 'rb'), as_attachment=True, filename=fichero.name,
                            content_type='text/plain; charset=utf-8')


from .models import DiagnosticoServidor  # noqa: E402


@admin.register(DiagnosticoServidor)
class DiagnosticoServidorAdmin(RegistroErroresAdmin):
    """Dónde guarda Orbith los ficheros subidos, si existen y quién los sirve.
    Mismos permisos que el Registro de errores: solo el Administrador."""

    def get_urls(self):
        return admin.ModelAdmin.get_urls(self)

    def changelist_view(self, request, extra_context=None):
        if not self._puede(request):
            raise Http404
        from core import diagnostico
        contexto = {
            **self.admin_site.each_context(request),
            'title': 'Diagnóstico del servidor',
            'opts': self.model._meta,
            'd': diagnostico.datos(),
            'url_prueba': diagnostico.escribir_fichero_de_prueba(),
        }
        return TemplateResponse(request, 'admin/soporte/diagnostico.html', contexto)
