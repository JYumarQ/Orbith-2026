# usuarios/admin.py
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from auditoria.admin_mixins import AuditoriaAdminMixin

from .models import CustomUser, PreferenciasUsuario
from .forms import CustomUserCreationForm, CustomUserChangeForm

@admin.register(CustomUser)
class CustomUserAdmin(AuditoriaAdminMixin, UserAdmin):
    modulo_auditoria = 'usuarios'
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    # Lo que verás en la tabla del admin
    list_display = (
        'username', 'email', 'es_admin', 'es_moderador', 'es_observador',
        'is_staff', 'is_superuser', 'is_active',
        'fecha_creado', 'fecha_actualizado'
    )
    # <- AQUÍ van tus filtros y búsquedas
    list_filter = ('es_admin', 'es_moderador', 'es_observador', 'is_staff', 'is_superuser', 'is_active')
    search_fields = (
        'username', 'email',
        'contrato__aspirante__nombre',
        'contrato__aspirante__papellido',
        'contrato__aspirante__sapellido'
    )
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Información personal', {'fields': ('contrato', 'unidades', 'avatar')}),
        ('Roles (app)', {'fields': ('es_admin', 'es_moderador', 'es_observador')}),
        ('Permisos', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas importantes', {'fields': ('last_login', 'fecha_creado', 'fecha_actualizado')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'contrato', 'es_admin', 'es_moderador', 'es_observador', 'password1', 'password2'),
        }),
    )

    # Evita que toquen is_staff/is_superuser manualmente (el modelo ya los define)
    readonly_fields = ('is_staff', 'is_superuser', 'fecha_creado', 'fecha_actualizado', 'last_login')
    filter_horizontal = ('groups', 'user_permissions', 'unidades')
    # CAlta ya tiene search_fields propio (contratos.admin.CAltaAdmin): evita un
    # <select> con todos los contratos del sistema en el formulario de usuario.
    autocomplete_fields = ['contrato']

    def save_model(self, request, obj, form, change):
        roles_marcados = sum([obj.es_admin, obj.es_moderador, obj.es_observador])
        super().save_model(request, obj, form, change)  # el modelo ya auto-corrigió
        if roles_marcados > 1:
            self.message_user(
                request,
                'Solo puede tener un rol activo a la vez (Administrador, Moderador '
                'u Observador). Se ajustó automáticamente para mantener uno solo.',
                level=messages.WARNING
            )


@admin.register(PreferenciasUsuario)
class PreferenciasUsuarioAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    modulo_auditoria = 'usuarios'
    list_display = ('usuario', 'sidebar_colapsada', 'animaciones_activas', 'fecha_actualizado')
    list_filter = ('sidebar_colapsada', 'animaciones_activas')
    search_fields = ('usuario__username',)
    list_select_related = ('usuario',)
    autocomplete_fields = ['usuario']