"""
URL configuration for FireNOC-Management-System project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .views import home
from applicants.views import register, login_view, logout_view, my_applications, application_details, document_upload, my_documents, inspection_details

urlpatterns = [
    # Admin Interface
    path('admin/', admin.site.urls),

    # Home Landing Page
    path('', home, name='home'),

    # Applicant Authentication Routes
    path('register/', register, name='register'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),

    # Applicant Module Routes
    path('applicant/', include('applicants.urls')),

    # Officer Module Routes
    path('officer/', include('officers.urls')),

    # Top-level My Applications route: /applications/
    path('applications/', my_applications, name='my_applications_root'),
    path('applications/<int:application_id>/', application_details, name='application_details_root'),
    path('applications/<int:application_id>/documents/', document_upload, name='document_upload_root'),

    # Top-level Documents Listing route: /documents/
    path('documents/', my_documents, name='my_documents_root'),

    # Top-level Inspection Details route: /applications/<id>/inspections/
    path('applications/<int:application_id>/inspections/', inspection_details, name='inspection_details_root'),
]

# Serve media files in development environment
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
