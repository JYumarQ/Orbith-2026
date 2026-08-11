from django.contrib import admin
from .models import Notificacion


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'tipo', 'estado', 'leido', 'severidad', 'destinatario', 'fecha_creado')
    list_filter = ('tipo', 'estado', 'leido', 'severidad')
    search_fields = ('titulo', 'mensaje', 'codigo_regla')
    list_select_related = ('destinatario', 'unidad')
    date_hierarchy = 'fecha_creado'
    autocomplete_fields = ['destinatario', 'unidad']
