from django.contrib import admin
from .models import Aspirante


@admin.register(Aspirante)
class AspiranteAdmin(admin.ModelAdmin):
    list_display = ('doc_identidad', 'nombre', 'papellido', 'sapellido', 'estado', 'unidad_organizativa')
    search_fields = ('doc_identidad', 'nombre', 'papellido', 'sapellido')
    list_filter = ('estado', 'sexo', 'unidad_organizativa')
    list_select_related = ('unidad_organizativa', 'municipio', 'provincia', 'especialidad')
    autocomplete_fields = ['municipio', 'provincia', 'unidad_organizativa', 'especialidad']
