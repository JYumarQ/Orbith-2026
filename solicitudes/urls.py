from django.urls import path
from . import views
from django.contrib.auth.decorators import login_required

urlpatterns = [

    # *CONTRATO
    path('list_solicitudes/', login_required(views.SolicitudCargoListView.as_view()), name='list_solicitudes'),
    path('add_solicitud/', login_required(views.SolicitudCargoCreateView.as_view()), name='add_solicitud'),

]
