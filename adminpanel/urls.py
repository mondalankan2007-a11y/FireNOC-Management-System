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

    # Officer management
    path('officers/', views.officer_list, name='officer_list'),
    path('officers/<int:profile_id>/', views.officer_detail, name='officer_detail'),
    path('officers/<int:profile_id>/set-active/', views.officer_set_active,
         name='officer_set_active'),

    # NOC certificates
    path('noc/', views.noc_list, name='noc_list'),
    path('noc/issue/<int:app_id>/', views.noc_issue, name='noc_issue'),

    # Admin Module landing page
    path('', views.admin_home, name='admin_home'),
]
