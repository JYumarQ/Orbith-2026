from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import Aspirante


@admin.register(Aspirante)
class AspiranteAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'bolsa'
    list_display = ('doc_identidad', 'serie_ci', 'nombre', 'papellido', 'sapellido', 'estado')
    search_fields = ('doc_identidad', 'serie_ci', 'nombre', 'papellido', 'sapellido')
    list_filter = ('estado', 'sexo')
    list_select_related = ('municipio', 'provincia', 'especialidad')
    autocomplete_fields = ['municipio', 'provincia', 'especialidad']
