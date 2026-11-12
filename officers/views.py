from functools import wraps
import datetime
import os
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from applicants.models import Application, ApplicationDocument
from .models import (
    OfficerProfile,
    DocumentVerification,
    ApplicationReview,
    Inspection,
    InspectionChecklistItem,
    InspectionReport,
    Deficiency,
    DeficiencyRectification,
    get_recommendation_eligibility,
)


def is_officer(user):
    """
    Check if a user is an authorized Fire Officer.
    
    A user is considered a Fire Officer if:
    1. They possess an associated OfficerProfile that is active, and user.is_active is True.
    2. OR they are designated as staff / superuser and active.
    3. OR they belong to the 'Officers' / 'Fire Officers' group and active.
    """
    if not user or not user.is_authenticated:
        return False
    if hasattr(user, 'officer_profile'):
        return user.officer_profile.is_active and user.is_active
    if user.is_staff or user.is_superuser:
        return user.is_active
    return user.groups.filter(name__in=['Officers', 'Fire Officers', 'officers']).exists() and user.is_active


def officer_required(view_func):
    """
    Decorator for views that strictly require Fire Officer authentication.
    - Redirects unauthenticated users to the Officer login page with a ?next= parameter.
    - Denies access to authenticated non-officer users (e.g. Applicants) with an error message.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse('officers:login')
            return redirect(f"{login_url}?next={request.path}")
        if not is_officer(request.user):
            messages.error(
                request,
                "Access denied. This section is restricted to authorized Fire Officers."
            )
            return redirect('officers:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_officer_dashboard_data(user):
    """
    Retrieve officer dashboard statistics and pending applications.
    Queries database-backed values from the Application, Inspection,
    and Deficiency models.
    """
    stats = {
        'total_applications': 0,
        'pending_applications': 0,
        'applications_under_verification': 0,
        'scheduled_inspections': 0,
        'completed_inspections': 0,
        'open_deficiencies': 0,
        'pending_rectification_verification': 0,
        'verified_deficiencies': 0,
        'applications_ready_for_recommendation': 0,
    }
    recent_applications = []

    stats['total_applications'] = Application.objects.count()
    stats['pending_applications'] = Application.objects.filter(
        status__in=['PENDING', 'SUBMITTED', 'pending', 'submitted']
    ).count()
    stats['applications_under_verification'] = Application.objects.filter(
        status__in=[
            'UNDER_REVIEW', 'DOCUMENTS_VERIFIED', 'UNDER_VERIFICATION', 'UNDER_INSPECTION',
            'under_review', 'documents_verified', 'under_verification', 'under_inspection'
        ]
    ).count()

    # Use real Inspection model data
    stats['scheduled_inspections'] = Inspection.objects.filter(
        status__in=[Inspection.STATUS_SCHEDULED, Inspection.STATUS_IN_PROGRESS]
    ).count()
    stats['completed_inspections'] = Inspection.objects.filter(
        status=Inspection.STATUS_COMPLETED
    ).count()

    # Deficiency metrics
    stats['open_deficiencies'] = Deficiency.objects.filter(
        status=Deficiency.STATUS_OPEN
    ).count()
    stats['pending_rectification_verification'] = DeficiencyRectification.objects.filter(
        status__in=[
            DeficiencyRectification.STATUS_SUBMITTED,
            DeficiencyRectification.STATUS_UNDER_REVIEW,
        ]
    ).count()
    stats['verified_deficiencies'] = Deficiency.objects.filter(
        status=Deficiency.STATUS_VERIFIED
    ).count()

    # Applications ready for officer recommendation
    ready_count = 0
    candidate_apps = Application.objects.prefetch_related(
        'documents__verification',
        'inspections__report',
        'deficiencies',
    ).all()
    for app in candidate_apps:
        if get_recommendation_eligibility(app)['is_eligible']:
            ready_count += 1
    stats['applications_ready_for_recommendation'] = ready_count

    recent_applications = list(Application.objects.order_by('-created_at')[:5])

    return stats, recent_applications


@officer_required
def dashboard(request):
    """
    Fire Officer Dashboard view.
    Protected route accessible only to authenticated Fire Officers.
    Displays department statistics, inspection status metrics,
    and the queue of applications awaiting officer review.
    """
    stats, recent_applications = get_officer_dashboard_data(request.user)
    profile = getattr(request.user, 'officer_profile', None)

    upcoming_inspections = list(
        Inspection.objects
        .filter(status__in=[Inspection.STATUS_SCHEDULED, Inspection.STATUS_IN_PROGRESS])
        .select_related('application', 'officer')
        .order_by('scheduled_date', 'scheduled_time')[:5]
    )

    context = {
        'stats': stats,
        'recent_applications': recent_applications,
        'upcoming_inspections': upcoming_inspections,
        'officer': request.user,
        'profile': profile,
    }
    return render(request, 'officers/officer_home.html', context)


# Maintain alias for backward compatibility with Commit 1
officer_home = dashboard


@officer_required
def application_list(request):
    """
    Officer Application Queue view.
    Displays the list of Fire NOC applications requiring Fire Officer review.
    Supports filtering by review status and searching by application ID or building name.
    """
    status_filter = request.GET.get('status', '').strip().upper()
    search_query = request.GET.get('q', '').strip()

    queryset = Application.objects.select_related('applicant').prefetch_related('documents__verification').all()

    if status_filter in ['PENDING', 'UNDER_REVIEW', 'DOCUMENTS_VERIFIED', 'UNDER_INSPECTION', 'APPROVED', 'REJECTED', 'DEFICIENT']:
        queryset = queryset.filter(status=status_filter)

    if search_query:
        queryset = queryset.filter(
            models.Q(application_id__icontains=search_query) |
            models.Q(building_name__icontains=search_query) |
            models.Q(full_name__icontains=search_query) |
            models.Q(city__icontains=search_query)
        )

    # Attach document verification metrics for each application
    applications_data = []
    for app in queryset:
        docs = list(app.documents.all())
        total_docs = len(docs)
        verified_docs = sum(1 for d in docs if hasattr(d, 'verification') and d.verification.status == 'VERIFIED')
        rejected_docs = sum(1 for d in docs if hasattr(d, 'verification') and d.verification.status == 'REJECTED')
        pending_docs = total_docs - verified_docs - rejected_docs

        applications_data.append({
            'application': app,
            'total_docs': total_docs,
            'verified_docs': verified_docs,
            'rejected_docs': rejected_docs,
            'pending_docs': pending_docs,
        })

    profile = getattr(request.user, 'officer_profile', None)

    context = {
        'applications_data': applications_data,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_count': len(applications_data),
        'officer': request.user,
        'profile': profile,
    }
    return render(request, 'officers/application_list.html', context)


@officer_required
def application_detail(request, pk):
    """
    Officer Application Detail view.
    Renders comprehensive application information across 6 organized sections:
    1. Applicant Information
    2. Building Information
    3. Application Information
    4. Documents (with download, verification status, and officer remarks)
    5. Verification Status
    6. Officer Actions
    """
    application = get_object_or_404(
        Application.objects.select_related('applicant'),
        pk=pk
    )

    # Ensure all documents have associated verification records
    doc_list = list(application.documents.select_related('verification').all())
    for doc in doc_list:
        if not hasattr(doc, 'verification'):
            DocumentVerification.objects.get_or_create(document=doc)
    # Re-fetch with fresh verification relations
    doc_list = list(application.documents.select_related('verification', 'verification__verified_by').all())

    review, _ = ApplicationReview.objects.get_or_create(application=application)
    profile = getattr(request.user, 'officer_profile', None)

    total_docs = len(doc_list)
    verified_docs = sum(1 for d in doc_list if hasattr(d, 'verification') and d.verification.status == 'VERIFIED')
    rejected_docs = sum(1 for d in doc_list if hasattr(d, 'verification') and d.verification.status == 'REJECTED')
    pending_docs = total_docs - verified_docs - rejected_docs

    inspections = list(
        application.inspections.select_related('officer').order_by('-created_at')
    )
    latest_inspection = inspections[0] if inspections else None
    has_active_inspection = any(
        i.status in (Inspection.STATUS_SCHEDULED, Inspection.STATUS_IN_PROGRESS)
        for i in inspections
    )
    can_schedule_inspection = (
        application.status in INSPECTION_ELIGIBLE_STATUSES
        and not has_active_inspection
    )

    deficiencies = list(
        application.deficiencies
        .select_related('inspection', 'reported_by')
        .order_by('-created_at')
    )
    deficiency_stats = {
        'total': len(deficiencies),
        'open': sum(1 for d in deficiencies if d.status == Deficiency.STATUS_OPEN),
        'submitted': sum(1 for d in deficiencies if d.status == Deficiency.STATUS_SUBMITTED),
        'verified': sum(1 for d in deficiencies if d.status == Deficiency.STATUS_VERIFIED),
        'closed': sum(1 for d in deficiencies if d.status == Deficiency.STATUS_CLOSED),
        'critical': sum(1 for d in deficiencies if d.severity == Deficiency.SEVERITY_CRITICAL),
    }

    eligibility = get_recommendation_eligibility(application)
    latest_bad_inspection = (
        application.inspections
        .filter(
            status=Inspection.STATUS_COMPLETED,
            report__overall_result__in=[
                InspectionReport.RESULT_UNSATISFACTORY,
                InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            ],
        )
        .order_by('-created_at')
        .first()
    )

    context = {
        'application': application,
        'documents': doc_list,
        'review': review,
        'total_docs': total_docs,
        'verified_docs': verified_docs,
        'rejected_docs': rejected_docs,
        'pending_docs': pending_docs,
        'inspections': inspections,
        'latest_inspection': latest_inspection,
        'has_active_inspection': has_active_inspection,
        'can_schedule_inspection': can_schedule_inspection,
        'deficiencies': deficiencies,
        'deficiency_stats': deficiency_stats,
        'eligibility': eligibility,
        'latest_bad_inspection': latest_bad_inspection,
        'recommendation_choices': ApplicationReview.RECOMMENDATION_CHOICES,
        'officer': request.user,
        'profile': profile,
    }
    return render(request, 'officers/application_detail.html', context)


@officer_required
def document_verify(request, app_id, doc_id):
    """
    Process Officer Document Verification action (Verify or Reject).
    State-changing action strictly requiring POST request.
    Does not delete uploaded files on rejection.
    """
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('officers:application_detail', pk=app_id)

    application = get_object_or_404(Application, pk=app_id)
    document = get_object_or_404(ApplicationDocument, pk=doc_id, application=application)

    action = request.POST.get('action', '').strip().upper()
    remarks = request.POST.get('officer_remarks', '').strip()

    # Data integrity: Do not allow verification without attached file
    if action == 'VERIFY' and not document.file:
        messages.error(request, "Cannot verify document: No valid file is attached to this record.")
        return redirect('officers:application_detail', pk=app_id)

    # Rejection requires reason/remarks
    if action == 'REJECT' and not remarks:
        messages.error(request, "Please provide officer remarks explaining the rejection reason.")
        return redirect('officers:application_detail', pk=app_id)

    verification, _ = DocumentVerification.objects.get_or_create(document=document)

    if action == 'VERIFY':
        verification.status = 'VERIFIED'
        verification.officer_remarks = remarks or 'Document audited and verified in compliance with fire safety norms.'
        verification.verified_by = request.user
        verification.verified_at = timezone.now()
        verification.save()
        messages.success(request, f"Document '{document.document_name}' verified successfully.")
    elif action == 'REJECT':
        verification.status = 'REJECTED'
        verification.officer_remarks = remarks
        verification.verified_by = request.user
        verification.verified_at = timezone.now()
        verification.save()
        messages.warning(request, f"Document '{document.document_name}' rejected. Officer remarks have been recorded.")
    else:
        messages.error(request, "Invalid verification action specified.")

    return redirect('officers:application_detail', pk=app_id)


@officer_required
def application_review(request, app_id):
    """
    Process Officer Application Verification status update.
    Allows advancing the preliminary stage to 'UNDER_REVIEW' or 'DOCUMENTS_VERIFIED'.
    State-changing action strictly requiring POST request.
    """
    if request.method != 'POST':
        messages.error(request, "Invalid request method.")
        return redirect('officers:application_detail', pk=app_id)

    application = get_object_or_404(Application, pk=app_id)
    verification_status = request.POST.get('verification_status', '').strip().upper()
    remarks = request.POST.get('officer_remarks', '').strip()

    valid_statuses = ['UNDER_REVIEW', 'DOCUMENTS_VERIFIED']
    if verification_status not in valid_statuses:
        messages.error(request, "Invalid application verification status specified.")
        return redirect('officers:application_detail', pk=app_id)

    # Validate that no rejected documents exist before marking all documents verified
    if verification_status == 'DOCUMENTS_VERIFIED':
        has_rejected = application.documents.filter(verification__status='REJECTED').exists()
        if has_rejected:
            messages.error(
                request,
                "Cannot mark application as 'Documents Verified': One or more required documents have been rejected."
            )
            return redirect('officers:application_detail', pk=app_id)

    application.status = verification_status
    application.save(update_fields=['status', 'updated_at'])

    review, _ = ApplicationReview.objects.get_or_create(application=application)
    review.status = verification_status
    review.officer_remarks = remarks
    review.reviewed_by = request.user
    review.reviewed_at = timezone.now()
    review.save()

    if verification_status == 'UNDER_REVIEW':
        messages.info(request, f"Application {application.application_id} has been moved to Under Review.")
    else:
        messages.success(
            request,
            f"Application {application.application_id} marked as Documents Verified / Ready for Inspection."
        )

    return redirect('officers:application_detail', pk=app_id)


def officer_login(request):
    """
    Fire Officer login view.
    Authenticates officers using Officer ID, Email, or Username and Password.
    Restricts access strictly to authorized Fire Officers.
    Creates a secure session upon successful authentication and redirects to the dashboard.
    """
    if request.user.is_authenticated and is_officer(request.user):
        return redirect('officers:officer_home')

    if request.method == 'POST':
        identifier = (
            request.POST.get('identifier', '').strip()
            or request.POST.get('username', '').strip()
            or request.POST.get('officer_id', '').strip()
            or request.POST.get('email', '').strip()
        )
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')
        next_url = request.POST.get('next', '').strip() or request.GET.get('next', '').strip()

        # Validate required inputs
        if not identifier or not password:
            messages.error(request, "Both Officer ID / Email and password are required.")
            return render(request, 'officers/login.html', {
                'identifier': identifier,
                'next_url': next_url
            })

        # Resolve identifier to username
        resolved_username = None

        # 1. Search by Officer ID in OfficerProfile
        profile = OfficerProfile.objects.filter(officer_id__iexact=identifier).select_related('user').first()
        if profile:
            resolved_username = profile.user.username

        # 2. Search by Email
        if not resolved_username:
            user_by_email = User.objects.filter(email__iexact=identifier).first()
            if user_by_email:
                resolved_username = user_by_email.username

        # 3. Search by Username
        if not resolved_username:
            user_by_username = User.objects.filter(username__iexact=identifier).first()
            if user_by_username:
                resolved_username = user_by_username.username

        # Fallback to literal identifier
        if not resolved_username:
            resolved_username = identifier

        # Securely authenticate using Django auth backend (PBKDF2-SHA256 password hash comparison)
        user = authenticate(request, username=resolved_username, password=password)

        if user is not None:
            # Check user active status
            if not user.is_active:
                messages.error(
                    request,
                    "Your officer account has been deactivated. Please contact the department administrator."
                )
                return render(request, 'officers/login.html', {
                    'identifier': identifier,
                    'next_url': next_url
                })

            # Check officer authorization
            if not is_officer(user):
                messages.error(
                    request,
                    "Access denied. This account does not have Fire Officer privileges. "
                    "Applicants must use the Applicant Portal."
                )
                return render(request, 'officers/login.html', {
                    'identifier': identifier,
                    'next_url': next_url
                })

            # Establish authenticated session
            login(request, user)

            if not remember_me:
                request.session.set_expiry(0)  # Expires on browser close
            else:
                request.session.set_expiry(1209600)  # 2 weeks

            officer_name = user.get_full_name() or user.username
            messages.success(request, f"Welcome back, Officer {officer_name}!")

            # Validate redirect URL to prevent open redirect vulnerabilities
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('officers:officer_home')
        else:
            # Check if user exists with correct password but has been deactivated
            user_obj = User.objects.filter(username__iexact=resolved_username).first()
            if user_obj and user_obj.check_password(password) and not user_obj.is_active:
                messages.error(
                    request,
                    "Your officer account has been deactivated. Please contact the department administrator."
                )
                return render(request, 'officers/login.html', {
                    'identifier': identifier,
                    'next_url': next_url
                })

            messages.error(
                request,
                "Invalid Officer ID / Email or password. Please verify your credentials and try again."
            )
            return render(request, 'officers/login.html', {
                'identifier': identifier,
                'next_url': next_url
            })

    next_url = request.GET.get('next', '').strip()
    return render(request, 'officers/login.html', {'next_url': next_url})


def officer_logout(request):
    """
    Fire Officer logout view.
    Terminates the user session, clears session cookies,
    and redirects to the Officer login page with a success message.
    Accepts both POST requests and GET fallbacks.
    """
    logout(request)
    messages.success(request, "You have been successfully logged out of the Fire Officer Portal.")
    return redirect('officers:login')


# ===========================================================================
# Commit 4 — Inspection Management Views
# ===========================================================================

# Checklist item types in display order (matches model ITEM_TYPES)
CHECKLIST_ITEM_TYPES = [t[0] for t in InspectionChecklistItem.ITEM_TYPES]

# Application statuses that make an application eligible for inspection scheduling
INSPECTION_ELIGIBLE_STATUSES = {'DOCUMENTS_VERIFIED', 'UNDER_INSPECTION', 'DEFICIENT'}


def _can_modify_inspection(user, inspection):
    """
    Ensure only the assigned inspecting officer (or superuser) can modify
    an inspection's state, checklist, or report.
    """
    if user.is_superuser:
        return True
    return inspection.officer_id in (None, user.id)


def _ensure_checklist(inspection):
    """Create missing checklist items for an inspection (idempotent)."""
    existing_types = set(
        inspection.checklist_items.values_list('item_type', flat=True)
    )
    to_create = [
        InspectionChecklistItem(
            inspection=inspection,
            item_type=item_type,
            status=InspectionChecklistItem.STATUS_NOT_APPLICABLE,
        )
        for item_type in CHECKLIST_ITEM_TYPES
        if item_type not in existing_types
    ]
    if to_create:
        InspectionChecklistItem.objects.bulk_create(to_create)


@officer_required
def inspection_list(request):
    """
    Display all inspections visible to the authenticated officer.
    Supports filtering by status.
    """
    status_filter = request.GET.get('status', '').strip().upper()

    qs = (
        Inspection.objects
        .select_related('application', 'officer')
        .all()
    )

    valid_statuses = {s[0] for s in Inspection.STATUS_CHOICES}
    if status_filter in valid_statuses:
        qs = qs.filter(status=status_filter)

    profile = getattr(request.user, 'officer_profile', None)
    context = {
        'inspections': qs,
        'status_filter': status_filter,
        'total_count': qs.count(),
        'officer': request.user,
        'profile': profile,
        'STATUS_CHOICES': Inspection.STATUS_CHOICES,
    }
    return render(request, 'officers/inspection_list.html', context)


@officer_required
def schedule_inspection(request, app_id):
    """
    Schedule a new inspection for an eligible application.
    GET  → show scheduling form.
    POST → validate and create Inspection; advance Application status.
    """
    application = get_object_or_404(Application, pk=app_id)
    profile = getattr(request.user, 'officer_profile', None)

    # Eligibility check
    if application.status not in INSPECTION_ELIGIBLE_STATUSES:
        messages.error(
            request,
            f"Application {application.application_id} is not eligible for inspection scheduling. "
            f"Current status: {application.get_status_display()}. "
            "Only applications with 'Documents Verified' or 'Under Inspection' status can be scheduled."
        )
        return redirect('officers:application_detail', pk=app_id)

    # Prevent scheduling if an active inspection already exists
    if application.inspections.filter(
        status__in=[Inspection.STATUS_SCHEDULED, Inspection.STATUS_IN_PROGRESS]
    ).exists():
        messages.warning(
            request,
            f"Application {application.application_id} already has an active scheduled or in-progress inspection."
        )
        return redirect('officers:application_detail', pk=app_id)

    if request.method == 'POST':
        scheduled_date_str = request.POST.get('scheduled_date', '').strip()
        scheduled_time_str = request.POST.get('scheduled_time', '').strip()
        location = request.POST.get('location', '').strip()
        officer_remarks = request.POST.get('officer_remarks', '').strip()

        errors = []

        # Validate date
        scheduled_date = None
        try:
            scheduled_date = datetime.date.fromisoformat(scheduled_date_str)
        except ValueError:
            errors.append("Please enter a valid inspection date.")

        # Validate time
        scheduled_time = None
        try:
            scheduled_time = datetime.time.fromisoformat(scheduled_time_str)
        except ValueError:
            errors.append("Please enter a valid inspection time.")

        # Validate date and time are not in the past
        if scheduled_date and scheduled_time:
            scheduled_dt = timezone.make_aware(
                datetime.datetime.combine(scheduled_date, scheduled_time),
                timezone.get_current_timezone()
            )
            if scheduled_dt < timezone.now():
                errors.append("Inspection date and time cannot be in the past.")
        elif scheduled_date and scheduled_date < timezone.localdate():
            errors.append("Inspection date cannot be in the past.")

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'officers/schedule_inspection.html', {
                'application': application,
                'officer': request.user,
                'profile': profile,
                'form_data': {
                    'scheduled_date': scheduled_date_str,
                    'scheduled_time': scheduled_time_str,
                    'location': location,
                    'officer_remarks': officer_remarks,
                },
            })

        # Create inspection — officer is always the authenticated user (never from POST)
        inspection = Inspection.objects.create(
            application=application,
            officer=request.user,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            location=location or application.building_address,
            status=Inspection.STATUS_SCHEDULED,
            officer_remarks=officer_remarks,
        )

        # Advance application status to UNDER_INSPECTION
        application.status = 'UNDER_INSPECTION'
        application.save(update_fields=['status', 'updated_at'])

        # Create the full checklist
        _ensure_checklist(inspection)

        messages.success(
            request,
            f"Inspection scheduled for {application.application_id} on "
            f"{scheduled_date.strftime('%d %b %Y')} at {inspection.scheduled_time.strftime('%H:%M')}."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection.pk)

    # GET — render blank form
    return render(request, 'officers/schedule_inspection.html', {
        'application': application,
        'officer': request.user,
        'profile': profile,
        'form_data': {
            'scheduled_date': '',
            'scheduled_time': '',
            'location': application.building_address,
            'officer_remarks': '',
        },
    })


@officer_required
def inspection_detail(request, inspection_id):
    """
    Detail view for a single inspection.
    Shows application info, inspection info, checklist, report and state-transition actions.
    """
    inspection = get_object_or_404(
        Inspection.objects.select_related('application', 'officer'),
        pk=inspection_id
    )
    _ensure_checklist(inspection)

    checklist_items = list(
        inspection.checklist_items.order_by('item_type')
    )
    report = getattr(inspection, 'report', None)
    profile = getattr(request.user, 'officer_profile', None)
    deficiencies = list(
        inspection.deficiencies.select_related('reported_by').order_by('-created_at')
    )
    can_create_deficiency = (
        inspection.status == Inspection.STATUS_COMPLETED
        and report is not None
        and report.overall_result in (
            InspectionReport.RESULT_UNSATISFACTORY,
            InspectionReport.RESULT_REQUIRES_RECTIFICATION,
        )
    )

    context = {
        'inspection': inspection,
        'checklist_items': checklist_items,
        'report': report,
        'deficiencies': deficiencies,
        'can_create_deficiency': can_create_deficiency,
        'can_modify': _can_modify_inspection(request.user, inspection),
        'officer': request.user,
        'profile': profile,
        'STATUS_SCHEDULED': Inspection.STATUS_SCHEDULED,
        'STATUS_IN_PROGRESS': Inspection.STATUS_IN_PROGRESS,
        'STATUS_COMPLETED': Inspection.STATUS_COMPLETED,
        'STATUS_CANCELLED': Inspection.STATUS_CANCELLED,
        'RESULT_CHOICES': InspectionReport.RESULT_CHOICES,
        'checklist_status_choices': InspectionChecklistItem.STATUS_CHOICES,
    }
    return render(request, 'officers/inspection_detail.html', context)


@officer_required
def inspection_start(request, inspection_id):
    """Transition inspection from Scheduled → In Progress."""
    if request.method != 'POST':
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    inspection = get_object_or_404(Inspection, pk=inspection_id)

    if not _can_modify_inspection(request.user, inspection):
        messages.error(request, "You are not authorized to modify another officer's inspection.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    if not inspection.can_transition_to(Inspection.STATUS_IN_PROGRESS):
        messages.error(
            request,
            f"Cannot start inspection: current status is '{inspection.get_status_display()}'. "
            "Only 'Scheduled' inspections can be started."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    inspection.status = Inspection.STATUS_IN_PROGRESS
    inspection.started_at = timezone.now()
    inspection.save(update_fields=['status', 'started_at', 'updated_at'])

    messages.success(request, "Inspection started. Please complete the safety checklist and submit your report.")
    return redirect('officers:inspection_detail', inspection_id=inspection_id)


@officer_required
def inspection_complete(request, inspection_id):
    """
    Transition inspection from In Progress → Completed.
    Requires the officer to submit the inspection report as part of the same POST.
    POST fields: overall_result, general_observations, officer_remarks
    """
    if request.method != 'POST':
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    inspection = get_object_or_404(Inspection, pk=inspection_id)

    if not _can_modify_inspection(request.user, inspection):
        messages.error(request, "You are not authorized to modify another officer's inspection.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    if not inspection.can_transition_to(Inspection.STATUS_COMPLETED):
        messages.error(
            request,
            f"Cannot complete inspection: current status is '{inspection.get_status_display()}'. "
            "Only 'In Progress' inspections can be completed."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    overall_result = request.POST.get('overall_result', '').strip()
    general_observations = request.POST.get('general_observations', '').strip()
    officer_remarks = request.POST.get('officer_remarks', '').strip()

    valid_results = {r[0] for r in InspectionReport.RESULT_CHOICES}
    if overall_result not in valid_results:
        messages.error(request, "Please select a valid overall inspection result before completing.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    if not general_observations:
        messages.error(request, "General observations are required before completing the inspection.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    # Save checklist if posted
    _save_checklist(request, inspection)

    now = timezone.now()

    # Create or update report
    InspectionReport.objects.update_or_create(
        inspection=inspection,
        defaults={
            'overall_result': overall_result,
            'general_observations': general_observations,
            'officer_remarks': officer_remarks,
            'completed_at': now,
        }
    )

    inspection.status = Inspection.STATUS_COMPLETED
    inspection.completed_at = now
    inspection.save(update_fields=['status', 'completed_at', 'updated_at'])

    messages.success(
        request,
        f"Inspection completed. Report recorded as '{InspectionReport(overall_result=overall_result).get_overall_result_display()}'."
    )
    return redirect('officers:inspection_detail', inspection_id=inspection_id)


@officer_required
def inspection_cancel(request, inspection_id):
    """Transition inspection from Scheduled or In Progress → Cancelled."""
    if request.method != 'POST':
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    inspection = get_object_or_404(Inspection, pk=inspection_id)

    if not _can_modify_inspection(request.user, inspection):
        messages.error(request, "You are not authorized to modify another officer's inspection.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    if not inspection.can_transition_to(Inspection.STATUS_CANCELLED):
        messages.error(
            request,
            f"Cannot cancel inspection: current status is '{inspection.get_status_display()}'."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    cancel_reason = request.POST.get('cancel_reason', '').strip()
    if cancel_reason:
        inspection.officer_remarks = (
            f"{inspection.officer_remarks}\n\nCancellation reason: {cancel_reason}".strip()
        )

    inspection.status = Inspection.STATUS_CANCELLED
    inspection.save(update_fields=['status', 'officer_remarks', 'updated_at'])

    messages.warning(request, f"Inspection #{inspection.pk} has been cancelled.")
    return redirect('officers:inspection_detail', inspection_id=inspection_id)


@officer_required
def inspection_checklist_save(request, inspection_id):
    """
    Save checklist item statuses while inspection is In Progress.
    POST only. Redirects back to the detail page.
    """
    if request.method != 'POST':
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    inspection = get_object_or_404(Inspection, pk=inspection_id)

    if not _can_modify_inspection(request.user, inspection):
        messages.error(request, "You are not authorized to modify another officer's inspection.")
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    if not inspection.is_editable:
        messages.error(
            request,
            "Checklist can only be updated while the inspection is 'In Progress'."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection_id)

    _save_checklist(request, inspection)
    messages.success(request, "Checklist updated successfully.")
    return redirect('officers:inspection_detail', inspection_id=inspection_id)


def _save_checklist(request, inspection):
    """
    Internal helper: persist checklist item statuses and remarks from POST data.
    Only processes items that belong to the given inspection.
    """
    _ensure_checklist(inspection)
    valid_statuses = {s[0] for s in InspectionChecklistItem.STATUS_CHOICES}
    items = {item.item_type: item for item in inspection.checklist_items.all()}

    for item_type, item in items.items():
        status_key = f'checklist_{item_type}_status'
        remarks_key = f'checklist_{item_type}_remarks'

        updated = False
        if status_key in request.POST:
            new_status = request.POST.get(status_key, '').strip()
            if new_status in valid_statuses and new_status != item.status:
                item.status = new_status
                updated = True
        if remarks_key in request.POST:
            new_remarks = request.POST.get(remarks_key, '').strip()
            if new_remarks != item.remarks:
                item.remarks = new_remarks
                updated = True
        if updated:
            item.save(update_fields=['status', 'remarks', 'updated_at'])


# ===========================================================================
# Commit 5 — Deficiency, Rectification & Officer Recommendation Views
# ===========================================================================

ALLOWED_EVIDENCE_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_EVIDENCE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


@officer_required
def deficiency_list(request):
    """
    Officer Deficiencies Queue view.
    Supports filtering by status and severity, and searching by Application ID,
    applicant name, or deficiency title.
    """
    status_filter = request.GET.get('status', '').strip().upper()
    severity_filter = request.GET.get('severity', '').strip().upper()
    search_query = request.GET.get('q', '').strip()

    qs = (
        Deficiency.objects
        .select_related('application', 'inspection', 'reported_by')
        .all()
    )

    valid_statuses = {s[0] for s in Deficiency.STATUS_CHOICES}
    if status_filter in valid_statuses:
        qs = qs.filter(status=status_filter)
    else:
        status_filter = ''

    valid_severities = {s[0] for s in Deficiency.SEVERITY_CHOICES}
    if severity_filter in valid_severities:
        qs = qs.filter(severity=severity_filter)
    else:
        severity_filter = ''

    if search_query:
        qs = qs.filter(
            models.Q(application__application_id__icontains=search_query) |
            models.Q(application__full_name__icontains=search_query) |
            models.Q(title__icontains=search_query)
        )

    profile = getattr(request.user, 'officer_profile', None)
    context = {
        'deficiencies': qs,
        'total_count': qs.count(),
        'status_filter': status_filter,
        'severity_filter': severity_filter,
        'search_query': search_query,
        'STATUS_CHOICES': Deficiency.STATUS_CHOICES,
        'SEVERITY_CHOICES': Deficiency.SEVERITY_CHOICES,
        'officer': request.user,
        'profile': profile,
    }
    return render(request, 'officers/deficiency_list.html', context)


@officer_required
def deficiency_create(request, inspection_id):
    """
    Create a deficiency from a Completed inspection whose report is
    Unsatisfactory or Requires Rectification.
    Never trusts reported_by or application from POST data.
    """
    inspection = get_object_or_404(
        Inspection.objects.select_related('application'),
        pk=inspection_id
    )
    report = getattr(inspection, 'report', None)
    profile = getattr(request.user, 'officer_profile', None)

    is_eligible_inspection = (
        inspection.status == Inspection.STATUS_COMPLETED
        and report is not None
        and report.overall_result in (
            InspectionReport.RESULT_UNSATISFACTORY,
            InspectionReport.RESULT_REQUIRES_RECTIFICATION,
        )
    )
    if not is_eligible_inspection:
        messages.error(
            request,
            "Deficiencies can only be created for completed inspections with an "
            "'Unsatisfactory' or 'Requires Rectification' report."
        )
        return redirect('officers:inspection_detail', inspection_id=inspection.pk)

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        severity = request.POST.get('severity', '').strip().upper()
        officer_remarks = request.POST.get('officer_remarks', '').strip()

        errors = []
        if not title:
            errors.append("Deficiency title is required.")
        if not description:
            errors.append("Deficiency description is required.")
        valid_severities = {s[0] for s in Deficiency.SEVERITY_CHOICES}
        if severity not in valid_severities:
            errors.append("Please select a valid severity level.")

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'officers/deficiency_create.html', {
                'inspection': inspection,
                'application': inspection.application,
                'report': report,
                'SEVERITY_CHOICES': Deficiency.SEVERITY_CHOICES,
                'officer': request.user,
                'profile': profile,
                'form_data': {
                    'title': title,
                    'description': description,
                    'severity': severity,
                    'officer_remarks': officer_remarks,
                },
            })

        deficiency = Deficiency.objects.create(
            application=inspection.application,
            inspection=inspection,
            reported_by=request.user,
            title=title,
            description=description,
            severity=severity,
            status=Deficiency.STATUS_OPEN,
            officer_remarks=officer_remarks,
        )
        if inspection.application.status != 'DEFICIENT':
            inspection.application.status = 'DEFICIENT'
            inspection.application.save(update_fields=['status', 'updated_at'])
        messages.success(request, f"Deficiency DEF-{deficiency.pk} '{deficiency.title}' logged successfully.")
        return redirect('officers:deficiency_detail', deficiency_id=deficiency.pk)

    return render(request, 'officers/deficiency_create.html', {
        'inspection': inspection,
        'application': inspection.application,
        'report': report,
        'SEVERITY_CHOICES': Deficiency.SEVERITY_CHOICES,
        'officer': request.user,
        'profile': profile,
        'form_data': {
            'title': '',
            'description': '',
            'severity': Deficiency.SEVERITY_MAJOR,
            'officer_remarks': '',
        },
    })


@officer_required
def deficiency_detail(request, deficiency_id):
    """
    Display full details of a Deficiency, associated Application & Inspection,
    rectification submissions, and state-machine actions.
    """
    deficiency = get_object_or_404(
        Deficiency.objects.select_related('application', 'inspection', 'reported_by', 'closed_by'),
        pk=deficiency_id
    )
    inspection_report = getattr(deficiency.inspection, 'report', None)
    rectifications = list(
        deficiency.rectifications.select_related('submitted_by', 'reviewed_by').order_by('-submitted_at')
    )
    pending_rectification = next(
        (r for r in rectifications if r.status in (DeficiencyRectification.STATUS_SUBMITTED, DeficiencyRectification.STATUS_UNDER_REVIEW)),
        None
    )
    profile = getattr(request.user, 'officer_profile', None)

    context = {
        'deficiency': deficiency,
        'application': deficiency.application,
        'inspection': deficiency.inspection,
        'inspection_report': inspection_report,
        'rectifications': rectifications,
        'pending_rectification': pending_rectification,
        'officer': request.user,
        'profile': profile,
    }
    return render(request, 'officers/deficiency_detail.html', context)


@officer_required
def deficiency_rectify(request, deficiency_id):
    """
    Record a rectification submission for an Open deficiency and transition
    Deficiency: Open -> Submitted for Verification.
    Validates optional evidence file type and size.
    """
    if request.method != 'POST':
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency = get_object_or_404(Deficiency, pk=deficiency_id)

    if deficiency.is_closed or not deficiency.can_transition_to(Deficiency.STATUS_SUBMITTED):
        messages.error(
            request,
            f"Cannot submit rectification: deficiency is currently '{deficiency.get_status_display()}'."
        )
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    description = request.POST.get('description', '').strip()
    evidence_file = request.FILES.get('evidence_file')

    if not description:
        messages.error(request, "Rectification description is required.")
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    if evidence_file is not None:
        ext = os.path.splitext(evidence_file.name)[1].lower()
        if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
            messages.error(
                request,
                "Invalid evidence file format. Allowed formats: PDF, JPG, JPEG, PNG."
            )
            return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)
        if evidence_file.size > MAX_EVIDENCE_SIZE_BYTES:
            messages.error(
                request,
                "Evidence file size exceeds the 5 MB limit."
            )
            return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    DeficiencyRectification.objects.create(
        deficiency=deficiency,
        submitted_by=request.user,
        description=description,
        evidence_file=evidence_file,
        status=DeficiencyRectification.STATUS_SUBMITTED,
    )

    deficiency.status = Deficiency.STATUS_SUBMITTED
    deficiency.save(update_fields=['status', 'updated_at'])

    messages.success(request, "Rectification submitted for verification.")
    return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)


@officer_required
def rectification_review(request, deficiency_id, rect_id):
    """
    Officer reviews a submitted rectification (Accept or Reject).
    - Accept: Deficiency Submitted for Verification -> Verified
    - Reject: Deficiency Submitted for Verification -> Rejected -> Open
    Never trusts reviewed_by from POST data.
    """
    if request.method != 'POST':
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency = get_object_or_404(Deficiency, pk=deficiency_id)
    rectification = get_object_or_404(DeficiencyRectification, pk=rect_id, deficiency=deficiency)

    if deficiency.is_closed or deficiency.status != Deficiency.STATUS_SUBMITTED:
        messages.error(
            request,
            f"Cannot review rectification: deficiency status is '{deficiency.get_status_display()}'."
        )
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    action = request.POST.get('action', '').strip().upper()
    review_remarks = request.POST.get('review_remarks', '').strip()
    now = timezone.now()

    if action == 'ACCEPT':
        if not deficiency.can_transition_to(Deficiency.STATUS_VERIFIED):
            messages.error(request, "Invalid state transition for acceptance.")
            return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

        rectification.status = DeficiencyRectification.STATUS_ACCEPTED
        rectification.reviewed_by = request.user
        rectification.reviewed_at = now
        rectification.review_remarks = review_remarks or 'Rectification verified and accepted.'
        rectification.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_remarks'])

        deficiency.status = Deficiency.STATUS_VERIFIED
        if review_remarks:
            deficiency.officer_remarks = review_remarks
        deficiency.save(update_fields=['status', 'officer_remarks', 'updated_at'])

        has_unresolved = deficiency.application.deficiencies.exclude(
            status__in=[Deficiency.STATUS_VERIFIED, Deficiency.STATUS_CLOSED]
        ).exists()
        if not has_unresolved and deficiency.application.status == 'DEFICIENT':
            deficiency.application.status = 'UNDER_INSPECTION'
            deficiency.application.save(update_fields=['status', 'updated_at'])

        messages.success(request, f"Rectification accepted. DEF-{deficiency.pk} is now Verified.")

    elif action == 'REJECT':
        if not review_remarks:
            messages.error(request, "Please provide review remarks explaining why the rectification was rejected.")
            return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

        if not deficiency.can_transition_to(Deficiency.STATUS_REJECTED):
            messages.error(request, "Invalid state transition for rejection.")
            return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

        rectification.status = DeficiencyRectification.STATUS_REJECTED
        rectification.reviewed_by = request.user
        rectification.reviewed_at = now
        rectification.review_remarks = review_remarks
        rectification.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_remarks'])

        # Submitted for Verification -> Rejected -> Open so applicant can resubmit
        deficiency.status = Deficiency.STATUS_REJECTED
        deficiency.officer_remarks = review_remarks
        deficiency.save(update_fields=['status', 'officer_remarks', 'updated_at'])

        if deficiency.can_transition_to(Deficiency.STATUS_OPEN):
            deficiency.status = Deficiency.STATUS_OPEN
            deficiency.save(update_fields=['status', 'updated_at'])

        messages.warning(
            request,
            f"Rectification rejected. DEF-{deficiency.pk} has been reopened for further rectification."
        )
    else:
        messages.error(request, "Invalid review action specified.")

    return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)


@officer_required
def deficiency_reopen(request, deficiency_id):
    """Transition a Rejected deficiency back to Open (POST only)."""
    if request.method != 'POST':
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency = get_object_or_404(Deficiency, pk=deficiency_id)
    if not deficiency.can_transition_to(Deficiency.STATUS_OPEN):
        messages.error(
            request,
            f"Cannot reopen deficiency from '{deficiency.get_status_display()}'."
        )
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency.status = Deficiency.STATUS_OPEN
    deficiency.save(update_fields=['status', 'updated_at'])
    messages.info(request, f"DEF-{deficiency.pk} reopened.")
    return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)


@officer_required
def deficiency_close(request, deficiency_id):
    """
    Close a Verified deficiency (Verified -> Closed).
    Sets resolved_at and closed_by. Closed deficiencies become read-only.
    """
    if request.method != 'POST':
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency = get_object_or_404(Deficiency, pk=deficiency_id)
    if not deficiency.can_transition_to(Deficiency.STATUS_CLOSED):
        messages.error(
            request,
            f"Cannot close deficiency: current status is '{deficiency.get_status_display()}'. "
            "Only 'Verified' deficiencies can be closed."
        )
        return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)

    deficiency.status = Deficiency.STATUS_CLOSED
    deficiency.resolved_at = timezone.now()
    deficiency.closed_by = request.user
    deficiency.save(update_fields=['status', 'resolved_at', 'closed_by', 'updated_at'])

    has_unresolved = deficiency.application.deficiencies.exclude(
        status__in=[Deficiency.STATUS_VERIFIED, Deficiency.STATUS_CLOSED]
    ).exists()
    if not has_unresolved and deficiency.application.status == 'DEFICIENT':
        deficiency.application.status = 'UNDER_INSPECTION'
        deficiency.application.save(update_fields=['status', 'updated_at'])

    messages.success(request, f"DEF-{deficiency.pk} has been closed and marked resolved.")
    return redirect('officers:deficiency_detail', deficiency_id=deficiency_id)


@officer_required
def application_recommend(request, app_id):
    """
    Record Officer Recommendation for an Application
    (Pending / Requires Rectification / Recommended for Approval / Not Recommended).
    Does NOT issue final Fire NOC or perform Admin approval.
    Enforces get_recommendation_eligibility() for 'Recommended for Approval'.
    """
    if request.method != 'POST':
        return redirect('officers:application_detail', pk=app_id)

    application = get_object_or_404(Application, pk=app_id)
    recommendation = request.POST.get('recommendation', '').strip().upper()
    recommendation_remarks = request.POST.get('recommendation_remarks', '').strip()

    valid_recommendations = {r[0] for r in ApplicationReview.RECOMMENDATION_CHOICES}
    if recommendation not in valid_recommendations:
        messages.error(request, "Invalid recommendation selection.")
        return redirect('officers:application_detail', pk=app_id)

    if recommendation == ApplicationReview.RECOMMENDATION_APPROVED:
        eligibility = get_recommendation_eligibility(application)
        if not eligibility['is_eligible']:
            reasons = "; ".join(eligibility['blocking_reasons'])
            messages.error(
                request,
                f"Application is not eligible for 'Recommended for Approval': {reasons}."
            )
            return redirect('officers:application_detail', pk=app_id)

    review, _ = ApplicationReview.objects.get_or_create(application=application)
    review.recommendation = recommendation
    review.recommendation_remarks = recommendation_remarks
    review.recommended_by = request.user
    review.recommended_at = timezone.now()
    review.save(update_fields=['recommendation', 'recommendation_remarks', 'recommended_by', 'recommended_at'])

    messages.success(
        request,
        f"Officer recommendation updated to '{review.get_recommendation_display()}'."
    )
    return redirect('officers:application_detail', pk=app_id)
