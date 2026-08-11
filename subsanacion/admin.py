"""Registro en el admin de Django, en modo consulta.

Subsanación nunca escribe directamente sobre datos de negocio (ver docstring de
subsanacion/models.py): la corrección de un hallazgo la hace el usuario desde los
formularios normales de Orbith, que además dejan constancia del cambio en
RevisionHallazgo. Editar un Hallazgo desde aquí saltaría ese registro, así que se
deja en modo consulta, igual que auditoria.EventoAuditoria.
"""
from django.contrib import admin

from .models import EjecucionAnalisis, Hallazgo, RevisionHallazgo


class SoloConsultaMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EjecucionAnalisis)
class EjecucionAnalisisAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'iniciada_en', 'estado', 'origen', 'lanzada_por', 'duracion_ms',
        'hallazgos_nuevos', 'hallazgos_resueltos', 'indice_salud',
    )
    list_filter = ('estado', 'origen')
    list_select_related = ('lanzada_por',)
    date_hierarchy = 'iniciada_en'


@admin.register(Hallazgo)
class HallazgoAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'titulo', 'codigo_regla', 'modulo', 'criticidad',
        'estado', 'vigente', 'ultima_deteccion',
    )
    list_filter = ('modulo', 'criticidad', 'estado', 'vigente')
    search_fields = ('titulo', 'codigo_regla', 'detalle')
    list_select_related = ('content_type', 'unidad_organizativa', 'ejecucion', 'revisado_por')
    date_hierarchy = 'ultima_deteccion'


@admin.register(RevisionHallazgo)
class RevisionHallazgoAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = ('hallazgo', 'estado_anterior', 'estado_nuevo', 'usuario', 'automatica', 'fecha')
    list_filter = ('automatica', 'estado_nuevo')
    list_select_related = ('hallazgo', 'usuario')
    date_hierarchy = 'fecha'
