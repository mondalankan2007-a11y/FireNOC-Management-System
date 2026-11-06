"""
URL configuration for FireNOC-Management-System project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from .views import home
from applicants.views import register

urlpatterns = [
    # Admin Interface
    path('admin/', admin.site.urls),

    # Home Landing Page
    path('', home, name='home'),

    # Applicant Registration Route
    path('register/', register, name='register'),

    # Applicant Module Routes
    path('applicant/', include('applicants.urls')),
]

# Serve media files in development environment
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
