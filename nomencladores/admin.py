from django.contrib import admin, messages
from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from import_export.admin import ImportExportModelAdmin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import (
    NTridente, NRol, NGrupoEscala, NSalario, NCargo,
    NProvincia, NMunicipio, NEspecialidad,
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
class NProvinciaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)
    inlines = [NMunicipioInline]

@admin.register(NMunicipio)
class NMunicipioAdmin(AuditoriaAdminMixin, ImportExportModelAdmin):
    # NOTA: la importación masiva desde Excel (botón "Import" de django-import-export)
    # crea/actualiza registros sin pasar por save_model, así que esos cambios NO
    # quedan auditados. El CRUD normal del Admin (fila a fila) sí queda cubierto.
    modulo_auditoria = 'nomencladores'
    resource_class = NMunicipioResource
    list_display = ('id', 'nombre', 'provincia')
    list_filter = ('provincia',)
    search_fields = ('nombre',)
    autocomplete_fields = ['provincia']
    list_select_related = ('provincia',)
@admin.register(NCargo)
class NCargoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    # Importar/Exportar Excel (24-10-2026, `nomencladores/importacion.py`): todo o
    # nada, con simulación; cada cargo se guarda con `save()`, así que Auditoría lo
    # registra con el usuario del admin.
    modulo_auditoria = 'nomencladores'
    list_display = ('descripcion', 'cat_ocupacional', 'grupo_escala', 'salario_basico')
    search_fields = ('descripcion',)
    list_filter = ('cat_ocupacional', 'grupo_escala')
    list_select_related = ('grupo_escala',)
    change_list_template = "pages/catalogos/ncargo/admin_change_list.html"

    def get_urls(self):
        from django.urls import path
        propias = [
            path('importar/', self.admin_site.admin_view(self.importar_view), name='importar-ncargo'),
            path('exportar/', self.admin_site.admin_view(self.exportar_view), name='exportar-ncargo'),
        ]
        return propias + super().get_urls()

    def importar_view(self, request):
        from django.urls import reverse

        from core.excel_admin import vista_importar
        from .importacion import importar_cargos
        return vista_importar(
            self, request, importar_cargos, 'Importar cargos desde Excel',
            'Hoja <b>CARGOS_CODIGO</b> (o la primera) con las columnas <b>Cargos</b>, <b>Grupo Escala</b>, '
            '<b>Categoría Ocupacional</b> y <b>Salario Básico</b>. Un cargo se reconoce por su nombre '
            '(sin tener en cuenta tildes ni mayúsculas).',
            reverse('admin:exportar-ncargo'))

    def exportar_view(self, request):
        from core.excel_admin import descarga
        from core.nombres_descarga import nombre_de_informe
        from .importacion import exportar_cargos
        return descarga(exportar_cargos(), nombre_de_informe('Nomenclador_de_cargos', extension='xlsx'))

@admin.register(NTipoUnidadOrganizativa)
class NTipoUnidadAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('descripcion', 'es_principal', 'es_subunidad', 'es_temporal')
    search_fields = ('descripcion',)


# Resto de modelos: antes registrados con `admin.site.register(Modelo)` (sin clase
# propia). Se les da una clase mínima para poder engancharlos a AuditoriaAdminMixin.
class _NomencladorAdminBase(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'


@admin.register(NTridente)
class NTridenteAdmin(_NomencladorAdminBase):
    pass


@admin.register(NRol)
class NRolAdmin(_NomencladorAdminBase):
    pass


@admin.register(NGrupoEscala)
class NGrupoEscalaAdmin(_NomencladorAdminBase):
    pass


@admin.register(NSalario)
class NSalarioAdmin(_NomencladorAdminBase):
    pass


@admin.register(NTipoContrato)
class NTipoContratoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('descripcion', 'ocupa_plaza', 'requiere_motivo', 'es_adiestrado')
    list_editable = ('es_adiestrado',) # Permite marcar el check sin entrar al detalle

@admin.register(NMotivoContrato)
class NMotivoContratoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('descripcion', 'tipo_contrato')
    list_editable = ('tipo_contrato',) # Permite asignar el tipo rápidamente desde la tabla
    list_filter = ('tipo_contrato',)
    list_select_related = ('tipo_contrato',)
# admin.site.register(NCargo) <--- OJO: Ya está registrado arriba con @admin.register


@admin.register(NEspecialidad)
class NEspecialidadAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('nombre', 'educ_superior')
    search_fields = ('nombre',)
    list_filter = ('educ_superior',)


# --- Nomencladores sin registrar previamente ---

@admin.register(NTipoFamilia)
class NTipoFamiliaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('nombre',)
    search_fields = ('nombre',)


@admin.register(NFamiliaCargo)
class NFamiliaCargoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('nombre', 'tipo_familia')
    search_fields = ('nombre',)
    list_filter = ('tipo_familia',)
    list_select_related = ('tipo_familia',)


@admin.register(NNocturnidad)
class NNocturnidadAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('codigo', 'hora_inicio', 'hora_fin')
    search_fields = ('codigo',)


@admin.register(NCondicionLaboralAnormal)
class NCondicionLaboralAnormalAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('nombre', 'tarifa_hora', 'nocturnidad')
    search_fields = ('nombre',)
    autocomplete_fields = ['nocturnidad']


@admin.register(NCausaAltaBaja)
class NCausaAltaBajaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('descripcion', 'alta')
    search_fields = ('descripcion',)
    list_filter = ('alta',)


@admin.register(NNivelPreparacion)
class NNivelPreparacionAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'nomencladores'
    list_display = ('nombre',)
    search_fields = ('nombre',)
