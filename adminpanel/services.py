"""
Actions the admin module performs on the workflow.

Kept out of the view functions so the rules can be read, tested and reused
without going through HTTP, and so a management command can later perform the
same action without duplicating them.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

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
