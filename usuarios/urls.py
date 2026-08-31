from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required
from .decorators import admin_required


# =========================================================================
# GESTIÓN DE USUARIOS: SOLO ADMINISTRADOR
#
# La barra lateral ya oculta «Administración > Usuarios» a quien no es
# Administrador (ver templates/base/sidebar.html), pero ocultar el enlace NO es
# proteger la vista: bastaba con escribir la URL —o ser redirigido a ella, como
# pasaba al cambiar la contraseña propia— para que un Moderador viera el listado
# completo de usuarios, sus roles y los botones de crear/editar/eliminar.
#
# Por eso estas vistas se envuelven con `admin_required`, el mismo decorador que
# ya protegía Mantenimiento y Sesiones: la comprobación real vive en el backend.
#
# `cambiar_password` es la ÚNICA excepción y se queda con `login_required`:
# cualquier usuario debe poder cambiar su propia contraseña desde «Mi Perfil».
# La vista comprueba por sí misma (ver `CambiarPasswordView.dispatch`) que, si el
# destino no es su propia cuenta, quien pide el cambio sea Administrador.
# =========================================================================
urlpatterns = [
    path('list_usuarios/', admin_required(views.UsuarioListView.as_view()), name='list_usuarios'),
    path('add_usuario/', admin_required(views.CustomUserCreateView.as_view()), name='add_usuario'),
    path('updt_usuario/<pk>/', admin_required(views.CustomUserUpdateView.as_view()), name='updt_usuario'),
    path('usuarios/<pk>/cambiar-password/', login_required(views.CambiarPasswordView.as_view()), name='cambiar_password'),
    path('del_usuario/<pk>/', admin_required(views.CustomUserDeleteView.as_view()), name='del_usuario'),
    # Alternativa al borrado: quita el acceso conservando unidades, plantillas y
    # calendarios. Es lo que se ofrece cuando el borrado está bloqueado.
    path('usuarios/<pk>/inhabilitar/', views.inhabilitar_usuario, name='inhabilitar_usuario'),
    path('validar_username/', admin_required(views.validar_username), name='validar_username'),
    path('search_usuarios/', admin_required(views.search_usuarios), name='search_usuarios'),

    # --- MANTENIMIENTO Y SESIONES (solo Administrador) ---
    path('mantenimiento/activar/', admin_required(views.activar_mantenimiento), name='activar_mantenimiento'),
    path('mantenimiento/desactivar/', admin_required(views.desactivar_mantenimiento), name='desactivar_mantenimiento'),
    path('usuarios/<pk>/expulsar-sesion/', admin_required(views.expulsar_sesion), name='expulsar_sesion'),

    # --- MENÚ DE USUARIO (siempre sobre la propia cuenta) ---
    path('perfil/avatar/', views.actualizar_avatar, name='actualizar_avatar'),
    path('perfil/avatar/eliminar/', views.eliminar_avatar, name='eliminar_avatar'),
    path('preferencias/', views.guardar_preferencias, name='guardar_preferencias'),
]

