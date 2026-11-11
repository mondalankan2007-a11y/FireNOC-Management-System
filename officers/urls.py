from django.urls import path
from . import views

app_name = 'officers'

urlpatterns = [
    path('', views.officer_home, name='officer_home'),
]
