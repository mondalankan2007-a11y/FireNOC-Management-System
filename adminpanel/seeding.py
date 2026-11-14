"""
Synthetic data for database evaluation.

Shared by the dbanalyze and runqueries management commands, which both need a
realistic volume of rows to produce meaningful output and both discard it
afterwards. Nothing here is used by the running application.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection

from adminpanel.models import Building, PinCode
from applicants.models import Application
from officers.models import Deficiency, Inspection

BUILDING_TYPES = ['RESIDENTIAL', 'COMMERCIAL', 'INDUSTRIAL', 'EDUCATIONAL',
                  'HOSPITAL', 'HOTEL', 'OTHER']

SEED_USERNAME = '__sampledata__'
SEED_PREFIX = 'LOAD-'


class Rollback(Exception):
    """Raised to discard seeded rows by unwinding the surrounding atomic block."""


def seed(count):
    """
    Insert `count` applications with inspections and deficiencies hanging off
    them, and return a summary of what was created.

    bulk_create is used throughout: it bypasses Model.save(), which keeps the
    normalized-record receiver out of the way and makes seeding fast. That also
    means application_id must be set explicitly, since the column is unique and
    save() is what would normally populate it.
    """
    user, _ = User.objects.get_or_create(
        username=SEED_USERNAME,
        defaults={'email': 'sampledata@example.invalid'})

    statuses = [c[0] for c in Application.STATUS_CHOICES]
    existing = Application.objects.count()

    Application.objects.bulk_create([
        Application(
            applicant=user,
            full_name='Load Test Applicant',
            email='load@example.invalid',
            mobile_number='9000000000',
            building_name=f'Building {i % max(count // 4, 1)}',
            building_type=BUILDING_TYPES[i % len(BUILDING_TYPES)],
            # Addresses repeat, so several applications share one building and
            # the normalized Building table has something to de-duplicate.
            building_address=f'{i % max(count // 4, 1)} Synthetic Road',
            city='Jaipur',
            state='Rajasthan',
            pin_code=f'3020{i % 100:02d}',
            num_floors=(i % 20) + 1,
            builtup_area=Decimal(1000 + (i % 50) * 100),
            year_construction=2000 + (i % 25),
            occupancy_type='BUSINESS',
            application_id=f'{SEED_PREFIX}{existing + i:07d}',
            application_type='RENEWAL' if i % 4 == 0 else 'NEW_NOC',
            purpose='Synthetic row for database evaluation',
            # NOC_ISSUED is deliberately rare (~1%), so the effect of
            # selectivity on index choice can be measured.
            status='NOC_ISSUED' if i % 97 == 0 else statuses[i % (len(statuses) - 1)],
        )
        for i in range(count)
    ], batch_size=1000)

    seeded = list(Application.objects.filter(
        application_id__startswith=SEED_PREFIX).values_list('id', flat=True))

    inspection_statuses = ['SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED']
    Inspection.objects.bulk_create([
        Inspection(
            application_id=app_id,
            scheduled_date=date(2026, 1, 1) + timedelta(days=i % 365),
            scheduled_time='10:00',
            status=inspection_statuses[i % 4],
        )
        for i, app_id in enumerate(seeded[::2])
    ], batch_size=1000)

    inspections = list(Inspection.objects.values_list('id', 'application_id'))
    deficiency_statuses = ['OPEN', 'SUBMITTED_FOR_VERIFICATION', 'VERIFIED',
                           'REJECTED', 'CLOSED']
    Deficiency.objects.bulk_create([
        Deficiency(
            application_id=app_id,
            inspection_id=insp_id,
            title=f'Synthetic deficiency {i}',
            description='Synthetic row for database evaluation',
            severity=['MINOR', 'MAJOR', 'CRITICAL'][i % 3],
            status=deficiency_statuses[i % 5],
        )
        for i, (insp_id, app_id) in enumerate(inspections[::2])
    ], batch_size=1000)

    _spread_submission_dates()
    _link_normalized_records()

    return {
        'applications': Application.objects.count(),
        'inspections': Inspection.objects.count(),
        'deficiencies': Deficiency.objects.count(),
    }


def _spread_submission_dates():
    """
    Spread created_at over the last year.

    auto_now_add stamps every bulk-created row with the current moment, which
    makes any query grouping by month or measuring age return a single bucket.
    A direct UPDATE bypasses auto_now_add.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE applicants_application
               SET created_at = NOW() - ((id %% 365) * INTERVAL '1 day')
             WHERE application_id LIKE %s
        """, [f'{SEED_PREFIX}%'])


def _link_normalized_records():
    """Create PinCode and Building rows for the seeded applications and link them."""
    seeded = Application.objects.filter(application_id__startswith=SEED_PREFIX)

    PinCode.objects.bulk_create(
        [PinCode(pin_code=pin, city='Jaipur', state='Rajasthan')
         for pin in sorted(set(seeded.values_list('pin_code', flat=True)))],
        ignore_conflicts=True)

    seen, buildings = set(), []
    for app in seeded.order_by('id'):
        key = (app.building_address, app.pin_code)
        if key in seen:
            continue
        seen.add(key)
        buildings.append(Building(
            name=app.building_name, address=app.building_address,
            pin_code_id=app.pin_code, building_type=app.building_type,
            num_floors=app.num_floors, builtup_area=app.builtup_area,
            year_construction=app.year_construction,
            occupancy_type=app.occupancy_type))
    Building.objects.bulk_create(buildings, ignore_conflicts=True)

    lookup = {(b.address, b.pin_code_id): b.pk for b in Building.objects.all()}
    to_update = []
    for app in seeded.order_by('id'):
        app.building_id = lookup.get((app.building_address, app.pin_code))
        to_update.append(app)
    Application.objects.bulk_update(to_update, ['building'], batch_size=1000)
