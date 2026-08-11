"""Registro en el admin de Django, en modo consulta.

Los cierres son una fotografía inmutable (ver docstring de cierres/models.py): la
mutación de estado pasa siempre por cierres/servicios.py. Editar desde aquí
rompería esa garantía (números que dejarían de coincidir con lo declarado en su
momento), así que se registra solo para inspección/depuración, igual que
auditoria.EventoAuditoria.
"""
from django.contrib import admin

from .models import CierreCargo, CierreContrato, CierreUnidad, EstadoCierreUnidad


class SoloConsultaMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CierreUnidad)
class CierreUnidadAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'unidad_descripcion', 'anno', 'mes', 'declarado_por_nombre',
        'fecha_declaracion', 'en_plazo', 'total_cargos',
        'total_plazas_aprobadas', 'total_plazas_cubiertas',
    )
    list_filter = ('anno', 'mes', 'en_plazo')
    search_fields = ('unidad_descripcion', 'declarado_por_nombre')
    list_select_related = ('unidad', 'declarado_por')
    date_hierarchy = 'fecha_declaracion'


@admin.register(CierreCargo)
class CierreCargoAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'cierre', 'ncargo_descripcion', 'departamento_descripcion',
        'cat_ocupacional', 'cant_aprobada', 'cant_cubierta',
    )
    list_filter = ('cat_ocupacional', 'puesto_clave')
    search_fields = ('ncargo_descripcion', 'departamento_descripcion')
    list_select_related = ('cierre',)


@admin.register(CierreContrato)
class CierreContratoAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'cierre', 'aspirante_nombre', 'no_expediente', 'ncargo_descripcion',
        'cat_ocupacional', 'fecha_alta',
    )
    list_filter = ('cat_ocupacional', 'mision')
    search_fields = ('aspirante_nombre', 'doc_identidad', 'no_expediente')
    list_select_related = ('cierre', 'cierre_cargo')


@admin.register(EstadoCierreUnidad)
class EstadoCierreUnidadAdmin(SoloConsultaMixin, admin.ModelAdmin):
    list_display = (
        'unidad', 'estado', 'meses_pendientes',
        'periodo_pendiente_anno', 'periodo_pendiente_mes', 'fecha_calculo',
    )
    list_filter = ('estado',)
    search_fields = ('unidad__descripcion',)
    list_select_related = ('unidad', 'primer_cierre', 'ultimo_cierre')
