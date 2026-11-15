"""
Querysets behind the admin management screens.

Kept apart from the view functions so that the question "which rows does this
screen show, and in what order" has one answer that can be read and tested on
its own.
"""

from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Count, Max, Q
from django.utils import timezone

from applicants.models import Application
from officers.models import Deficiency, Inspection, OfficerProfile

from .models import NOC, AuditLog

APPLICANT_SORTS = {
    'name': 'first_name',
    'username': 'username',
    'applications': '-application_count',
    'recent': '-last_application_at',
    'joined': '-date_joined',
}
DEFAULT_APPLICANT_SORT = 'recent'


def applicants(search='', status='', sort=DEFAULT_APPLICANT_SORT):
    """
    Accounts that act as applicants, with their application activity.

    An applicant is a plain account: anyone who owns an OfficerProfile is a
    fire officer and anyone carrying is_staff is an administrator, so both are
    excluded. A user who has registered but never filed an application is
    still an applicant and still appears, which is the point of a management
    screen — the ones with nothing to show are often the interesting ones.
    """
    queryset = (User.objects
                .filter(officer_profile__isnull=True, is_staff=False)
                .annotate(
                    application_count=Count('fire_noc_applications', distinct=True),
                    last_application_at=Max('fire_noc_applications__created_at'),
                )
                .select_related('applicant_profile'))

    if search:
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(applicant_profile__mobile_number__icontains=search)
            | Q(fire_noc_applications__application_id__icontains=search)
        ).distinct()

    if status == 'active':
        queryset = queryset.filter(is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(is_active=False)
    elif status == 'with_applications':
        queryset = queryset.filter(application_count__gt=0)
    elif status == 'no_applications':
        queryset = queryset.filter(application_count=0)

    order = APPLICANT_SORTS.get(sort, APPLICANT_SORTS[DEFAULT_APPLICANT_SORT])
    # A secondary key keeps paging stable when the primary key ties, which it
    # does constantly here: most applicants have the same application count.
    return queryset.order_by(order, 'pk')


def applicant_applications(user):
    """
    Every application this person has filed, newest first.

    Read through v_application_overview rather than reassembling the same
    joins here, so the admin detail page and the dashboard agree on what "the
    latest inspection" and "open deficiencies" mean for an application.

    Falls back to the ORM where the view does not exist, on SQLite.
    """
    if connection.vendor != 'postgresql':
        return [
            {
                'reference': a.application_id,
                'status': a.status,
                'application_type': a.application_type,
                'building_name': a.building_name,
                'city': a.city,
                'created_at': a.created_at,
                'age_in_days': (timezone.now() - a.created_at).days,
                'last_inspection_date': None,
                'last_inspection_status': None,
                'last_inspection_result': None,
                'deficiency_count': a.deficiencies.count(),
                'open_deficiency_count': a.deficiencies.filter(status='OPEN').count(),
            }
            for a in user.fire_noc_applications.order_by('-created_at')
        ]

    with connection.cursor() as cursor:
        cursor.execute("""
            select reference, status, application_type, building_name, city,
                   created_at, age_in_days, last_inspection_date,
                   last_inspection_status, last_inspection_result,
                   deficiency_count, open_deficiency_count
              from v_application_overview
             where applicant_username = %s
             order by created_at desc
        """, [user.username])
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def applicant_activity(user, limit=20):
    """
    Audit entries concerning this applicant.

    Two things count as "concerning" them: entries where they were the actor,
    and entries about one of their applications. The second matters more — an
    officer rejecting their application is the kind of event an administrator
    looks for on this page, and the applicant did not perform it.
    """
    references = set(
        user.fire_noc_applications.values_list('application_id', flat=True))
    application_ids = set(
        user.fire_noc_applications.values_list('id', flat=True))

    criteria = Q(actor=user)
    if application_ids:
        criteria |= Q(entity_type=AuditLog.ENTITY_APPLICATION,
                      entity_id__in=application_ids)
    if references:
        criteria |= Q(entity_label__in=references)

    return list(AuditLog.objects.select_related('actor').filter(criteria)[:limit])


OFFICER_SORTS = {
    'officer_id': 'officer_id',
    'name': 'user__first_name',
    'designation': 'designation',
    'joined': '-created_at',
}
DEFAULT_OFFICER_SORT = 'officer_id'


def officers(search='', status='', sort=DEFAULT_OFFICER_SORT):
    """
    Fire officers, identified by owning an OfficerProfile.

    Returns profiles rather than users, because the officer identity lives on
    the profile: the officer_id, designation and badge number an administrator
    searches by are not on the account.
    """
    queryset = OfficerProfile.objects.select_related('user')

    if search:
        queryset = queryset.filter(
            Q(officer_id__icontains=search)
            | Q(designation__icontains=search)
            | Q(badge_number__icontains=search)
            | Q(phone__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search)
        )

    if status == 'active':
        queryset = queryset.filter(is_active=True, user__is_active=True)
    elif status == 'inactive':
        queryset = queryset.filter(Q(is_active=False) | Q(user__is_active=False))

    order = OFFICER_SORTS.get(sort, OFFICER_SORTS[DEFAULT_OFFICER_SORT])
    return queryset.order_by(order, 'pk')


def officer_workload_map():
    """
    Inspection and deficiency counts per officer account, keyed by user id.

    Read from v_officer_workload so this page and the dashboard agree. One
    query for the whole page rather than one per row, which is what a naive
    implementation of this table would do.
    """
    if connection.vendor != 'postgresql':
        return {}

    with connection.cursor() as cursor:
        cursor.execute("""
            select officer_user_id, inspections_total, inspections_scheduled,
                   inspections_completed, deficiencies_raised, last_inspection_date
              from v_officer_workload
        """)
        columns = [c[0] for c in cursor.description]
        return {row[0]: dict(zip(columns, row)) for row in cursor.fetchall()}


def officer_activity(user, limit=20):
    """Audit entries where this officer was the actor."""
    return list(AuditLog.objects.select_related('actor').filter(actor=user)[:limit])


def officer_inspections(user, limit=25):
    """Inspections this officer conducted, most recent first."""
    return list(
        Inspection.objects
        .filter(officer=user)
        .select_related('application')
        .order_by('-scheduled_date', '-pk')[:limit])


def officer_outstanding_work(user):
    """
    What would be left behind if this officer stopped acting now.

    Used both to warn an administrator before deactivating and to record in
    the audit entry what the state actually was at that moment, so the
    decision can be judged later on what was known at the time.
    """
    return {
        'scheduled_inspections': Inspection.objects.filter(
            officer=user, status__in=['SCHEDULED', 'IN_PROGRESS']).count(),
        'open_deficiencies': Deficiency.objects.filter(
            reported_by=user, status='OPEN').count(),
    }


def issued_certificates(search='', status=''):
    """Certificates the department has issued, newest first."""
    queryset = NOC.objects.select_related('application', 'issued_by')

    if search:
        queryset = queryset.filter(
            Q(noc_number__icontains=search)
            | Q(application__application_id__icontains=search)
            | Q(application__building_name__icontains=search)
            | Q(application__full_name__icontains=search))

    if status in dict(NOC.STATUS_CHOICES):
        queryset = queryset.filter(status=status)

    return queryset


def applications_awaiting_issue(limit=50):
    """
    Applications an officer has recommended, that have no live certificate.

    The eligibility of each is evaluated afterwards rather than in SQL,
    because the rules live in get_recommendation_eligibility() and span four
    tables. This narrows the candidates to a handful first so that evaluation
    is cheap.
    """
    from .services import issuance_blockers

    candidates = (Application.objects
                  .filter(officer_review__recommendation='RECOMMENDED_FOR_APPROVAL')
                  .exclude(status__in=['REJECTED', 'NOC_ISSUED'])
                  .select_related('officer_review')
                  .order_by('created_at')[:limit])

    ready, blocked = [], []
    for application in candidates:
        reasons = issuance_blockers(application)
        (ready if not reasons else blocked).append((application, reasons))
    return ready, blocked
