from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required


urlpatterns = [
    path('list_usuarios/', login_required(views.UsuarioListView.as_view()), name='list_usuarios'),
    path('add_usuario/', login_required(views.CustomUserCreateView.as_view()), name='add_usuario'),
    path('updt_usuario/<pk>/', login_required(views.CustomUserUpdateView.as_view()), name='updt_usuario'),
    path('usuarios/<pk>/cambiar-password/', login_required(views.CambiarPasswordView.as_view()), name='cambiar_password'),
    path('del_usuario/<pk>/', login_required(views.CustomUserDeleteView.as_view()), name='del_usuario'),
    path('validar_username/', views.validar_username, name='validar_username'),
    path('search_usuarios/', login_required(views.search_usuarios), name='search_usuarios'),
]

