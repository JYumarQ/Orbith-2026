from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import TareaGuia, TareaGuiaParte, TareaGuiaUsuario


@admin.register(TareaGuia)
class TareaGuiaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'progreso'
    list_display = ('titulo', 'codigo', 'categoria', 'modulo', 'partes',
                    'para_admin', 'para_moderador', 'para_observador', 'activo', 'orden')
    list_editable = ('para_admin', 'para_moderador', 'para_observador', 'activo', 'orden')
    list_filter = ('categoria', 'activo', 'para_admin', 'para_moderador', 'para_observador')
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


@admin.register(TareaGuiaParte)
class TareaGuiaParteAdmin(admin.ModelAdmin):
    """Partes hechas de las tareas con avance. Igual que las tareas
    completadas, es evidencia de una acción real: solo consulta."""
    list_display = ('usuario', 'tarea', 'parte', 'fecha')
    list_filter = ('tarea',)
    search_fields = ('usuario__username', 'tarea__titulo')
    ordering = ('-fecha',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
