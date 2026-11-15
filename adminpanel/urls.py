from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # Administrator authentication
    path('login/', views.admin_login, name='login'),
    path('logout/', views.admin_logout, name='logout'),

    # Admin Module landing page
    path('', views.admin_home, name='admin_home'),
]
