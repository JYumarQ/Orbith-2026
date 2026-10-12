from django.contrib import admin

from .models import ActividadXP, GanadorMes, MesCerrado


@admin.register(ActividadXP)
class ActividadXPAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'usuario', 'rol', 'actividad', 'xp', 'formato', 'detalle')
    list_filter = ('rol', 'actividad', 'dia')
    search_fields = ('usuario__username', 'detalle')
    date_hierarchy = 'dia'
    list_select_related = ('usuario',)


@admin.register(GanadorMes)
class GanadorMesAdmin(admin.ModelAdmin):
    list_display = ('anno', 'mes', 'rol', 'puesto', 'usuario', 'xp')
    list_filter = ('anno', 'mes', 'rol')
    list_select_related = ('usuario',)


@admin.register(MesCerrado)
class MesCerradoAdmin(admin.ModelAdmin):
    list_display = ('anno', 'mes', 'fecha_cierre')
