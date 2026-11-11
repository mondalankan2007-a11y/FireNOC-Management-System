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

    # Officer Application Queue & Verification Routes
    path('applications/', views.application_list, name='application_list'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path(
        'applications/<int:app_id>/documents/<int:doc_id>/verify/',
        views.document_verify,
        name='document_verify'
    ),
    path(
        'applications/<int:app_id>/review/',
        views.application_review,
        name='application_review'
    ),

    # Inspection Management Routes (Commit 4)
    path('inspections/', views.inspection_list, name='inspection_list'),
    path('inspections/schedule/<int:app_id>/', views.schedule_inspection, name='schedule_inspection'),
    path('inspections/<int:inspection_id>/', views.inspection_detail, name='inspection_detail'),
    path('inspections/<int:inspection_id>/start/', views.inspection_start, name='inspection_start'),
    path('inspections/<int:inspection_id>/complete/', views.inspection_complete, name='inspection_complete'),
    path('inspections/<int:inspection_id>/cancel/', views.inspection_cancel, name='inspection_cancel'),
    path('inspections/<int:inspection_id>/checklist/save/', views.inspection_checklist_save, name='inspection_checklist_save'),

    # Deficiency, Rectification & Officer Recommendation Routes (Commit 5)
    path('deficiencies/', views.deficiency_list, name='deficiency_list'),
    path('deficiencies/<int:deficiency_id>/', views.deficiency_detail, name='deficiency_detail'),
    path('inspections/<int:inspection_id>/deficiencies/create/', views.deficiency_create, name='deficiency_create'),
    path('deficiencies/<int:deficiency_id>/rectify/', views.deficiency_rectify, name='deficiency_rectify'),
    path('deficiencies/<int:deficiency_id>/rectifications/<int:rect_id>/review/', views.rectification_review, name='rectification_review'),
    path('deficiencies/<int:deficiency_id>/reopen/', views.deficiency_reopen, name='deficiency_reopen'),
    path('deficiencies/<int:deficiency_id>/close/', views.deficiency_close, name='deficiency_close'),
    path('applications/<int:app_id>/recommend/', views.application_recommend, name='application_recommend'),
]
