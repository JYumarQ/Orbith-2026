from django.urls import path

from . import views

app_name = 'auditoria'

urlpatterns = [
    path('', views.index, name='index'),
    path('buscar/', views.buscar_eventos, name='buscar_eventos'),
    path('<int:pk>/detalle/', views.detalle_evento, name='detalle_evento'),
]
