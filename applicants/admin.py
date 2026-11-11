from django.contrib import admin
from .models import Application, ApplicationDocument


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('application_id', 'building_name', 'applicant', 'status', 'created_at')
    list_filter = ('status', 'building_type', 'occupancy_type')
    search_fields = ('application_id', 'building_name', 'applicant__username', 'applicant__email')
    inlines = [ApplicationDocumentInline]


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ('document_name', 'application', 'document_type', 'uploaded_at')
    list_filter = ('document_type',)
