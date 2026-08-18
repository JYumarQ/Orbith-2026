from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import TareaGuia, TareaGuiaUsuario


@admin.register(TareaGuia)
class TareaGuiaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'progreso'
    list_display = ('titulo', 'codigo', 'categoria', 'modulo', 'activo', 'orden')
    list_editable = ('activo', 'orden')
    list_filter = ('categoria', 'activo')
    search_fields = ('titulo', 'codigo', 'descripcion')
    ordering = ('orden', 'id')


@admin.register(TareaGuiaUsuario)
class TareaGuiaUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'tarea', 'fecha_completada', 'visto')
    list_filter = ('tarea__categoria', 'visto')
    search_fields = ('usuario__username', 'tarea__titulo')
    autocomplete_fields = ('usuario', 'tarea')
    ordering = ('-fecha_completada',)
    # Este registro es evidencia de una acción real ya ocurrida: no tiene
    # sentido crear o editar filas a mano desde el Admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
