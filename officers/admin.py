from django.contrib import admin
from .models import (
    OfficerProfile,
    DocumentVerification,
    ApplicationReview,
    Inspection,
    InspectionChecklistItem,
    InspectionReport,
    Deficiency,
    DeficiencyRectification,
)


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


class InspectionChecklistInline(admin.TabularInline):
    model = InspectionChecklistItem
    extra = 0


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ('pk', 'application', 'officer', 'scheduled_date', 'scheduled_time', 'status', 'created_at')
    list_filter = ('status', 'scheduled_date')
    search_fields = ('application__application_id', 'application__building_name', 'officer__username')
    ordering = ('scheduled_date', 'scheduled_time')
    inlines = [InspectionChecklistInline]


@admin.register(InspectionChecklistItem)
class InspectionChecklistItemAdmin(admin.ModelAdmin):
    list_display = ('inspection', 'item_type', 'status')
    list_filter = ('status', 'item_type')


@admin.register(InspectionReport)
class InspectionReportAdmin(admin.ModelAdmin):
    list_display = ('inspection', 'overall_result', 'completed_at', 'created_at')
    list_filter = ('overall_result',)
    search_fields = ('inspection__application__application_id', 'general_observations', 'officer_remarks')


class DeficiencyRectificationInline(admin.TabularInline):
    model = DeficiencyRectification
    extra = 0


@admin.register(Deficiency)
class DeficiencyAdmin(admin.ModelAdmin):
    list_display = ('pk', 'title', 'application', 'inspection', 'severity', 'status', 'reported_by', 'created_at')
    list_filter = ('status', 'severity')
    search_fields = ('title', 'description', 'application__application_id', 'application__building_name')
    inlines = [DeficiencyRectificationInline]


@admin.register(DeficiencyRectification)
class DeficiencyRectificationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'deficiency', 'status', 'submitted_by', 'submitted_at', 'reviewed_by')
    list_filter = ('status',)
    search_fields = ('deficiency__title', 'description', 'review_remarks')
