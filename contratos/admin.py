import logging
from urllib.parse import urlencode

from django.contrib import admin
from django.db.models import Count, F, Window
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse

from auditoria.admin_mixins import AuditoriaAdminMixin, AuditoriaSoloEdicionAdminMixin

from .models import CAlta, CBaja, TMovimiento, TMovimientoAgrupado

logger = logging.getLogger(__name__)


@admin.register(CAlta)
class CAltaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'contratos'
    list_display = (
        'no_expediente', 'aspirante', 'cargo', 'tipo',
        'fecha_alta', 'salario_actual', 'en_proceso_movimiento'
    )
    search_fields = (
        'aspirante__nombre', 'aspirante__papellido', 'aspirante__sapellido',
        'aspirante__doc_identidad', 'no_expediente'
    )
    list_filter = ('tipo', 'motivo', 'mision', 'en_proceso_movimiento', 'tipo_salario')
    list_select_related = ('aspirante', 'cargo', 'tipo', 'motivo')
    autocomplete_fields = ['aspirante', 'cargo']
    readonly_fields = ('salario_actual',)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'fecha_alta_entidad' in form.base_fields:
            form.base_fields['fecha_alta_entidad'].help_text = (
                'Excepción de Admin: aquí se permite una fecha posterior a '
                '"F. de Contratación" (fecha_alta), a diferencia de los '
                'formularios normales de contrato.'
            )
        return form


@admin.register(CBaja)
class CBajaAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'contratos'
    list_display = ('no_expediente', 'aspirante', 'fecha_baja', 'causa_baja')
    search_fields = (
        'aspirante__nombre', 'aspirante__papellido', 'aspirante__sapellido',
        'aspirante__doc_identidad', 'no_expediente'
    )
    list_filter = ('causa_baja',)
    list_select_related = ('aspirante', 'causa_baja')
    autocomplete_fields = ['aspirante']


@admin.register(TMovimientoAgrupado)
class TMovimientoAgrupadoAdmin(admin.ModelAdmin):
    """Nivel 1 de navegación: una fila por (aspirante, no_expediente).

    Agrupa por estos dos campos y no por 'contrato' porque los movimientos de
    tipo Baja se guardan deliberadamente sin contrato (ver TMovimiento.contrato),
    y porque tras una recontratación el 'contrato' de los movimientos antiguos
    puede reasignarse (ver CAlta.movimientos_huerfanos_reenganchables). El par
    (aspirante, no_expediente) es la clave de identidad estable que ya usa el
    resto del código para reconocer "el mismo ciclo de contrato".
    """
    list_display = ('get_trabajador', 'get_no_expediente', 'get_cantidad', 'get_tipo_reciente', 'get_fecha_reciente')
    search_fields = ('no_expediente', 'aspirante__nombre', 'aspirante__papellido', 'aspirante__sapellido')
    list_select_related = ('aspirante',)

    # OBLIGATORIO: debe coincidir con el prefijo del DISTINCT ON de get_queryset.
    # Sin esto, Django reordena por el Meta.ordering heredado de TMovimiento
    # (-fecha_efectiva) y PostgreSQL rechaza la consulta porque el ORDER BY deja
    # de empezar por las columnas del DISTINCT ON.
    ordering = ('aspirante_id', 'no_expediente', '-fecha_efectiva')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # `obj is None`: permiso "general" que Django consulta para decidir si
        # ofrece acciones de borrado en la lista — se concede, para habilitar la
        # acción `eliminar_historico_completo` de abajo (que no declara permisos
        # propios, así que no depende de esto, pero se deja consistente).
        #
        # `obj` concreto: permiso para el borrado de UN objeto (el icono de la fila
        # y la página `.../<id>/delete/`) — se NIEGA siempre. Cada fila de este
        # queryset es solo la "representante" del grupo (ver `get_queryset`); borrar
        # solo esa fila con el flujo estándar de Django dejaría el resto del grupo
        # huérfano. La única forma de borrado válida aquí es la acción de abajo.
        return obj is None

    def get_actions(self, request):
        acciones = super().get_actions(request)
        acciones.pop('delete_selected', None)
        return acciones

    actions = ['eliminar_historico_completo']

    @admin.action(description='Eliminar TODO el histórico de nómina de los '
                               'trabajadores seleccionados')
    def eliminar_historico_completo(self, request, queryset):
        """Borra, para cada (aspirante, no_expediente) seleccionado, TODOS sus
        TMovimiento — no solo la fila "representante" que se ve en la lista.

        Se borra instancia por instancia (no con un `.delete()` sobre el
        queryset filtrado completo) para que `post_delete`
        (`contratos.models._al_eliminar_movimiento`) se dispare por cada uno:
        es lo que audita cada borrado y, cuando el último movimiento de un
        trabajador desaparece, cierra su ciclo de contratación.
        """
        total_grupos = 0
        total_movimientos = 0
        for fila in queryset:
            movimientos = list(TMovimiento.objects.filter(
                aspirante_id=fila.aspirante_id, no_expediente=fila.no_expediente))
            for movimiento in movimientos:
                movimiento.delete()
            total_movimientos += len(movimientos)
            total_grupos += 1
        self.message_user(
            request,
            f'Histórico completo eliminado: {total_grupos} trabajador(es), '
            f'{total_movimientos} movimiento(s) en total.')

    def get_queryset(self, request):
        return (
            TMovimiento.objects
            # Defensivo: PostgreSQL trata todos los NULL de una columna como
            # "iguales" en un DISTINCT ON, así que filas sin aspirante/expediente
            # colapsarían en un único grupo fantasma mezclando personas distintas.
            # Hoy no hay ninguna fila así; se excluyen para que, si aparecieran,
            # queden fuera del agrupado (pero siguen intactas y visibles en
            # TMovimientoAdmin) en vez de mezclarse en silencio.
            .exclude(aspirante_id__isnull=True)
            .exclude(no_expediente__isnull=True)
            .exclude(no_expediente__exact='')
            .annotate(cantidad_movimientos=Window(
                expression=Count('id'),
                partition_by=[F('aspirante_id'), F('no_expediente')],
            ))
            .order_by('aspirante_id', 'no_expediente', '-fecha_efectiva')
            .distinct('aspirante_id', 'no_expediente')
        )

    @admin.display(description='Trabajador')
    def get_trabajador(self, obj):
        if obj.aspirante:
            return f"{obj.aspirante.nombre} {obj.aspirante.papellido}"
        return '—'

    @admin.display(description='Expediente')
    def get_no_expediente(self, obj):
        return obj.no_expediente or '—'

    @admin.display(description='Cantidad de movimientos')
    def get_cantidad(self, obj):
        return obj.cantidad_movimientos

    @admin.display(description='Último movimiento')
    def get_tipo_reciente(self, obj):
        return obj.tipo_movimiento

    @admin.display(description='Fecha del último movimiento')
    def get_fecha_reciente(self, obj):
        return obj.fecha_efectiva

    def change_view(self, request, object_id, form_url='', extra_context=None):
        # Se resuelve con una consulta directa sobre TMovimiento (no sobre este
        # queryset agrupado): el proxy solo contiene la fila "representante" de
        # cada grupo, así que apoyarse en get_object() del propio proxy podría
        # dar 404 en casos límite.
        fila = TMovimiento.objects.filter(pk=object_id).values('aspirante_id', 'no_expediente').first()
        if fila is None:
            raise Http404("El movimiento solicitado no existe.")
        url = reverse('admin:contratos_tmovimiento_changelist')
        params = urlencode({
            'aspirante__id__exact': fila['aspirante_id'],
            'no_expediente': fila['no_expediente'],
        })
        return HttpResponseRedirect(f'{url}?{params}')


@admin.register(TMovimiento)
class TMovimientoAdmin(AuditoriaSoloEdicionAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'contratos'
    # Columnas que se verán en la lista principal
    list_display = (
        'id',
        'get_expediente',
        'get_trabajador',
        'tipo_movimiento',
        'fecha_efectiva',
        'cargo_nuevo',
        'unidad_nueva'
    )

    # Filtros laterales
    list_filter = ('tipo_movimiento', 'fecha_efectiva')

    # Buscador (campos propios de TMovimiento: sobreviven aunque el contrato
    # se haya borrado, a diferencia de 'contrato__...' que da NULL en las Bajas)
    search_fields = (
        'no_expediente',
        'aspirante__nombre',
        'aspirante__papellido',
        'aspirante__sapellido',
    )

    # Evita N+1: get_expediente/get_trabajador recorren aspirante y contrato fila a fila
    list_select_related = ('aspirante', 'contrato')

    # Navegación por fechas arriba de la lista
    date_hierarchy = 'fecha_efectiva'

    # Ordenar por defecto (el más reciente primero)
    ordering = ('-fecha_efectiva',)

    # Autocomplete seguro: CAltaAdmin, AspiranteAdmin (bolsa) y
    # UnidadOrganizativaAdmin ya tienen search_fields propios.
    autocomplete_fields = ['contrato', 'aspirante', 'unidad_anterior_fk', 'unidad_nueva_fk']

    # auto_now_add: no se puede editar de todas formas, se muestra como referencia
    readonly_fields = ('fecha_movimiento',)

    fieldsets = (
        ('Identificación', {
            'description': 'Este registro forma parte del historial de contratación. '
                            'Edítelo solo para corregir errores.',
            'fields': ('contrato', 'aspirante', 'no_expediente', 'tipo_movimiento', 'usuario'),
        }),
        ('Fechas', {
            'fields': ('fecha_solicitud', 'fecha_efectiva', 'fecha_movimiento'),
        }),
        ('Situación anterior', {
            'classes': ('collapse',),
            'fields': (
                'cargo_anterior', 'unidad_anterior', 'unidad_anterior_fk',
                'departamento_anterior', 'grupo_escala_anterior', 'cat_ocupacional_anterior',
                'tipo_salario_anterior', 'rol_anterior', 'tridente_anterior',
                'tipo_contrato_anterior', 'motivo_anterior', 'salario_anterior',
            ),
        }),
        ('Situación nueva', {
            'fields': (
                'cargo_nuevo', 'unidad_nueva', 'unidad_nueva_fk',
                'departamento_nuevo', 'grupo_escala_nuevo', 'cat_ocupacional_nuevo',
                'tipo_salario_nuevo', 'rol_nuevo', 'tridente_nuevo',
                'tipo_contrato_nuevo', 'motivo_nuevo', 'salario_nuevo', 'duracion_nueva',
            ),
        }),
        ('Observaciones', {
            'fields': ('observaciones',),
        }),
    )

    # Métodos auxiliares para mostrar datos de relaciones (ForeignKeys)
    @admin.display(description='Expediente')
    def get_expediente(self, obj):
        # 'contrato' es SET_NULL a propósito en los movimientos de Baja (el
        # contrato se borra justo después): por eso se usan primero los campos
        # propios de TMovimiento, que sobreviven a esa desvinculación.
        if obj.no_expediente:
            return obj.no_expediente
        if obj.contrato:
            return obj.contrato.no_expediente
        return '—'

    @admin.display(description='Trabajador')
    def get_trabajador(self, obj):
        if obj.aspirante:
            return f"{obj.aspirante.nombre} {obj.aspirante.papellido}"
        if obj.contrato and obj.contrato.aspirante:
            return f"{obj.contrato.aspirante.nombre} {obj.contrato.aspirante.papellido}"
        return '—'
