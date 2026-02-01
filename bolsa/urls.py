from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [
    # --- ASPIRANTES ---
    path('list_aspir/', login_required(views.AspiranteListView.as_view()), name='list_aspir'),
    # IMPORTANTE: El nombre debe ser 'search_aspirantes' (plural) para coincidir con tu views.py
    path('search_aspirante/', login_required(views.search_aspirantes), name='search_aspirantes'),
    
    path('add_aspir/', login_required(views.AspiranteCreateView.as_view()), name='add_aspir'),
    path('updt_aspir/<str:pk>/', login_required(views.AspiranteUpdateView.as_view()), name='updt_aspir'),
    path('del_aspir/<str:pk>/', login_required(views.AspiranteDeleteView.as_view()), name='del_aspir'),
    
    # --- BAJAS (Nuevas Rutas) ---
    path('list_baja/', login_required(views.BajaListView.as_view()), name='list_baja'),
    path('search_baja/', login_required(views.search_bajas), name='search_bajas'),

    # --- UTILIDADES ---
    path('validar_datos/', login_required(views.validar_datos_aspirante), name='validar_datos_aspirante'),
]