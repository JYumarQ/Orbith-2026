from django.contrib import admin

from .models import ImagenReporteProblema, ReporteProblema


class ImagenReporteProblemaInline(admin.TabularInline):
    model = ImagenReporteProblema
    extra = 0
    readonly_fields = ('imagen', 'fecha_subida')
    can_delete = False


@admin.register(ReporteProblema)
class ReporteProblemaAdmin(admin.ModelAdmin):
    list_display = ('fecha_creado', 'usuario', 'estado', 'url_origen')
    list_filter = ('estado', 'fecha_creado')
    search_fields = ('mensaje', 'error_consola', 'usuario__username')
    readonly_fields = (
        'usuario', 'mensaje', 'error_consola', 'url_origen',
        'fecha_creado', 'fecha_actualizado',
    )
    inlines = (ImagenReporteProblemaInline,)
