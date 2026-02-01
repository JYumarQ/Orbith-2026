from django.contrib import admin, messages
from django.shortcuts import render, redirect
from .forms import ImportarCargosForm
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from import_export.admin import ImportExportModelAdmin
from .utils import importar_cargos_excel
from .models import (
    NTridente, NRol, NGrupoEscala, NSalario, NCargo,
    NProvincia, NMunicipio, NHorario, NJornada, NEspecialidad
)


class NMunicipioResource(resources.ModelResource):
    provincia = fields.Field(
        column_name='Provincia',
        attribute='provincia',
        widget=ForeignKeyWidget(NProvincia, field='nombre')
    )
    nombre = fields.Field(column_name='Municipio', attribute='nombre')

    class Meta:
        model = NMunicipio
        fields = ('id', 'provincia', 'nombre')
        import_id_fields = ('nombre', 'provincia') 
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        # Crea la provincia automáticamente si no existe en el Excel
        provincia_nombre = row.get('Provincia')
        if provincia_nombre:
            NProvincia.objects.get_or_create(nombre=provincia_nombre.strip())


class NMunicipioInline(admin.TabularInline):
    model = NMunicipio
    extra = 1
    fields = ('nombre',)
    show_change_link = True

@admin.register(NProvincia)
class NProvinciaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)
    inlines = [NMunicipioInline]

@admin.register(NMunicipio)
class NMunicipioAdmin(ImportExportModelAdmin):
    resource_class = NMunicipioResource
    list_display = ('id', 'nombre', 'provincia')
    list_filter = ('provincia',)
    search_fields = ('nombre',)
    autocomplete_fields = ['provincia']
@admin.register(NCargo)
class NCargoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'cat_ocupacional', 'grupo_escala', 'salario_basico', 'activo')
    search_fields = ('descripcion',)
    list_filter = ('cat_ocupacional', 'grupo_escala', 'activo')
    
    # CORRECCIÓN 1: Ruta exacta a tu archivo existente
    change_list_template = "pages/catalogos/ncargo/admin_change_list.html"

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        my_urls = [
            # CORRECCIÓN: Ahora dice 'importar/' para coincidir con tu template
            path('importar/', self.admin_site.admin_view(self.importar_cargos_view), name='importar-ncargo'),
        ]
        return my_urls + urls

    def importar_cargos_view(self, request):
        if request.method == "POST":
            form = ImportarCargosForm(request.POST, request.FILES)
            if form.is_valid():
                archivo = request.FILES['archivo_excel']
                estrategia = form.cleaned_data['estrategia']
                
                res = importar_cargos_excel(archivo, estrategia)
                
                if 'fatal' in res:
                    messages.error(request, f"Error crítico: {res['fatal']}")
                else:
                    msg = f"Importación: {res['creados']} creados, {res['actualizados']} actualizados. {res['saltados']} saltados."
                    if res['errores']:
                        msg += f" Errores detectados: {len(res['errores'])}."
                        for err in res['errores'][:5]:
                            messages.warning(request, err)
                    messages.success(request, msg)
                return redirect("..")
        else:
            form = ImportarCargosForm()

        context = dict(
            self.admin_site.each_context(request),
            form=form,
            title="Importar Cargos desde Excel"
        )
        # CORRECCIÓN 2: Ruta exacta a tu archivo existente
        return render(request, "pages/catalogos/ncargo/admin_import_form.html", context)

# Resto de modelos
admin.site.register(NTridente)
admin.site.register(NRol)
admin.site.register(NGrupoEscala)
admin.site.register(NSalario)
# admin.site.register(NCargo) <--- OJO: Ya está registrado arriba con @admin.register
admin.site.register(NHorario)
admin.site.register(NJornada)
admin.site.register(NEspecialidad)