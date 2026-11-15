"""
Querysets behind the admin management screens.

Kept apart from the view functions so that the question "which rows does this
screen show, and in what order" has one answer that can be read and tested on
its own.
"""

from django.contrib.auth.models import User
from django.db.models import Count, Max, Q

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
