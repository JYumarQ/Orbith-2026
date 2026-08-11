from django.contrib import admin
from .models import InformePersonalizado


@admin.register(InformePersonalizado)
class InformePersonalizadoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'modelo_raiz', 'usuario', 'es_plantilla', 'fecha_actualizacion')
    list_filter = ('es_plantilla', 'modelo_raiz')
    search_fields = ('nombre', 'descripcion')
    list_select_related = ('usuario',)
