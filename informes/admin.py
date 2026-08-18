from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import PlanMensualRegistro


@admin.register(PlanMensualRegistro)
class PlanMensualRegistroAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'informes'
    list_display = ('anno', 'mes', 'ueb_id', 'familia_id', 'valor')
    list_filter = ('anno', 'mes')
    search_fields = ('ueb_id', 'familia_id')
