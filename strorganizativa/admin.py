from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import UnidadOrganizativa, Departamento, CargoPlantilla


class ExcelEstructuraMixin:
    """«Importar Excel» y «Exportar Excel» de la estructura (unidades y departamentos
    en un mismo libro, `strorganizativa/importacion.py`). Va en Unidades y en
    Departamentos, y los dos usan las mismas direcciones."""
    change_list_template = 'admin/strorganizativa/estructura_change_list.html'

    def importar_view(self, request):
        from django.urls import reverse

        from core.excel_admin import vista_importar
        from .importacion import importar_estructura
        return vista_importar(
            self, request, importar_estructura, 'Importar la estructura desde Excel',
            'Libro con la hoja <b>Unidades</b> (Código, Unidad, Tipo, Pertenece a, Municipio, Grupo de '
            'nómina, Posición) y, si quiere, la hoja <b>Departamentos</b> (Unidad, Departamento, '
            'Posición). Una unidad se reconoce por su <b>Código</b> (con él se puede renombrar) o, '
            'sin código, por su nombre. La Posición vacía pone lo nuevo al final.',
            reverse('admin:exportar-estructura'))

    def exportar_view(self, request):
        from core.excel_admin import descarga
        from core.nombres_descarga import nombre_de_informe
        from .importacion import exportar_estructura
        return descarga(exportar_estructura(), nombre_de_informe('Estructura_organizativa', extension='xlsx'))


@admin.register(UnidadOrganizativa)
class UnidadOrganizativaAdmin(ExcelEstructuraMixin, AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'strorganizativa'
    list_display = ('codigo_interno', 'descripcion', 'tipo', 'padre', 'grupo_nomina')
    search_fields = ('descripcion',)
    list_filter = ('tipo',)
    list_select_related = ('tipo', 'municipio', 'padre')
    autocomplete_fields = ['tipo', 'municipio', 'padre']

    def get_urls(self):
        from django.urls import path
        propias = [
            path('importar/', self.admin_site.admin_view(self.importar_view), name='importar-estructura'),
            path('exportar/', self.admin_site.admin_view(self.exportar_view), name='exportar-estructura'),
        ]
        return propias + super().get_urls()


@admin.register(Departamento)
class DepartamentoAdmin(ExcelEstructuraMixin, AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'strorganizativa'
    list_display = ('descripcion', 'unidad_organizativa', 'orden_informe')
    search_fields = ('descripcion',)
    list_filter = ('unidad_organizativa',)
    list_select_related = ('unidad_organizativa',)
    autocomplete_fields = ['unidad_organizativa']


@admin.register(CargoPlantilla)
class CargoPlantillaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'strorganizativa'
    list_display = ('ncargo', 'departamento', 'cant_aprobada', 'cant_cubierta', 'activo')
    search_fields = ('ncargo__descripcion', 'departamento__descripcion')
    list_filter = ('activo', 'funcionario', 'designado', 'departamento__unidad_organizativa')
    list_select_related = ('ncargo', 'departamento', 'rol', 'nivel_preparacion')
    autocomplete_fields = ['ncargo', 'departamento']
