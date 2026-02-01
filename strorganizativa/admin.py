from django.contrib import admin
from .models import UnidadOrganizativa, Departamento, CargoPlantilla

# Register your models here.
admin.site.register(UnidadOrganizativa)
admin.site.register(Departamento)
admin.site.register(CargoPlantilla)