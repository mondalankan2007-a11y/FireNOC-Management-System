"""
Populate PinCode, ApplicantProfile and Building from the denormalized columns
already held on Application, then point each application at its new rows.

The denormalized columns are left untouched. See docs/database/normalization.md
section 7 for why both representations coexist.

Existing rows were written by a form that does not constrain them to agree with
one another, so the data has to be reconciled rather than simply copied. Three
rules are applied, each recorded here because each one discards information:

1.  Most recent wins. Where two applications disagree about the same postal
    code, building or applicant, the values from the newest application are
    kept, on the basis that they are the most current.
2.  Keys are matched loosely, values are stored verbatim. Addresses and postal
    codes are compared with surrounding whitespace collapsed and letter case
    ignored, so "12 MI Road" and "12  mi road" are recognised as one building.
    The stored row keeps the spelling used by the newest application.
3.  A row that cannot satisfy the new constraints is skipped, not altered.
    Application allows num_floors and builtup_area to be zero; Building does
    not. Rather than inventing a plausible value, such an application keeps its
    denormalized columns and its building_id stays null.
"""

from django.db import migrations


def _key(value):
    """Loose comparison key: collapse whitespace, ignore case."""
    return ' '.join((value or '').split()).casefold()


def backfill(apps, schema_editor):
    Application = apps.get_model('applicants', 'Application')
    PinCode = apps.get_model('adminpanel', 'PinCode')
    ApplicantProfile = apps.get_model('adminpanel', 'ApplicantProfile')
    Building = apps.get_model('adminpanel', 'Building')

    # Newest first, so the first value seen for any key is the most recent one.
    applications = list(Application.objects.order_by('-created_at', '-pk'))
    if not applications:
        return

    skipped_no_pin = []
    skipped_bad_measurements = []

    # --- 1. Postal codes -----------------------------------------------------
    pin_rows = {}
    for app in applications:
        pin = (app.pin_code or '').strip()
        if not pin or _key(pin) in pin_rows:
            continue
        pin_rows[_key(pin)] = PinCode(
            pin_code=pin,
            city=(app.city or '').strip(),
            state=(app.state or '').strip(),
        )
    PinCode.objects.bulk_create(pin_rows.values(), ignore_conflicts=True)
    stored_pins = {_key(p.pin_code): p.pin_code for p in PinCode.objects.all()}

    # --- 2. Applicant profiles ----------------------------------------------
    profiles = {}
    for app in applications:
        if app.applicant_id in profiles:
            continue
        profiles[app.applicant_id] = ApplicantProfile(
            user_id=app.applicant_id,
            full_name=(app.full_name or '').strip(),
            mobile_number=(app.mobile_number or '').strip(),
        )
    ApplicantProfile.objects.bulk_create(profiles.values(), ignore_conflicts=True)
    profile_ids = {
        p.user_id: p.pk for p in ApplicantProfile.objects.all()
    }

    # --- 3. Buildings --------------------------------------------------------
    buildings = {}
    for app in applications:
        pin = (app.pin_code or '').strip()
        if not pin:
            skipped_no_pin.append(app.pk)
            continue
        if app.num_floors <= 0 or app.builtup_area <= 0:
            skipped_bad_measurements.append(app.pk)
            continue
        key = (_key(app.building_address), _key(pin))
        if key in buildings:
            continue
        buildings[key] = Building(
            name=(app.building_name or '').strip(),
            address=(app.building_address or '').strip(),
            pin_code_id=stored_pins[_key(pin)],
            building_type=app.building_type,
            building_type_other=app.building_type_other,
            num_floors=app.num_floors,
            builtup_area=app.builtup_area,
            year_construction=app.year_construction,
            occupancy_type=app.occupancy_type,
        )
    Building.objects.bulk_create(buildings.values())
    building_ids = {
        (_key(b.address), _key(b.pin_code_id)): b.pk
        for b in Building.objects.all()
    }

    # --- 4. Link each application -------------------------------------------
    for app in applications:
        app.applicant_profile_id = profile_ids.get(app.applicant_id)
        app.building_id = building_ids.get(
            (_key(app.building_address), _key((app.pin_code or '').strip()))
        )
    Application.objects.bulk_update(
        applications, ['applicant_profile_id', 'building_id'], batch_size=500
    )

    linked = sum(1 for a in applications if a.building_id)
    print(
        f"\n  Backfill: {len(pin_rows)} pin codes, {len(profiles)} applicant "
        f"profiles, {len(buildings)} buildings from {len(applications)} "
        f"applications ({linked} linked to a building)."
    )
    if skipped_no_pin:
        print(f"  Skipped (no postal code): applications {skipped_no_pin}")
    if skipped_bad_measurements:
        print(
            "  Skipped (zero floors or zero built-up area, which Building "
            f"forbids): applications {skipped_bad_measurements}"
        )


def unbackfill(apps, schema_editor):
    """
    Undo the backfill: unlink the applications and empty the three tables.

    Removing every row is correct here rather than heavy-handed, because the
    preceding migration created these tables empty; everything in them was put
    there by this migration. The denormalized columns on Application were never
    modified, so no application data is lost.
    """
    Application = apps.get_model('applicants', 'Application')
    PinCode = apps.get_model('adminpanel', 'PinCode')
    ApplicantProfile = apps.get_model('adminpanel', 'ApplicantProfile')
    Building = apps.get_model('adminpanel', 'Building')

    Application.objects.update(applicant_profile=None, building=None)
    Building.objects.all().delete()
    ApplicantProfile.objects.all().delete()
    PinCode.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('adminpanel', '0001_initial'),
        ('applicants', '0002_normalized_references'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
