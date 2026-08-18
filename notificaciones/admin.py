from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import Notificacion


@admin.register(Notificacion)
class NotificacionAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'notificaciones'
    list_display = ('titulo', 'tipo', 'estado', 'leido', 'severidad', 'destinatario', 'fecha_creado')
    list_filter = ('tipo', 'estado', 'leido', 'severidad')
    search_fields = ('titulo', 'mensaje', 'codigo_regla')
    list_select_related = ('destinatario', 'unidad')
    date_hierarchy = 'fecha_creado'
    autocomplete_fields = ['destinatario', 'unidad']
