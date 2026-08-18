from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import Configuracion


@admin.register(Configuracion)
class ConfiguracionAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'configuracion'

    def has_add_permission(self, request):
        # Configuracion es un singleton (su propio save() ya rechaza una segunda
        # fila con ValueError): se oculta "Añadir" en vez de dejar que el usuario
        # llegue a ese error 500.
        return not Configuracion.objects.exists()
