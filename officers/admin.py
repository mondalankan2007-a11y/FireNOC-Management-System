from django.contrib import admin
from .models import OfficerProfile, DocumentVerification, ApplicationReview


@admin.register(OfficerProfile)
class OfficerProfileAdmin(admin.ModelAdmin):
    list_display = ('officer_id', 'user', 'designation', 'badge_number', 'is_active', 'created_at')
    list_filter = ('is_active', 'designation')
    search_fields = ('officer_id', 'badge_number', 'user__username', 'user__first_name', 'user__last_name', 'user__email')
    ordering = ('officer_id',)


@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ('document', 'status', 'verified_by', 'verified_at')
    list_filter = ('status',)
    search_fields = ('document__document_name', 'officer_remarks')


@admin.register(ApplicationReview)
class ApplicationReviewAdmin(admin.ModelAdmin):
    list_display = ('application', 'status', 'reviewed_by', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('application__application_id', 'application__building_name', 'officer_remarks')
