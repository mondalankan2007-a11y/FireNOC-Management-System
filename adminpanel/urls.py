from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # Admin Module landing page
    path('', views.admin_home, name='admin_home'),
]
