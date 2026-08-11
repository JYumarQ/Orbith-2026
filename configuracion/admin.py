from django.contrib import admin
from .models import Configuracion


@admin.register(Configuracion)
class ConfiguracionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Configuracion es un singleton (su propio save() ya rechaza una segunda
        # fila con ValueError): se oculta "Añadir" en vez de dejar que el usuario
        # llegue a ese error 500.
        return not Configuracion.objects.exists()
