"""
Actions the admin module performs on the workflow.

Kept out of the view functions so the rules can be read, tested and reused
without going through HTTP, and so a management command can later perform the
same action without duplicating them.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from applicants.models import Application

from officers.models import get_recommendation_eligibility

from .models import NOC, AuditLog


class IssuanceRefused(Exception):
    """
    Raised when a certificate cannot be issued.

    Carries the individual reasons rather than one string, so a caller can
    present them as a list and the person reading knows what to fix.
    """

    def __init__(self, reasons):
        self.reasons = reasons
        super().__init__('; '.join(reasons))


def issuance_blockers(application):
    """
    Everything standing between this application and a certificate.

    The technical checks — documents verified, inspection completed and
    satisfactory, no unresolved deficiencies — are delegated to
    get_recommendation_eligibility(), which the officer module already uses to
    decide whether an officer may recommend approval. Reimplementing them here
    would mean two definitions of "ready" that could disagree, and the officer
    screen and the admin screen would start contradicting each other.

    This function adds the conditions that are the admin module's own: that an
    officer actually recommended approval, and that a live certificate does not
    already exist.
    """
    reasons = list(get_recommendation_eligibility(application)['blocking_reasons'])

    review = getattr(application, 'officer_review', None)
    if review is None or review.recommendation != 'RECOMMENDED_FOR_APPROVAL':
        reasons.append(
            'No fire officer has recommended this application for approval.')

    if application.status == 'REJECTED':
        reasons.append('This application has been rejected.')

    live = NOC.objects.filter(application=application).exclude(
        status=NOC.STATUS_REVOKED).first()
    if live is not None:
        reasons.append(
            f'Certificate {live.noc_number} has already been issued for this '
            f'application.')

    return reasons


def can_issue(application):
    return not issuance_blockers(application)


@transaction.atomic
def issue_noc(application, *, actor=None, remarks='', ip_address=None):
    """
    Issue a Fire NOC for an application.

    Raises IssuanceRefused if any condition is unmet. The checks and the insert
    run in one transaction, so an application that becomes ineligible midway —
    a deficiency raised a moment ago — cannot slip through between the two.

    The certificate number is read-then-incremented, which two callers could do
    simultaneously and reach the same answer. Rather than lock the table for
    every issuance, the unique constraint catches the collision and the insert
    is retried with a fresh number. Collisions are rare; the lock would be paid
    on every issuance.
    """
    reasons = issuance_blockers(application)
    if reasons:
        raise IssuanceRefused(reasons)

    issued_at = timezone.now()
    valid_from = timezone.localdate()
    years = NOC.validity_years_for(application.occupancy_type)
    valid_until = valid_from.replace(year=valid_from.year + years)

    for attempt in range(5):
        try:
            with transaction.atomic():
                noc = NOC.objects.create(
                    application=application,
                    noc_number=NOC.next_number(issued_at.year),
                    status=NOC.STATUS_ACTIVE,
                    issued_at=issued_at,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    issued_by=actor,
                    issued_by_label=(
                        (actor.get_full_name() or actor.get_username())[:150]
                        if actor is not None else ''),
                    remarks=remarks,
                )
            break
        except IntegrityError:
            if attempt == 4:
                raise
            # Another issuance took this number between reading and writing.
            continue

    # The applicant module reads this status for the dashboard counter and the
    # certificate pages, so the application has to move with the certificate.
    application.status = 'NOC_ISSUED'
    application.save(update_fields=['status', 'updated_at'])

    AuditLog.record(
        AuditLog.ACTION_ISSUE, AuditLog.ENTITY_NOC,
        actor=actor, entity=noc,
        summary=f'Fire NOC {noc.noc_number} issued for '
                f'{application.application_id}, valid until {valid_until:%d %b %Y}',
        changes={
            'noc_number': noc.noc_number,
            'application': application.application_id,
            'valid_from': valid_from.isoformat(),
            'valid_until': valid_until.isoformat(),
        },
        ip_address=ip_address)

    return noc


# How far ahead a certificate counts as due for renewal. Chosen so that an
# applicant has time to file a renewal application and the department has time
# to inspect before the current certificate lapses.
RENEWAL_WINDOW_DAYS = 60


def expire_due_certificates(*, actor=None, today=None):
    """
    Mark certificates whose validity period has passed as expired.

    A certificate expires because the calendar moves, not because anything
    happens in the system, so nothing would ever notice without a sweep like
    this. The model can already tell you a certificate is out of date — the
    is_expired property compares dates — but the stored status is what reports,
    filters and the applicant's badge read, and a property cannot be queried
    or indexed.

    Returns the certificates it changed. Revoked certificates are left alone:
    withdrawal is a stronger statement than lapsing, and overwriting it would
    lose the reason the certificate is not valid.
    """
    today = today or timezone.localdate()

    due = list(NOC.objects.filter(
        status=NOC.STATUS_ACTIVE, valid_until__lt=today
    ).select_related('application'))

    if not due:
        return []

    with transaction.atomic():
        NOC.objects.filter(pk__in=[n.pk for n in due]).update(
            status=NOC.STATUS_EXPIRED, updated_at=timezone.now())

        for noc in due:
            noc.status = NOC.STATUS_EXPIRED
            AuditLog.record(
                AuditLog.ACTION_UPDATE, AuditLog.ENTITY_NOC,
                actor=actor, entity=noc,
                summary=f'Certificate {noc.noc_number} expired on '
                        f'{noc.valid_until:%d %b %Y}',
                changes={'status': {'from': NOC.STATUS_ACTIVE,
                                    'to': NOC.STATUS_EXPIRED},
                         'valid_until': noc.valid_until.isoformat()})

    return due


def certificates_due_for_renewal(*, within_days=RENEWAL_WINDOW_DAYS, today=None):
    """
    Certificates still valid but close enough to expiry to need renewing.

    Ordered by how soon they lapse, so the most urgent is first.
    """
    today = today or timezone.localdate()
    return (NOC.objects
            .filter(status=NOC.STATUS_ACTIVE,
                    valid_until__gte=today,
                    valid_until__lte=today + timedelta(days=within_days))
            .select_related('application')
            .order_by('valid_until'))


def has_renewal_application(noc):
    """
    Whether the applicant has already filed a renewal for this building.

    A renewal is a new application rather than a change to the certificate, so
    the link between them is the building and the applicant, not a foreign key.
    """
    return (Application.objects
            .filter(applicant=noc.application.applicant,
                    building_address=noc.application.building_address,
                    pin_code=noc.application.pin_code,
                    application_type='RENEWAL',
                    created_at__gt=noc.issued_at)
            .exclude(status='REJECTED')
            .exists())
