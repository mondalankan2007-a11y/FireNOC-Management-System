from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.paginator import Paginator
from django.utils.http import urlencode
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import queries, services, statistics
from applicants.models import Application
from officers.models import OfficerProfile

from .models import NOC, AuditLog


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

    # The feed can be narrowed without leaving the dashboard. Unknown values
    # are discarded rather than passed to the query.
    entity_filter = request.GET.get('entity', '')
    if entity_filter not in dict(AuditLog.ENTITY_CHOICES):
        entity_filter = ''
    action_filter = request.GET.get('action', '')
    if action_filter not in dict(AuditLog.ACTION_CHOICES):
        action_filter = ''

    context = {
        'counts': statistics.headline_counts(),
        'status_breakdown': breakdown,
        'status_is_precomputed': precomputed,
        'last_refreshed_at': statistics.last_refreshed_at(),
        'deficiencies': statistics.deficiency_summary(),
        'officers': statistics.officer_workload(),
        'oldest_waiting': statistics.oldest_waiting(),
        'activity': statistics.recent_activity(
            entity_type=entity_filter, action=action_filter),
        'activity_counts': statistics.activity_counts(),
        'activity_filters': {
            'entity_types': AuditLog.ENTITY_CHOICES,
            'selected_entity': entity_filter,
            'actions': AuditLog.ACTION_CHOICES,
            'selected_action': action_filter,
        },
    }
    return render(request, 'adminpanel/dashboard.html', context)


@admin_required
def refresh_statistics(request):
    """Refresh the materialized view behind the status breakdown."""
    if request.method != 'POST':
        return redirect('adminpanel:dashboard')

    try:
        call_command('refreshviews', verbosity=0, actor_id=request.user.pk)
    except CommandError as exc:
        messages.error(request, f'Statistics could not be refreshed: {exc}')
        return redirect('adminpanel:dashboard')

    # refreshviews writes the audit entry, with the actor passed through, so
    # one refresh produces exactly one record however it was triggered.
    messages.success(request, 'Statistics refreshed.')
    return redirect('adminpanel:dashboard')


@admin_required
def applicant_list(request):
    """
    Registered applicants, searchable and paged.

    Paging is explicit rather than a bare queryset slice so the page survives
    a department with thousands of registrations, and so the figures shown
    ("showing 1-20 of 413") are honest.
    """
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    sort = request.GET.get('sort', queries.DEFAULT_APPLICANT_SORT)
    if sort not in queries.APPLICANT_SORTS:
        sort = queries.DEFAULT_APPLICANT_SORT

    results = queries.applicants(search=search, status=status, sort=sort)
    page = Paginator(results, 20).get_page(request.GET.get('page'))

    context = {
        'page': page,
        'search': search,
        'status': status,
        'sort': sort,
        'sort_options': queries.APPLICANT_SORTS,
        'total': page.paginator.count,
        # Carried into the paging links so a filtered list stays filtered.
        'querystring': urlencode(
            {k: v for k, v in (('q', search), ('status', status), ('sort', sort)) if v}),
    }
    return render(request, 'adminpanel/applicant_list.html', context)


@admin_required
def applicant_detail(request, user_id):
    """
    One applicant: their contact record, every application they have filed,
    and the audit entries concerning them.
    """
    applicant = get_object_or_404(
        User.objects.select_related('applicant_profile'), pk=user_id)

    if hasattr(applicant, 'officer_profile') or applicant.is_staff:
        messages.error(
            request, 'That account is not an applicant.')
        return redirect('adminpanel:applicant_list')

    applications = queries.applicant_applications(applicant)

    context = {
        'applicant': applicant,
        'profile': getattr(applicant, 'applicant_profile', None),
        'applications': applications,
        'activity': queries.applicant_activity(applicant),
        'summary': {
            'total': len(applications),
            'open_deficiencies': sum(
                a['open_deficiency_count'] or 0 for a in applications),
            'issued': sum(1 for a in applications if a['status'] == 'NOC_ISSUED'),
            'in_progress': sum(
                1 for a in applications
                if a['status'] not in ('NOC_ISSUED', 'REJECTED')),
        },
    }
    return render(request, 'adminpanel/applicant_detail.html', context)


@admin_required
def officer_list(request):
    """Fire officers, with the workload each is carrying."""
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    sort = request.GET.get('sort', queries.DEFAULT_OFFICER_SORT)
    if sort not in queries.OFFICER_SORTS:
        sort = queries.DEFAULT_OFFICER_SORT

    results = queries.officers(search=search, status=status, sort=sort)
    page = Paginator(results, 20).get_page(request.GET.get('page'))

    # One lookup for the whole page, attached to each row, rather than a
    # query per officer or a lookup the template cannot express.
    workload = queries.officer_workload_map()
    for profile in page.object_list:
        profile.workload = workload.get(profile.user_id)

    context = {
        'page': page,
        'search': search,
        'status': status,
        'sort': sort,
        'total': page.paginator.count,
        'querystring': urlencode(
            {k: v for k, v in (('q', search), ('status', status), ('sort', sort)) if v}),
    }
    return render(request, 'adminpanel/officer_list.html', context)


@admin_required
def officer_detail(request, profile_id):
    """One officer: their record, workload, inspections and recorded actions."""
    profile = get_object_or_404(
        OfficerProfile.objects.select_related('user'), pk=profile_id)

    context = {
        'profile': profile,
        'officer': profile.user,
        'workload': queries.officer_workload_map().get(profile.user_id),
        'inspections': queries.officer_inspections(profile.user),
        'activity': queries.officer_activity(profile.user),
        'outstanding': queries.officer_outstanding_work(profile.user),
        'is_active': profile.is_active and profile.user.is_active,
    }
    return render(request, 'adminpanel/officer_detail.html', context)


@admin_required
def officer_set_active(request, profile_id):
    """
    Activate or deactivate a fire officer.

    Both the profile flag and the account flag are set together. Clearing only
    OfficerProfile.is_active would leave the officer able to sign in while the
    department considers them inactive, which is the kind of half-state that
    causes incidents; clearing only the account would leave them listed as an
    active officer who can never act.

    Deactivation is permitted even when the officer has scheduled inspections,
    because an administrator may need to remove access immediately — someone
    leaving at short notice, or an account that must be locked. What the system
    owes them is not a refusal but a clear warning beforehand and a record of
    exactly what was outstanding, which the audit entry carries.
    """
    profile = get_object_or_404(
        OfficerProfile.objects.select_related('user'), pk=profile_id)

    if request.method != 'POST':
        return redirect('adminpanel:officer_detail', profile_id=profile.pk)

    action = request.POST.get('action')
    if action not in ('activate', 'deactivate'):
        messages.error(request, 'Unrecognised action.')
        return redirect('adminpanel:officer_detail', profile_id=profile.pk)

    activating = action == 'activate'
    already = (profile.is_active and profile.user.is_active) if activating else (
        not profile.is_active and not profile.user.is_active)
    if already:
        messages.info(
            request,
            f'{profile.officer_id} is already '
            f'{"active" if activating else "deactivated"}.')
        return redirect('adminpanel:officer_detail', profile_id=profile.pk)

    outstanding = queries.officer_outstanding_work(profile.user)

    with transaction.atomic():
        profile.is_active = activating
        profile.save(update_fields=['is_active', 'updated_at'])
        profile.user.is_active = activating
        profile.user.save(update_fields=['is_active'])

        AuditLog.record(
            AuditLog.ACTION_UPDATE, AuditLog.ENTITY_OFFICER,
            actor=request.user, entity=profile,
            summary=(
                f'Officer {profile.officer_id} '
                f'{"activated" if activating else "deactivated"}'
                + ('' if activating or not outstanding['scheduled_inspections']
                   else f", leaving {outstanding['scheduled_inspections']} "
                        f"scheduled inspection(s) unassigned")),
            changes={
                'is_active': {'from': not activating, 'to': activating},
                'outstanding': outstanding,
            },
            ip_address=_client_ip(request))

    if activating:
        messages.success(request, f'{profile.officer_id} has been reactivated.')
    elif outstanding['scheduled_inspections']:
        messages.warning(
            request,
            f"{profile.officer_id} has been deactivated. "
            f"{outstanding['scheduled_inspections']} scheduled inspection(s) "
            f"remain assigned to them and need reassigning.")
    else:
        messages.success(request, f'{profile.officer_id} has been deactivated.')

    return redirect('adminpanel:officer_detail', profile_id=profile.pk)


@admin_required
def noc_list(request):
    """Issued certificates, and the applications waiting for one."""
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')

    certificates = queries.issued_certificates(search=search, status=status)
    page = Paginator(certificates, 20).get_page(request.GET.get('page'))
    ready, blocked = queries.applications_awaiting_issue()

    context = {
        'page': page,
        'search': search,
        'status': status,
        'status_choices': NOC.STATUS_CHOICES,
        'total': page.paginator.count,
        'ready': ready,
        'blocked': blocked,
        'querystring': urlencode(
            {k: v for k, v in (('q', search), ('status', status)) if v}),
    }
    return render(request, 'adminpanel/noc_list.html', context)


@admin_required
def noc_issue(request, app_id):
    """Issue a certificate for an application."""
    application = get_object_or_404(Application, pk=app_id)

    if request.method != 'POST':
        return redirect('adminpanel:noc_list')

    try:
        noc = services.issue_noc(
            application,
            actor=request.user,
            remarks=request.POST.get('remarks', '').strip(),
            ip_address=_client_ip(request))
    except services.IssuanceRefused as refusal:
        for reason in refusal.reasons:
            messages.error(request, reason)
        return redirect('adminpanel:noc_list')

    messages.success(
        request,
        f'Fire NOC {noc.noc_number} issued for {application.application_id}, '
        f'valid until {noc.valid_until:%d %b %Y}.')
    return redirect('adminpanel:noc_list')


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
