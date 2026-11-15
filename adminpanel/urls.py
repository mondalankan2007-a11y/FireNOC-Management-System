from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # Administrator authentication
    path('login/', views.admin_login, name='login'),
    path('logout/', views.admin_logout, name='logout'),

    # Department dashboard
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/refresh/', views.refresh_statistics, name='refresh_statistics'),

    # Applicant management
    path('applicants/', views.applicant_list, name='applicant_list'),
    path('applicants/<int:user_id>/', views.applicant_detail, name='applicant_detail'),

    # Admin Module landing page
    path('', views.admin_home, name='admin_home'),
]
