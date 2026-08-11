from django.contrib import admin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(admin.ModelAdmin):
    """Solo para depuración de desarrollador. La interfaz real está en /auditoria/."""

    list_display = ('fecha', 'usuario_nombre', 'accion', 'modulo', 'descriptor',
                     'content_type', 'solicitud')
    list_filter = ('accion', 'modulo', 'content_type')
    search_fields = ('descriptor', 'usuario_nombre')
    date_hierarchy = 'fecha'
    list_select_related = ('content_type', 'solicitud')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
