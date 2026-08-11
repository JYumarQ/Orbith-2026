from django.contrib import admin
from .models import UnidadOrganizativa, Departamento, CargoPlantilla


@admin.register(UnidadOrganizativa)
class UnidadOrganizativaAdmin(admin.ModelAdmin):
    list_display = ('codigo_interno', 'descripcion', 'tipo', 'padre', 'grupo_nomina')
    search_fields = ('descripcion',)
    list_filter = ('tipo',)
    list_select_related = ('tipo', 'municipio', 'padre')
    autocomplete_fields = ['tipo', 'municipio', 'padre']


@admin.register(Departamento)
class DepartamentoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'unidad_organizativa', 'orden_informe')
    search_fields = ('descripcion',)
    list_filter = ('unidad_organizativa',)
    list_select_related = ('unidad_organizativa',)
    autocomplete_fields = ['unidad_organizativa']


@admin.register(CargoPlantilla)
class CargoPlantillaAdmin(admin.ModelAdmin):
    list_display = ('ncargo', 'departamento', 'cant_aprobada', 'cant_cubierta', 'activo')
    search_fields = ('ncargo__descripcion', 'departamento__descripcion')
    list_filter = ('activo', 'funcionario', 'designado', 'departamento__unidad_organizativa')
    list_select_related = ('ncargo', 'departamento', 'rol', 'nivel_preparacion')
    autocomplete_fields = ['ncargo', 'departamento']
