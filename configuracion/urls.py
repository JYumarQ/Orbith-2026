from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required



urlpatterns = [
    #*ASPIRANTE
    path('parametros/', login_required(views.ParametrosGeneralesView.as_view()), name='parametros'),
    path('configuracion/actualizar-salario/', login_required(views.actualizar_salario), name="actualizar_salario"),
    
    ]