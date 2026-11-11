from django.urls import path
from . import views

app_name = 'officers'

urlpatterns = [
    # Officer Dashboard Routes
    path('', views.dashboard, name='officer_home'),
    path('dashboard/', views.dashboard, name='dashboard'),

    # Officer Authentication Routes
    path('login/', views.officer_login, name='login'),
    path('logout/', views.officer_logout, name='logout'),
]
