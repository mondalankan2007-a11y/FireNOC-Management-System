from functools import wraps
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from .models import OfficerProfile


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
    
    Coordinates dynamically with team modules:
    - Queries installed apps for Application or Inspection models.
    - If models exist, queries database-backed values using Django ORM aggregations.
    - If models do not yet exist, gracefully provides clean defaults (zeros and empty list),
      allowing Commit 3 to connect the real application verification and inspection workflow.
    """
    stats = {
        'total_applications': 0,
        'pending_applications': 0,
        'applications_under_verification': 0,
        'scheduled_inspections': 0,
        'completed_inspections': 0,
    }
    recent_applications = []

    Application = None
    Inspection = None

    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            model_name = model.__name__.lower()
            if model_name in ('application', 'nocapplication', 'firenocapplication'):
                Application = model
            elif model_name in ('inspection', 'siteinspection', 'fieldinspection'):
                Inspection = model

    if Application is not None:
        stats['total_applications'] = Application.objects.count()
        stats['pending_applications'] = Application.objects.filter(
            status__in=['PENDING', 'SUBMITTED', 'pending', 'submitted']
        ).count()
        stats['applications_under_verification'] = Application.objects.filter(
            status__in=[
                'UNDER_REVIEW', 'UNDER_VERIFICATION', 'UNDER_INSPECTION',
                'under_review', 'under_verification', 'under_inspection'
            ]
        ).count()

        ordering = '-created_at' if hasattr(Application, 'created_at') else '-id'
        recent_applications = list(Application.objects.order_by(ordering)[:5])

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
