from functools import wraps
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
from .models import OfficerProfile, DocumentVerification, ApplicationReview


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
    Queries database-backed values from the Application model.
    """
    stats = {
        'total_applications': 0,
        'pending_applications': 0,
        'applications_under_verification': 0,
        'scheduled_inspections': 0,
        'completed_inspections': 0,
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

    recent_applications = list(Application.objects.order_by('-created_at')[:5])

    # Dynamic inspection check if Inspection model is implemented in future commits
    Inspection = None
    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            model_name = model.__name__.lower()
            if model_name in ('inspection', 'siteinspection', 'fieldinspection'):
                Inspection = model
                break
        if Inspection:
            break

    if Inspection is not None:
        stats['scheduled_inspections'] = Inspection.objects.filter(
            status__in=['SCHEDULED', 'ASSIGNED', 'scheduled', 'assigned']
        ).count()
        stats['completed_inspections'] = Inspection.objects.filter(
            status__in=['COMPLETED', 'PASSED', 'CLEARED', 'completed', 'passed', 'cleared']
        ).count()

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

    context = {
        'stats': stats,
        'recent_applications': recent_applications,
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

    if status_filter in ['PENDING', 'UNDER_REVIEW', 'DOCUMENTS_VERIFIED', 'UNDER_INSPECTION', 'APPROVED', 'REJECTED']:
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

    context = {
        'application': application,
        'documents': doc_list,
        'review': review,
        'total_docs': total_docs,
        'verified_docs': verified_docs,
        'rejected_docs': rejected_docs,
        'pending_docs': pending_docs,
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
