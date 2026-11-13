from django.urls import path
from . import views

app_name = 'applicants'

urlpatterns = [
    path('', views.applicant_home, name='applicant_home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Fire NOC Application Form
    path('applications/new/', views.application_new, name='application_new'),

    # My Applications listing
    path('applications/', views.my_applications, name='my_applications'),

    # Application Details
    path('applications/<int:application_id>/', views.application_details, name='application_details'),

    # Document Upload Interface
    path('applications/<int:application_id>/documents/', views.document_upload, name='document_upload'),
]
