# usuarios/admin.py
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser
from .forms import CustomUserCreationForm, CustomUserChangeForm

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = CustomUser

    # Lo que verás en la tabla del admin
    list_display = (
        'username', 'email', 'es_admin', 'es_moderador',
        'is_staff', 'is_superuser', 'is_active',
        'fecha_creado', 'fecha_actualizado'
    )
    # <- AQUÍ van tus filtros y búsquedas
    list_filter = ('es_admin', 'es_moderador', 'is_staff', 'is_superuser', 'is_active')
    search_fields = (
        'username', 'email',
        'contrato__aspirante__nombre',
        'contrato__aspirante__papellido',
        'contrato__aspirante__sapellido'
    )
    ordering = ('username',)

    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Información personal', {'fields': ('contrato', 'unidades')}),
        ('Roles (app)', {'fields': ('es_admin', 'es_moderador')}),
        ('Permisos', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas importantes', {'fields': ('last_login', 'fecha_creado', 'fecha_actualizado')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'contrato', 'es_admin', 'es_moderador', 'password1', 'password2'),
        }),
    )

    # Evita que toquen is_staff/is_superuser manualmente (el modelo ya los define)
    readonly_fields = ('is_staff', 'is_superuser', 'fecha_creado', 'fecha_actualizado', 'last_login')
    filter_horizontal = ('groups', 'user_permissions', 'unidades')

    def save_model(self, request, obj, form, change):
        ambos_true = obj.es_admin and obj.es_moderador
        super().save_model(request, obj, form, change)  # el modelo ya auto-corrigió
        if ambos_true:
            self.message_user(
                request,
                'No es posible ser Administrador y Moderador a la vez. '
                'Se ajustó automáticamente para mantener un solo rol.',
                level=messages.WARNING
            )