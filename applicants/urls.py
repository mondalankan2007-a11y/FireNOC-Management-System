from django.urls import path
from . import views

app_name = 'applicants'

urlpatterns = [
    path('', views.applicant_home, name='applicant_home'),
    path('register/', views.register, name='register'),
]
