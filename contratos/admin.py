from django.contrib import admin
from .models import CAlta, CBaja
from .models import TMovimiento



# Register your models here.
admin.site.register(CAlta)
admin.site.register(CBaja)

@admin.register(TMovimiento)
class TMovimientoAdmin(admin.ModelAdmin):
    # Columnas que se verán en la lista principal
    list_display = (
        'id', 
        'get_expediente', 
        'get_trabajador', 
        'tipo_movimiento', 
        'fecha_efectiva', 
        'cargo_nuevo', 
        'unidad_nueva'
    )
    
    # Filtros laterales
    list_filter = ('tipo_movimiento', 'fecha_efectiva')
    
    # Buscador (permite buscar por nombre, apellidos o número de expediente)
    search_fields = (
        'contrato__no_expediente', 
        'contrato__aspirante__nombre', 
        'contrato__aspirante__papellido', 
        'contrato__aspirante__sapellido'
    )
    
    # Navegación por fechas arriba de la lista
    date_hierarchy = 'fecha_efectiva'
    
    # Ordenar por defecto (el más reciente primero)
    ordering = ('-fecha_efectiva',)

    # Métodos auxiliares para mostrar datos de relaciones (ForeignKeys)
    @admin.display(description='Expediente')
    def get_expediente(self, obj):
        return obj.contrato.no_expediente

    @admin.display(description='Trabajador')
    def get_trabajador(self, obj):
        return f"{obj.contrato.aspirante.nombre} {obj.contrato.aspirante.papellido}"