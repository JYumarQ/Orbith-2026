from django.urls import path
from . import views

urlpatterns = [
    #DASHBOARD
    path('', views.DashboardView.as_view, name='dashboard')
]
