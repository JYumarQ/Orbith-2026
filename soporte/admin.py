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
from django.urls import path, reverse  # noqa: E402

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


from .models import CopiaBaseDatos  # noqa: E402


@admin.register(CopiaBaseDatos)
class CopiaBaseDatosAdmin(RegistroErroresAdmin):
    """Copia completa de la base para el desarrollador (18-11-2026): se prepara en un
    proceso aparte y luego se descarga. Mismos permisos que el Registro de errores (solo
    el Administrador) y cada copia preparada o descargada queda en Auditoría."""

    def get_urls(self):
        return [
            path('preparar/', self.admin_site.admin_view(self.preparar),
                 name='soporte_copiabasedatos_preparar'),
            path('descargar/<str:nombre>/', self.admin_site.admin_view(self.descargar),
                 name='soporte_copiabasedatos_descargar'),
        ] + admin.ModelAdmin.get_urls(self)

    def _fichero(self, nombre):
        from core import copia_base
        for fichero in copia_base.copias():
            if fichero.name == nombre:  # solo nombres de la lista: nada de rutas
                return fichero
        return None

    def _auditar(self, request, descriptor):
        from auditoria.models import AccionAuditoria
        from auditoria.servicios import registrar
        registrar(usuario=request.user, accion=AccionAuditoria.COPIA_BASE,
                  modulo='soporte', descriptor=descriptor)

    def changelist_view(self, request, extra_context=None):
        if not self._puede(request):
            raise Http404
        from core import copia_base
        copia_base.borrar_antiguas()
        errores = copia_base.errores()
        contexto = {
            **self.admin_site.each_context(request),
            'title': 'Copia de la base de datos',
            'opts': self.model._meta,
            'copias': [{'nombre': f.name, 'mb': round(f.stat().st_size / 1048576, 1)}
                       for f in copia_base.copias()],
            'preparando': bool(copia_base.en_preparacion()),
            'error': errores[0].read_text(encoding='utf-8', errors='replace') if errores else '',
            'sin_programa': not copia_base.programa(),
            'horas': copia_base.HORAS_QUE_SE_GUARDAN,
        }
        return TemplateResponse(request, 'admin/soporte/copia_base.html', contexto)

    def preparar(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from core import copia_base
        if not self._puede(request):
            raise Http404
        if request.method == 'POST':
            try:
                nombre = copia_base.preparar()
            except (RuntimeError, OSError) as exc:
                messages.error(request, str(exc))
            else:
                self._auditar(request, f'Preparó una copia completa de la base de datos ({nombre}).')
                messages.success(request, 'Se está preparando la copia. La página se actualiza sola '
                                          'y aparecerá en la lista al terminar.')
        return redirect('admin:soporte_copiabasedatos_changelist')

    def descargar(self, request, nombre):
        if not self._puede(request):
            raise Http404
        fichero = self._fichero(nombre)
        if fichero is None:
            raise Http404
        self._auditar(request, f'Descargó la copia completa de la base de datos ({nombre}).')
        return FileResponse(open(fichero, 'rb'), as_attachment=True, filename=fichero.name,
                            content_type='application/octet-stream')


from .models import ActualizacionOrbith  # noqa: E402

#: Lo que la página enseña del registro del ensayo en marcha (el final).
MAXIMO_REGISTRO_EN_PANTALLA = 60_000


@admin.register(ActualizacionOrbith)
class ActualizacionOrbithAdmin(RegistroErroresAdmin):
    """Diagnóstico del servidor y ENSAYO de actualización (18-11-2026). No toca el
    Orbith en uso. Mismos permisos que el Registro de errores (solo el Administrador);
    subir un paquete y lanzar un ensayo quedan en Auditoría."""

    def get_urls(self):
        vista = self.admin_site.admin_view
        return [
            path('diagnostico/', vista(self.descargar_diagnostico), name='soporte_actualizacion_diagnostico'),
            path('subir/', vista(self.subir), name='soporte_actualizacion_subir'),
            path('ensayar/', vista(self.ensayar), name='soporte_actualizacion_ensayar'),
            path('registro/<str:nombre>/', vista(self.descargar_registro), name='soporte_actualizacion_registro'),
        ] + admin.ModelAdmin.get_urls(self)

    def _auditar(self, request, descriptor):
        from auditoria.models import AccionAuditoria
        from auditoria.servicios import registrar
        registrar(usuario=request.user, accion=AccionAuditoria.ACTUALIZACION,
                  modulo='soporte', descriptor=descriptor[:200])

    def _registro(self, nombre):
        from core import actualizacion
        return next((f for f in actualizacion.lista_de_registros() if f.name == nombre), None)

    def changelist_view(self, request, extra_context=None):
        if not self._puede(request):
            raise Http404
        from core import actualizacion
        actualizacion.borrar_antiguos()
        en_curso = actualizacion.ensayo_en_curso()
        registros = actualizacion.lista_de_registros()
        elegido = self._registro(request.GET.get('registro', '')) or (
            self._registro(en_curso) if en_curso else (registros[0] if registros else None))
        texto = ''
        if elegido:
            datos = elegido.read_bytes()
            texto = datos[-MAXIMO_REGISTRO_EN_PANTALLA:].decode('utf-8', errors='replace')
        contexto = {
            **self.admin_site.each_context(request),
            'title': 'Actualizar Orbith',
            'opts': self.model._meta,
            'diagnostico': actualizacion.diagnostico() if request.GET.get('diagnostico') else '',
            'paquetes': [{'nombre': f.name, 'mb': round(f.stat().st_size / 1048576, 1)}
                         for f in actualizacion.paquetes_subidos()],
            'registros': [f.name for f in registros],
            'elegido': elegido.name if elegido else '',
            'texto_registro': texto,
            'en_curso': en_curso,
            'tamano_trozo': actualizacion.TAMANO_TROZO,
            'dias': actualizacion.DIAS_QUE_SE_GUARDAN,
        }
        return TemplateResponse(request, 'admin/soporte/actualizacion.html', contexto)

    def descargar_diagnostico(self, request):
        from django.http import HttpResponse
        from django.utils import timezone
        from core import actualizacion
        if not self._puede(request):
            raise Http404
        respuesta = HttpResponse(actualizacion.diagnostico(), content_type='text/plain; charset=utf-8')
        respuesta['Content-Disposition'] = 'attachment; filename="diagnostico-%s.txt"' % (
            timezone.localtime().strftime('%Y-%m-%d_%H%M'))
        return respuesta

    def subir(self, request):
        from django.http import JsonResponse
        from core import actualizacion
        if not self._puede(request) or request.method != 'POST':
            raise Http404
        trozo = request.FILES.get('trozo')
        try:
            indice, total = int(request.POST.get('indice', -1)), int(request.POST.get('total', 0))
            if trozo is None or trozo.size > actualizacion.TAMANO_TROZO:
                raise actualizacion.ErrorDeActualizacion('Trozo no válido. Vuelva a empezar la subida.')
            final = actualizacion.recibir_trozo(request.POST.get('nombre', ''), indice, total, trozo.read())
        except (ValueError, actualizacion.ErrorDeActualizacion) as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        if final is not None:
            self._auditar(request, 'Subió el paquete %s (%.1f MB) para ensayar la actualización.'
                          % (final.name, final.stat().st_size / 1048576))
        return JsonResponse({'ok': True, 'terminado': final is not None})

    def ensayar(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from core import actualizacion
        if not self._puede(request):
            raise Http404
        if request.method == 'POST':
            paquete = next((f for f in actualizacion.paquetes_subidos()
                            if f.name == request.POST.get('paquete')), None)
            try:
                if paquete is None:
                    raise actualizacion.ErrorDeActualizacion('Elija uno de los paquetes subidos.')
                nombre = actualizacion.lanzar_ensayo(paquete)
            except (actualizacion.ErrorDeActualizacion, OSError) as exc:
                messages.error(request, str(exc))
            else:
                self._auditar(request, 'Lanzó el ensayo de actualización con %s.' % paquete.name)
                messages.success(request, 'Ensayo en marcha. La página se actualiza sola; no hace falta '
                                          'quedarse en ella.')
                return redirect('%s?registro=%s' % (
                    reverse('admin:soporte_actualizacionorbith_changelist'), nombre))
        return redirect('admin:soporte_actualizacionorbith_changelist')

    def descargar_registro(self, request, nombre):
        if not self._puede(request):
            raise Http404
        fichero = self._registro(nombre)
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
