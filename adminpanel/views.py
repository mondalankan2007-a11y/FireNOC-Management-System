from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.management import call_command
from django.core.management.base import CommandError
from django.shortcuts import redirect, render
from django.urls import reverse

from . import statistics
from .models import AuditLog


def is_admin(user):
    """
    Whether a user may act as a departmental administrator.

    The three roles in this system are distinguished by what a user *has*,
    not by a role column:

      - an applicant is a plain account,
      - a fire officer owns an OfficerProfile,
      - an administrator carries is_staff.

    Officers are never given is_staff, so the two sets do not overlap in
    practice. The officer_profile test below enforces that from this side
    regardless: an account that is somehow both is treated as an officer, the
    narrower role, rather than silently gaining admin rights.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if hasattr(user, 'officer_profile'):
        return False
    return user.is_staff


def admin_required(view_func):
    """
    Restrict a view to administrators.

    An anonymous visitor is sent to the admin sign-in page with ?next= so the
    page they asked for is reachable after signing in. A signed-in user who is
    not an administrator is refused and sent home: they are already
    authenticated, so offering the sign-in form again would be a loop.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('adminpanel:login')}?next={request.path}")
        if not is_admin(request.user):
            messages.error(
                request,
                'That area is restricted to departmental administrators.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped


def admin_login(request):
    """Sign-in page for departmental administrators."""
    if is_admin(request.user):
        return redirect('adminpanel:admin_home')

    next_url = request.GET.get('next') or request.POST.get('next') or ''
    context = {'next': next_url}

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        context['username'] = username

        if not username or not password:
            messages.error(request, 'Enter both your username and password.')
            return render(request, 'adminpanel/login.html', context)

        user = authenticate(request, username=username, password=password)

        if user is None:
            # Deliberately not saying which of the two was wrong: that would
            # confirm whether an account exists.
            messages.error(request, 'Invalid username or password.')
            AuditLog.record(
                AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM,
                summary=f'Failed admin sign-in for "{username[:80]}"',
                ip_address=_client_ip(request))
            return render(request, 'adminpanel/login.html', context)

        if not is_admin(user):
            messages.error(
                request, 'That account does not have administrator access.')
            AuditLog.record(
                AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=user,
                summary='Admin sign-in refused: account is not an administrator',
                ip_address=_client_ip(request))
            return render(request, 'adminpanel/login.html', context)

        login(request, user)
        AuditLog.record(
            AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=user,
            summary='Administrator signed in',
            ip_address=_client_ip(request))
        messages.success(request, f'Signed in as {user.get_full_name() or user.username}.')
        return redirect(next_url or 'adminpanel:admin_home')

    return render(request, 'adminpanel/login.html', context)


def admin_logout(request):
    """Sign out of the admin portal. POST only, so a link cannot trigger it."""
    if request.method != 'POST':
        return redirect('adminpanel:admin_home')
    if request.user.is_authenticated:
        AuditLog.record(
            AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=request.user,
            summary='Administrator signed out', ip_address=_client_ip(request))
    logout(request)
    messages.success(request, 'You have been signed out.')
    return redirect('adminpanel:login')


@admin_required
def dashboard(request):
    """
    Department dashboard.

    Each figure is labelled with where it came from, because the sources
    differ: the status breakdown is precomputed and only as fresh as the last
    refresh, while everything else is live. Showing that distinction is more
    useful than hiding it behind a single "statistics" heading.
    """
    breakdown, precomputed = statistics.status_breakdown()

    context = {
        'counts': statistics.headline_counts(),
        'status_breakdown': breakdown,
        'status_is_precomputed': precomputed,
        'last_refreshed_at': statistics.last_refreshed_at(),
        'deficiencies': statistics.deficiency_summary(),
        'officers': statistics.officer_workload(),
        'oldest_waiting': statistics.oldest_waiting(),
    }
    return render(request, 'adminpanel/dashboard.html', context)


@admin_required
def refresh_statistics(request):
    """Refresh the materialized view behind the status breakdown."""
    if request.method != 'POST':
        return redirect('adminpanel:dashboard')

    try:
        call_command('refreshviews', verbosity=0)
    except CommandError as exc:
        messages.error(request, f'Statistics could not be refreshed: {exc}')
        return redirect('adminpanel:dashboard')

    # refreshviews records the refresh itself; this entry adds the actor,
    # which the command cannot know.
    AuditLog.record(
        AuditLog.ACTION_UPDATE, AuditLog.ENTITY_SYSTEM, actor=request.user,
        summary=statistics.REFRESH_SUMMARY, ip_address=_client_ip(request))
    messages.success(request, 'Statistics refreshed.')
    return redirect('adminpanel:dashboard')


@admin_required
def admin_home(request):
    """
    Admin Module landing page.

    Entry point for the Admin + Database + NOC module. Later commits attach
    the department dashboard, applicant/officer management, application
    monitoring, NOC issuance and reporting views beneath this namespace.
    """
    return render(request, 'adminpanel/admin_home.html')


def _client_ip(request):
    """Best-effort client address for the audit record."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None
