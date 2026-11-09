from django.urls import path
from . import views

app_name = 'applicants'

urlpatterns = [
    path('', views.applicant_home, name='applicant_home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
