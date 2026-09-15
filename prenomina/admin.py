"""Registro de Pre-Nómina en el panel de administración.

Dos criterios distintos según lo que se registra:

* **Los nomencladores son editables.** Usan el mismo `ModelForm` que el modal
  HTMX (`ModelAdmin.form`), de modo que la validación de fórmulas es literalmente
  la misma en las dos superficies: no hay forma de colar por el Admin una fórmula
  que la pantalla de Parámetros rechazaría.
* **El reporte es de solo lectura.** Se registra para poder inspeccionarlo y
  auditarlo, pero con las tres altas/cambios/bajas cerradas: un documento de
  nómina no debe poder editarse a mano saltándose los servicios, las validaciones
  y el recálculo. Los modelos de valor ni siquiera se registran; se consultan
  desde la pantalla del reporte.

Se mantiene `AuditoriaAdminMixin`, igual que el resto de `admin.py` del proyecto.
"""

from django.contrib import admin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .constantes import MODULO
from .forms import (NClaveAusenciaForm, NEscalaAnnosServicioForm,
                    NPagoHorasForm, NPagoImporteForm)
from .models import (AsignacionCalendario, Calendario, CalendarioPago,
                     CalendarioPagoDetalle, NClaveAusencia,
                     NEscalaAnnosServicio, NPagoHoras, NPagoImporte,
                     ReportePago)


@admin.register(NPagoHoras)
class NPagoHorasAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    form = NPagoHorasForm
    list_display = ('codigo', 'descripcion')
    search_fields = ('codigo', 'descripcion')
    ordering = ('codigo',)


@admin.register(NPagoImporte)
class NPagoImporteAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    form = NPagoImporteForm
    list_display = ('codigo', 'descripcion', 'tipo_valor', 'importe_fijo',
                    'formula', 'relacionado_con')
    list_filter = ('tipo_valor', 'relacionado_con')
    search_fields = ('codigo', 'descripcion', 'formula')
    ordering = ('codigo',)
    autocomplete_fields = ('relacionado_con',)
    list_select_related = ('relacionado_con',)


@admin.register(NClaveAusencia)
class NClaveAusenciaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    form = NClaveAusenciaForm
    list_display = ('codigo', 'descripcion', 'resta_horas_mes',
                    'resta_sistema_pago', 'resta_utilidades', 'relacionado_con')
    list_filter = ('resta_horas_mes', 'resta_sistema_pago', 'resta_utilidades',
                   'relacionado_con')
    search_fields = ('codigo', 'descripcion')
    ordering = ('codigo',)
    autocomplete_fields = ('relacionado_con',)
    list_select_related = ('relacionado_con',)


@admin.register(NEscalaAnnosServicio)
class NEscalaAnnosServicioAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    form = NEscalaAnnosServicioForm
    list_display = ('annos', 'cuantia')
    search_fields = ('annos',)
    ordering = ('annos',)


@admin.register(ReportePago)
class ReportePagoAdmin(admin.ModelAdmin):
    """Inspección, nunca edición. Ver el docstring del módulo."""

    # `quincena` va en la lista porque con pago Quincenal hay dos reportes por
    # unidad y mes: sin esa columna, las dos filas serían indistinguibles.
    list_display = ('unidad_descripcion', 'anno', 'mes', 'quincena', 'estado',
                    'fondo_tiempo', 'total_trabajadores', 'total_importes',
                    'fecha_cierre')
    list_filter = ('estado', 'anno', 'mes', 'quincena')
    search_fields = ('unidad_descripcion',)
    ordering = ('-anno', '-mes', '-quincena')
    date_hierarchy = 'fecha_desde'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --------------------------------------------------------------------------- #
# Calendario
#
# Son datos personales de cada usuario, y en la aplicación cada cual solo ve los
# suyos. Aquí se registran precisamente para lo contrario: es el único sitio
# donde el Administrador puede consultar los de todos, organizados por usuario
# (`list_filter` y `list_display` empiezan por él, y el orden por defecto los
# agrupa). Se dejan editables porque el Administrador es quien tiene que poder
# corregir un catálogo ajeno cuando su dueño ya no está disponible.
# --------------------------------------------------------------------------- #

class CalendarioPagoDetalleInline(admin.TabularInline):
    """Las líneas se ven dentro de su período: sueltas no se entienden."""

    model = CalendarioPagoDetalle
    extra = 0
    fields = ('calendario', 'codigo_historico', 'descripcion_historica',
              'horas_q1', 'horas_q2')
    autocomplete_fields = ('calendario',)


@admin.register(Calendario)
class CalendarioAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    list_display = ('usuario', 'codigo', 'descripcion', 'activo')
    list_display_links = ('descripcion',)
    list_filter = ('usuario', 'activo')
    search_fields = ('descripcion', 'codigo', 'usuario__username')
    ordering = ('usuario__username', 'codigo')
    list_select_related = ('usuario',)


@admin.register(CalendarioPago)
class CalendarioPagoAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    list_display = ('usuario', 'anno', 'mes', 'cerrado', 'fecha_cierre',
                    'cerrado_por_nombre')
    list_filter = ('usuario', 'cerrado', 'anno')
    ordering = ('usuario__username', '-anno', '-mes')
    list_select_related = ('usuario',)
    inlines = (CalendarioPagoDetalleInline,)
    # El cierre lo decide `servicios_calendario.cerrar_periodo()`, invocado desde
    # Gestión de Reportes de Pagos. Se muestra, pero no se teclea a mano aquí:
    # marcarlo desde el Admin dejaría el calendario cerrado y el reporte abierto.
    readonly_fields = ('cerrado', 'fecha_cierre', 'cerrado_por_nombre')


@admin.register(AsignacionCalendario)
class AsignacionCalendarioAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = MODULO
    list_display = ('contrato', 'calendario', 'asignado_por', 'fecha_asignacion')
    list_filter = ('calendario__usuario', 'calendario')
    search_fields = ('contrato__no_expediente', 'contrato__aspirante__nombre',
                     'contrato__aspirante__papellido')
    list_select_related = ('contrato', 'calendario', 'asignado_por')
