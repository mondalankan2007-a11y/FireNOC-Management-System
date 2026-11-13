from django.contrib import admin, messages
from django.shortcuts import redirect, get_object_or_404
from django.urls import path
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Application, ApplicationDocument
from officers.models import (
    ApplicationReview,
    Inspection,
    InspectionReport,
    Deficiency,
    get_recommendation_eligibility,
)


class FinalReviewStatusFilter(admin.SimpleListFilter):
    title = 'Final Review Status'
    parameter_name = 'final_review'

    def lookups(self, request, model_admin):
        return (
            ('ready', 'Ready for Final NOC Decision'),
            ('recommended', 'Recommended by Officer'),
            ('deficient', 'Deficiencies Pending'),
            ('inspection_pending', 'Inspection In Progress'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'ready':
            return queryset.filter(
                officer_review__recommendation=ApplicationReview.RECOMMENDATION_APPROVED,
                status__in=['DOCUMENTS_VERIFIED', 'UNDER_INSPECTION']
            )
        if self.value() == 'recommended':
            return queryset.filter(
                officer_review__recommendation=ApplicationReview.RECOMMENDATION_APPROVED
            )
        if self.value() == 'deficient':
            return queryset.filter(status='DEFICIENT')
        if self.value() == 'inspection_pending':
            return queryset.filter(status='UNDER_INSPECTION')
        return queryset


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0
    fields = ('document_name', 'document_type', 'file', 'verification_status_display', 'officer_remarks_display')
    readonly_fields = ('document_name', 'document_type', 'file', 'verification_status_display', 'officer_remarks_display')

    def verification_status_display(self, obj):
        if hasattr(obj, 'verification') and obj.verification:
            status = obj.verification.get_status_display()
            if obj.verification.status == 'VERIFIED':
                return format_html('<span style="color: green; font-weight: bold;">{}</span>', status)
            elif obj.verification.status == 'REJECTED':
                return format_html('<span style="color: red; font-weight: bold;">{}</span>', status)
            return status
        return mark_safe('<span style="color: orange;">Pending Verification</span>')
    verification_status_display.short_description = "Verification Status"

    def officer_remarks_display(self, obj):
        if hasattr(obj, 'verification') and obj.verification:
            return obj.verification.officer_remarks or '-'
        return '-'
    officer_remarks_display.short_description = "Verification Remarks"


class ApplicationReviewInline(admin.StackedInline):
    model = ApplicationReview
    extra = 0
    can_delete = False
    fields = (
        'status',
        'officer_remarks',
        'recommendation',
        'recommendation_remarks',
        'recommended_by',
        'recommended_at',
    )
    readonly_fields = (
        'status',
        'officer_remarks',
        'recommendation',
        'recommendation_remarks',
        'recommended_by',
        'recommended_at',
    )


class InspectionInline(admin.TabularInline):
    model = Inspection
    extra = 0
    can_delete = False
    fields = ('scheduled_date', 'scheduled_time', 'officer', 'status', 'report_result_display')
    readonly_fields = ('scheduled_date', 'scheduled_time', 'officer', 'status', 'report_result_display')

    def report_result_display(self, obj):
        if hasattr(obj, 'report') and obj.report:
            res = obj.report.get_overall_result_display()
            if obj.report.overall_result == InspectionReport.RESULT_SATISFACTORY:
                return format_html('<span style="color: green; font-weight: bold;">{}</span>', res)
            elif obj.report.overall_result == InspectionReport.RESULT_UNSATISFACTORY:
                return format_html('<span style="color: red; font-weight: bold;">{}</span>', res)
            return format_html('<span style="color: orange; font-weight: bold;">{}</span>', res)
        return "No Report"
    report_result_display.short_description = "Inspection Result"


class DeficiencyInline(admin.TabularInline):
    model = Deficiency
    extra = 0
    can_delete = False
    fields = ('title', 'severity', 'status', 'reported_by', 'resolved_at')
    readonly_fields = ('title', 'severity', 'status', 'reported_by', 'resolved_at')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'application_id',
        'building_name',
        'applicant',
        'status',
        'officer_recommendation_badge',
        'final_decision_readiness_badge',
        'created_at',
    )
    list_filter = (
        FinalReviewStatusFilter,
        'status',
        'building_type',
        'occupancy_type',
        'officer_review__recommendation',
    )
    search_fields = (
        'application_id',
        'building_name',
        'applicant__username',
        'applicant__email',
        'applicant__first_name',
        'applicant__last_name',
    )
    readonly_fields = (
        'application_id',
        'created_at',
        'updated_at',
        'officer_recommendation_summary',
        'inspection_summary',
        'documents_summary',
        'deficiencies_summary',
        'final_decision_readiness_display',
    )
    inlines = [
        ApplicationReviewInline,
        InspectionInline,
        DeficiencyInline,
        ApplicationDocumentInline,
    ]
    actions = ['approve_final_noc', 'reject_final_noc']

    @admin.action(description="Approve selected applications for Final Fire NOC")
    def approve_final_noc(self, request, queryset):
        approved_count = 0
        skipped_count = 0
        for app in queryset:
            if app.status == 'APPROVED':
                continue
            eligibility = get_recommendation_eligibility(app)
            review = getattr(app, 'officer_review', None)
            has_rec = (review is not None and review.recommendation == ApplicationReview.RECOMMENDATION_APPROVED)
            if eligibility['is_eligible'] and has_rec:
                app.status = 'APPROVED'
                app.save(update_fields=['status', 'updated_at'])
                approved_count += 1
            else:
                skipped_count += 1
        if approved_count:
            self.message_user(request, f"Successfully approved {approved_count} application(s) for Fire NOC.", level=messages.SUCCESS)
        if skipped_count:
            self.message_user(request, f"Skipped {skipped_count} application(s): missing verified documents, satisfactory inspection, or officer approval recommendation.", level=messages.WARNING)

    @admin.action(description="Reject selected applications for Final Fire NOC")
    def reject_final_noc(self, request, queryset):
        rejected_count = queryset.exclude(status='REJECTED').update(status='REJECTED')
        self.message_user(request, f"Marked {rejected_count} application(s) as Rejected.", level=messages.SUCCESS)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:app_id>/final-decision/',
                self.admin_site.admin_view(self.final_decision_view),
                name='applicants_application_final_decision'
            ),
        ]
        return custom_urls + urls

    def final_decision_view(self, request, app_id):
        app = get_object_or_404(Application, pk=app_id)
        if request.method == 'POST':
            decision = request.POST.get('decision', '').strip().upper()
            rejection_reason = request.POST.get('rejection_reason', '').strip()

            if decision == 'APPROVE':
                eligibility = get_recommendation_eligibility(app)
                review = getattr(app, 'officer_review', None)
                has_rec = (review is not None and review.recommendation == ApplicationReview.RECOMMENDATION_APPROVED)
                if not (eligibility['is_eligible'] and has_rec):
                    reasons = "; ".join(eligibility['blocking_reasons']) or "Missing officer recommendation for approval"
                    messages.error(request, f"Cannot approve final NOC: Application is not eligible ({reasons}).")
                    return redirect('admin:applicants_application_change', app.pk)
                app.status = 'APPROVED'
                app.save(update_fields=['status', 'updated_at'])
                messages.success(request, f"Final Fire NOC approved successfully for application {app.application_id}.")
                return redirect('admin:applicants_application_change', app.pk)

            elif decision == 'REJECT':
                if not rejection_reason:
                    messages.error(request, "Please provide a reason for rejecting the application.")
                    return redirect('admin:applicants_application_change', app.pk)
                app.status = 'REJECTED'
                if rejection_reason:
                    app.remarks = (f"{app.remarks}\n\n[ADMIN FINAL REJECTION REASON]: {rejection_reason}").strip()
                app.save(update_fields=['status', 'remarks', 'updated_at'])
                messages.warning(request, f"Application {app.application_id} has been marked as REJECTED.")
                return redirect('admin:applicants_application_change', app.pk)

        return redirect('admin:applicants_application_change', app.pk)

    fieldsets = (
        ('Application Identifiers', {
            'fields': ('application_id', 'status', 'final_decision_readiness_display', 'created_at', 'updated_at')
        }),
        ('Applicant Details', {
            'fields': ('applicant', 'full_name', 'email', 'mobile_number')
        }),
        ('Building & Property Details', {
            'fields': (
                'building_name', 'building_type', 'building_type_other',
                'building_address', 'city', 'state', 'pin_code',
                'num_floors', 'builtup_area', 'year_construction', 'occupancy_type'
            )
        }),
        ('Application Scope', {
            'fields': ('application_type', 'purpose', 'remarks')
        }),
        ('Officer Review & Recommendation Summary', {
            'fields': (
                'officer_recommendation_summary',
                'inspection_summary',
                'documents_summary',
                'deficiencies_summary',
            )
        }),
    )

    def officer_recommendation_badge(self, obj):
        review = getattr(obj, 'officer_review', None)
        if not review or not review.recommendation:
            return mark_safe('<span style="color: gray;">None</span>')
        rec = review.get_recommendation_display()
        if review.recommendation == ApplicationReview.RECOMMENDATION_APPROVED:
            return format_html('<span style="color: green; font-weight: bold;">{}</span>', rec)
        elif review.recommendation == ApplicationReview.RECOMMENDATION_NOT_RECOMMENDED:
            return format_html('<span style="color: red; font-weight: bold;">{}</span>', rec)
        return format_html('<span style="color: orange;">{}</span>', rec)
    officer_recommendation_badge.short_description = "Officer Recommendation"

    def final_decision_readiness_badge(self, obj):
        if obj.status == 'APPROVED':
            return mark_safe('<span style="color: green; font-weight: bold;">NOC Issued</span>')
        elif obj.status == 'REJECTED':
            return mark_safe('<span style="color: red; font-weight: bold;">Rejected</span>')
        eligibility = get_recommendation_eligibility(obj)
        review = getattr(obj, 'officer_review', None)
        has_rec = (review is not None and review.recommendation == ApplicationReview.RECOMMENDATION_APPROVED)
        if eligibility['is_eligible'] and has_rec:
            return mark_safe('<span style="color: blue; font-weight: bold;">Ready for NOC</span>')
        return mark_safe('<span style="color: gray;">Incomplete</span>')
    final_decision_readiness_badge.short_description = "NOC Readiness"

    def officer_recommendation_summary(self, obj):
        review = getattr(obj, 'officer_review', None)
        if not review:
            return "No officer review conducted yet."
        rec = review.get_recommendation_display()
        by = review.recommended_by.get_full_name() or review.recommended_by.username if review.recommended_by else "N/A"
        date = review.recommended_at.strftime('%Y-%m-%d %H:%M') if review.recommended_at else "N/A"
        return format_html(
            "<strong>Recommendation:</strong> {}<br>"
            "<strong>Recommended By:</strong> {} ({})<br>"
            "<strong>Remarks:</strong> {}",
            rec, by, date, review.recommendation_remarks or review.officer_remarks or 'None'
        )
    officer_recommendation_summary.short_description = "Officer Recommendation Summary"

    def inspection_summary(self, obj):
        inspections = obj.inspections.all()
        if not inspections.exists():
            return "No inspections recorded."
        parts = []
        for insp in inspections:
            rep = getattr(insp, 'report', None)
            res = rep.get_overall_result_display() if rep else "No report"
            parts.append(f"Inspection #{insp.pk} ({insp.get_status_display()}): Result = {res}")
        return mark_safe("<br>".join(parts))
    inspection_summary.short_description = "Inspection History"

    def documents_summary(self, obj):
        docs = obj.documents.all()
        if not docs.exists():
            return "No documents uploaded."
        parts = []
        for d in docs:
            v_status = d.verification.get_status_display() if hasattr(d, 'verification') and d.verification else "Pending"
            parts.append(f"{d.document_name} ({d.get_document_type_display()}): {v_status}")
        return mark_safe("<br>".join(parts))
    documents_summary.short_description = "Document Audits"

    def deficiencies_summary(self, obj):
        defs = obj.deficiencies.all()
        if not defs.exists():
            return "No deficiencies recorded (Clean)."
        parts = []
        for df in defs:
            parts.append(f"DEF-{df.pk} '{df.title}' [{df.get_severity_display()}]: {df.get_status_display()}")
        return mark_safe("<br>".join(parts))
    deficiencies_summary.short_description = "Deficiencies & Rectifications"

    def final_decision_readiness_display(self, obj):
        eligibility = get_recommendation_eligibility(obj)
        review = getattr(obj, 'officer_review', None)
        has_rec = (review is not None and review.recommendation == ApplicationReview.RECOMMENDATION_APPROVED)
        lines = []
        for check in eligibility['checks']:
            icon = "✓" if check['passed'] else "✗"
            color = "green" if check['passed'] else "red"
            lines.append(f'<span style="color: {color}; font-weight: bold;">{icon}</span> {check["label"]}: {check["detail"]}')
        rec_icon = "✓" if has_rec else "✗"
        rec_color = "green" if has_rec else "red"
        lines.append(f'<span style="color: {rec_color}; font-weight: bold;">{rec_icon}</span> Officer Recommendation for Approval: {"Yes" if has_rec else "No"}')
        return mark_safe("<br>".join(lines))
    final_decision_readiness_display.short_description = "NOC Decision Criteria Checklist"


@admin.register(ApplicationDocument)
class ApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = ('document_name', 'application', 'document_type', 'uploaded_at')
    list_filter = ('document_type',)
