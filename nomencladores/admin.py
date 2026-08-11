from django.contrib import admin, messages
from django.shortcuts import render, redirect
from .forms import ImportarCargosForm
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from import_export.admin import ImportExportModelAdmin
from .utils import importar_cargos_excel
from .models import (
    NTridente, NRol, NGrupoEscala, NSalario, NCargo,
    NProvincia, NMunicipio, NHorario, NJornada, NEspecialidad,
    NTipoUnidadOrganizativa, NTipoContrato, NMotivoContrato, # <--- Añadidos aquí
    NTipoFamilia, NFamiliaCargo, NNocturnidad, NCondicionLaboralAnormal,
    NCausaAltaBaja, NNivelPreparacion,
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
    list_select_related = ('provincia',)
@admin.register(NCargo)
class NCargoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'cat_ocupacional', 'grupo_escala', 'salario_basico')
    search_fields = ('descripcion',)
    list_filter = ('cat_ocupacional', 'grupo_escala')
    list_select_related = ('grupo_escala',)

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

@admin.register(NTipoUnidadOrganizativa)
class NTipoUnidadAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'es_principal', 'es_subunidad', 'es_temporal')
    search_fields = ('descripcion',)

# Resto de modelos
admin.site.register(NTridente)
admin.site.register(NRol)
admin.site.register(NGrupoEscala)
admin.site.register(NSalario)
@admin.register(NTipoContrato)
class NTipoContratoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'ocupa_plaza', 'requiere_motivo', 'es_adiestrado')
    list_editable = ('es_adiestrado',) # Permite marcar el check sin entrar al detalle

@admin.register(NMotivoContrato)
class NMotivoContratoAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'tipo_contrato')
    list_editable = ('tipo_contrato',) # Permite asignar el tipo rápidamente desde la tabla
    list_filter = ('tipo_contrato',)
    list_select_related = ('tipo_contrato',)
# admin.site.register(NCargo) <--- OJO: Ya está registrado arriba con @admin.register
admin.site.register(NHorario)
admin.site.register(NJornada)

@admin.register(NEspecialidad)
class NEspecialidadAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'educ_superior')
    search_fields = ('nombre',)
    list_filter = ('educ_superior',)


# --- Nomencladores sin registrar previamente ---

@admin.register(NTipoFamilia)
class NTipoFamiliaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


@admin.register(NFamiliaCargo)
class NFamiliaCargoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo_familia')
    search_fields = ('nombre',)
    list_filter = ('tipo_familia',)
    list_select_related = ('tipo_familia',)


@admin.register(NNocturnidad)
class NNocturnidadAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'hora_inicio', 'hora_fin')
    search_fields = ('codigo',)


@admin.register(NCondicionLaboralAnormal)
class NCondicionLaboralAnormalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tarifa_hora', 'nocturnidad')
    search_fields = ('nombre',)
    autocomplete_fields = ['nocturnidad']


@admin.register(NCausaAltaBaja)
class NCausaAltaBajaAdmin(admin.ModelAdmin):
    list_display = ('descripcion', 'alta')
    search_fields = ('descripcion',)
    list_filter = ('alta',)


@admin.register(NNivelPreparacion)
class NNivelPreparacionAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)