from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required
from .decorators import admin_required


urlpatterns = [
    path('list_usuarios/', login_required(views.UsuarioListView.as_view()), name='list_usuarios'),
    path('add_usuario/', login_required(views.CustomUserCreateView.as_view()), name='add_usuario'),
    path('updt_usuario/<pk>/', login_required(views.CustomUserUpdateView.as_view()), name='updt_usuario'),
    path('usuarios/<pk>/cambiar-password/', login_required(views.CambiarPasswordView.as_view()), name='cambiar_password'),
    path('del_usuario/<pk>/', login_required(views.CustomUserDeleteView.as_view()), name='del_usuario'),
    path('validar_username/', views.validar_username, name='validar_username'),
    path('search_usuarios/', login_required(views.search_usuarios), name='search_usuarios'),

    # --- MANTENIMIENTO Y SESIONES (solo Administrador) ---
    path('mantenimiento/activar/', admin_required(views.activar_mantenimiento), name='activar_mantenimiento'),
    path('mantenimiento/desactivar/', admin_required(views.desactivar_mantenimiento), name='desactivar_mantenimiento'),
    path('usuarios/<pk>/expulsar-sesion/', admin_required(views.expulsar_sesion), name='expulsar_sesion'),

    # --- MENÚ DE USUARIO (siempre sobre la propia cuenta) ---
    path('perfil/avatar/', views.actualizar_avatar, name='actualizar_avatar'),
    path('perfil/avatar/eliminar/', views.eliminar_avatar, name='eliminar_avatar'),
    path('preferencias/', views.guardar_preferencias, name='guardar_preferencias'),
]

