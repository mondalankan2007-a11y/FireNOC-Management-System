"""
Keep the normalized tables in step with applications as they are submitted.

The data migration that created PinCode, ApplicantProfile and Building
populated them from the applications that existed at the time. The applicant
module writes only the denormalized columns on Application, so without this
receiver every application submitted afterwards would leave building_id and
applicant_profile_id null and the normalized tables would drift out of date.

The receiver lives here rather than in Application.save() so that the applicant
module, which another member of the team owns, needs no further change.
"""

from decimal import Decimal, InvalidOperation

from django.db.models.signals import post_save
from django.dispatch import receiver

from applicants.models import Application

from .models import ApplicantProfile, Building, PinCode


def _clean(value):
    """Collapse surrounding whitespace; treat None as empty."""
    return ' '.join((value or '').split())


def _is_positive(value):
    """
    True when value represents a number greater than zero.

    An unsaved model instance holds whatever the caller assigned, so a numeric
    field can still be a string at the point this receiver runs; Django only
    coerces it on the way to the database. Comparing it directly would raise.
    """
    if value is None or value == '':
        return False
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def sync_normalized_records(application):
    """
    Create whatever normalized rows this application needs and link them.

    Existing rows are never overwritten. The backfill migration resolved
    conflicts by letting the newest application win, because at that point no
    authoritative record existed. One exists now, so an application fills in
    only what is still blank rather than silently rewriting a record an
    administrator may have corrected.

    An application the new constraints cannot accept — no postal code, or a
    zero floor count or built-up area, both of which Application permits and
    Building forbids — keeps a null building_id rather than being given
    invented values.
    """
    profile = _sync_applicant_profile(application)
    building = _sync_building(application)

    updates = {}
    if profile is not None and application.applicant_profile_id is None:
        updates['applicant_profile'] = profile
    if building is not None and application.building_id is None:
        updates['building'] = building

    if updates:
        # update() rather than save(), so this receiver does not re-enter.
        Application.objects.filter(pk=application.pk).update(**updates)
        for field, value in updates.items():
            setattr(application, field, value)


def _sync_applicant_profile(application):
    profile, created = ApplicantProfile.objects.get_or_create(
        user_id=application.applicant_id,
        defaults={
            'full_name': _clean(application.full_name),
            'mobile_number': _clean(application.mobile_number),
        },
    )
    if not created:
        # Fill gaps only; never replace a value that is already recorded.
        missing = {}
        if not profile.full_name and _clean(application.full_name):
            missing['full_name'] = _clean(application.full_name)
        if not profile.mobile_number and _clean(application.mobile_number):
            missing['mobile_number'] = _clean(application.mobile_number)
        if missing:
            for field, value in missing.items():
                setattr(profile, field, value)
            profile.save(update_fields=[*missing, 'updated_at'])
    return profile


def _sync_building(application):
    pin = _clean(application.pin_code)
    address = _clean(application.building_address)
    if not pin or not address:
        return None
    if not _is_positive(application.num_floors):
        return None
    if not _is_positive(application.builtup_area):
        return None

    PinCode.objects.get_or_create(
        pin_code=pin,
        defaults={
            'city': _clean(application.city),
            'state': _clean(application.state),
        },
    )

    # Match an existing building case-insensitively, as the backfill does, so
    # that a differently typed address does not create a second row.
    existing = Building.objects.filter(
        pin_code_id=pin, address__iexact=address
    ).first()
    if existing is not None:
        return existing

    building, _ = Building.objects.get_or_create(
        address=address,
        pin_code_id=pin,
        defaults={
            'name': _clean(application.building_name),
            'building_type': application.building_type,
            'building_type_other': _clean(application.building_type_other),
            'num_floors': application.num_floors,
            'builtup_area': application.builtup_area,
            'year_construction': application.year_construction,
            'occupancy_type': application.occupancy_type,
        },
    )
    return building


# Fields whose values the normalized tables are derived from. A save that
# touches none of them cannot change what those tables should hold.
SOURCE_FIELDS = frozenset({
    'applicant', 'full_name', 'mobile_number', 'building_name', 'building_type',
    'building_type_other', 'building_address', 'city', 'state', 'pin_code',
    'num_floors', 'builtup_area', 'year_construction', 'occupancy_type',
})


@receiver(post_save, sender=Application, dispatch_uid='adminpanel.sync_normalized')
def application_saved(sender, instance, update_fields=None, **kwargs):
    """
    Mirror a saved application into the normalized tables.

    This runs inside whatever transaction saved the application, so the
    normalized rows and the application commit or roll back together. Doing the
    work on transaction.on_commit instead would let an application be stored
    while its normalized rows silently failed.
    """
    if update_fields is not None and not SOURCE_FIELDS & set(update_fields):
        # e.g. Application.save() writing only application_id, or a view
        # updating only status; nothing the normalized tables derive from.
        return
    sync_normalized_records(instance)
