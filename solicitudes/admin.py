"""Registro en el admin de Django.

El modelo anterior no estaba registrado, lo que dejaba sin ninguna vía de inspección un
módulo que decide sobre operaciones sensibles. Se registra en modo consulta: el flujo
real vive en la aplicación, y aprobar o rechazar desde el admin se saltaría las
comprobaciones de `solicitudes/servicios.py` (permisos, bloqueo de revisión, ejecución
transaccional del cambio y notificaciones).
"""

from django.contrib import admin

from solicitudes.models import Solicitud


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = ('descriptor', 'operacion', 'estado', 'solicitante_nombre',
                    'unidad', 'created_at')
    list_filter = ('estado', 'operacion', 'unidad')
    search_fields = ('descriptor', 'motivo', 'solicitante_nombre')
    date_hierarchy = 'created_at'
    list_select_related = ('unidad', 'solicitante')

    # Solo consulta: ver arriba.
    readonly_fields = [campo.name for campo in Solicitud._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
