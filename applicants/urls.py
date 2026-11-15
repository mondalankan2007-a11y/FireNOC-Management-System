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

    # Applicant Uploaded Documents Listing
    path('documents/', views.my_documents, name='my_documents'),

    # Inspection Details
    path('applications/<int:application_id>/inspections/', views.inspection_details, name='inspection_details'),

    # Application Status Timeline
    path('applications/<int:application_id>/timeline/', views.application_timeline, name='application_timeline'),

    # Deficiency Management
    path('deficiencies/', views.my_deficiencies, name='my_deficiencies'),
    path('applications/<int:application_id>/deficiencies/', views.application_deficiencies, name='application_deficiencies'),
    path('deficiencies/<int:deficiency_id>/rectify/', views.deficiency_rectify_submit, name='deficiency_rectify_submit'),

    # NOC Management
    path('my-nocs/', views.my_nocs, name='my_nocs'),
    path('applications/<int:application_id>/certificate/', views.noc_certificate, name='noc_certificate'),
    path('applications/<int:application_id>/certificate/download/', views.noc_certificate_pdf, name='noc_certificate_pdf'),

    # Profile Management
    path('profile/', views.profile, name='profile'),
]
