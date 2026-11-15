from datetime import date, time, timedelta
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from officers.models import Deficiency, Inspection, OfficerProfile

from applicants.models import Application

from . import queries
from .models import ApplicantProfile, AuditLog, Building, PinCode
from .signals import _sync_building


def make_application(user, **overrides):
    """An application with valid defaults, overridable per test."""
    values = dict(
        applicant=user,
        full_name='Harsh Kothari',
        email='harsh@example.com',
        mobile_number='9876543210',
        building_name='Sunrise Tower',
        building_type='COMMERCIAL',
        building_address='12 MI Road',
        city='Jaipur',
        state='Rajasthan',
        pin_code='302001',
        num_floors=8,
        builtup_area=Decimal('2500.50'),
        year_construction=2015,
        occupancy_type='BUSINESS',
        application_type='NEW_NOC',
        purpose='Fire safety clearance',
    )
    values.update(overrides)
    return Application.objects.create(**values)


class NormalizedRecordSyncTests(TestCase):
    """
    A submitted application must populate and link the normalized tables,
    so they do not drift out of date after the backfill migration.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant1', 'a1@example.com', 'pw')

    def test_new_application_creates_and_links_all_three_records(self):
        application = make_application(self.user)

        self.assertEqual(PinCode.objects.count(), 1)
        self.assertEqual(ApplicantProfile.objects.count(), 1)
        self.assertEqual(Building.objects.count(), 1)

        application.refresh_from_db()
        self.assertIsNotNone(application.building_id)
        self.assertIsNotNone(application.applicant_profile_id)
        self.assertEqual(application.building.name, 'Sunrise Tower')
        self.assertEqual(application.applicant_profile.mobile_number, '9876543210')

    def test_pin_code_carries_city_and_state(self):
        make_application(self.user)

        pin = PinCode.objects.get(pk='302001')
        self.assertEqual(pin.city, 'Jaipur')
        self.assertEqual(pin.state, 'Rajasthan')

    def test_renewal_reuses_the_same_building(self):
        first = make_application(self.user)
        renewal = make_application(self.user, application_type='RENEWAL')

        self.assertEqual(Building.objects.count(), 1)
        first.refresh_from_db()
        renewal.refresh_from_db()
        self.assertEqual(first.building_id, renewal.building_id)

    def test_address_differing_only_in_spacing_and_case_reuses_the_building(self):
        first = make_application(self.user)
        second = make_application(self.user, building_address='12  mi   ROAD')

        self.assertEqual(Building.objects.count(), 1)
        second.refresh_from_db()
        self.assertEqual(second.building_id, first.building_id)

    def test_different_address_creates_a_second_building(self):
        make_application(self.user)
        make_application(self.user, building_address='77 Station Road')

        self.assertEqual(Building.objects.count(), 2)
        self.assertEqual(PinCode.objects.count(), 1)

    def test_one_profile_per_applicant_across_applications(self):
        make_application(self.user)
        make_application(self.user, building_address='77 Station Road')

        self.assertEqual(ApplicantProfile.objects.count(), 1)

    def test_existing_profile_is_not_overwritten(self):
        make_application(self.user)
        profile = ApplicantProfile.objects.get(user=self.user)
        profile.full_name = 'Corrected By Administrator'
        profile.save()

        make_application(self.user, full_name='Typed Again Wrongly',
                         building_address='77 Station Road')

        profile.refresh_from_db()
        self.assertEqual(profile.full_name, 'Corrected By Administrator')

    def test_blank_profile_field_is_filled_in_later(self):
        make_application(self.user, mobile_number='')
        profile = ApplicantProfile.objects.get(user=self.user)
        self.assertEqual(profile.mobile_number, '')

        make_application(self.user, mobile_number='9123456780',
                         building_address='77 Station Road')

        profile.refresh_from_db()
        self.assertEqual(profile.mobile_number, '9123456780')

    def test_existing_building_is_not_overwritten(self):
        make_application(self.user)
        building = Building.objects.get()
        building.name = 'Corrected Tower Name'
        building.save()

        make_application(self.user, building_name='Different Name Typed')

        building.refresh_from_db()
        self.assertEqual(building.name, 'Corrected Tower Name')
        self.assertEqual(Building.objects.count(), 1)


class UnusableApplicationTests(TestCase):
    """
    The building guard in the sync receiver.

    Zero floors and zero built-up area can no longer reach the database:
    application_num_floors_range and application_builtup_area_positive reject
    them at insert time. The guard remains as a backstop for rows arriving by
    other routes — a data migration, a bulk load, a SQL client — so it is
    exercised directly against unsaved instances rather than through a save
    the database would refuse.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant2', 'a2@example.com', 'pw')

    def _unsaved(self, **overrides):
        values = dict(
            applicant=self.user, full_name='X', email='x@example.com',
            mobile_number='1', building_name='B', building_type='COMMERCIAL',
            building_address='12 MI Road', city='Jaipur', state='Rajasthan',
            pin_code='302001', num_floors=8, builtup_area=Decimal('100'),
            year_construction=2015, occupancy_type='BUSINESS',
            application_type='NEW_NOC', purpose='p')
        values.update(overrides)
        return Application(**values)

    def test_guard_rejects_zero_floors(self):
        self.assertIsNone(_sync_building(self._unsaved(num_floors=0)))
        self.assertEqual(Building.objects.count(), 0)

    def test_guard_rejects_zero_builtup_area(self):
        self.assertIsNone(_sync_building(self._unsaved(builtup_area=Decimal('0'))))
        self.assertEqual(Building.objects.count(), 0)

    def test_guard_rejects_blank_pin_code(self):
        self.assertIsNone(_sync_building(self._unsaved(pin_code='')))
        self.assertEqual(PinCode.objects.count(), 0)

    def test_guard_accepts_a_usable_application(self):
        building = _sync_building(self._unsaved())
        self.assertIsNotNone(building)
        self.assertEqual(building.num_floors, 8)

    def test_blank_pin_code_leaves_the_building_unlinked(self):
        application = make_application(self.user, pin_code='')

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 0)
        self.assertEqual(PinCode.objects.count(), 0)
        self.assertIsNone(application.building_id)
        self.assertIsNotNone(application.applicant_profile_id)


class SyncSideEffectTests(TestCase):
    """The receiver must not disturb the applicant module's own behaviour."""

    def setUp(self):
        self.user = User.objects.create_user('applicant3', 'a3@example.com', 'pw')

    def test_application_id_is_still_generated(self):
        application = make_application(self.user)

        application.refresh_from_db()
        self.assertRegex(application.application_id, r'^NOC-\d{4}-\d{4}$')

    def test_status_only_update_does_not_create_records(self):
        application = make_application(self.user)
        before = Building.objects.count()

        application.status = 'UNDER_REVIEW'
        application.save(update_fields=['status', 'updated_at'])

        self.assertEqual(Building.objects.count(), before)
        application.refresh_from_db()
        self.assertEqual(application.status, 'UNDER_REVIEW')

    def test_numeric_fields_given_as_strings_are_handled(self):
        """
        An unsaved instance holds whatever the caller assigned, so a numeric
        field can still be a string when the receiver runs. Several existing
        tests in the applicant and officer modules create applications this
        way, and comparing a string to zero raises TypeError.
        """
        application = make_application(
            self.user, num_floors='8', builtup_area='2500.50')

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 1)
        self.assertIsNotNone(application.building_id)

    def test_numeric_strings_that_are_zero_are_still_rejected(self):
        unsaved = Application(
            applicant=self.user, full_name='X', email='x@example.com',
            mobile_number='1', building_name='B', building_type='COMMERCIAL',
            building_address='9 Zero Lane', city='Jaipur', state='Rajasthan',
            pin_code='302001', num_floors='0', builtup_area='0.00',
            year_construction=2015, occupancy_type='BUSINESS',
            application_type='NEW_NOC', purpose='p')

        self.assertIsNone(_sync_building(unsaved))
        self.assertEqual(Building.objects.count(), 0)

    def test_denormalized_columns_are_left_untouched(self):
        application = make_application(self.user)

        application.refresh_from_db()
        self.assertEqual(application.building_address, '12 MI Road')
        self.assertEqual(application.city, 'Jaipur')
        self.assertEqual(application.full_name, 'Harsh Kothari')


class AuditLogRecordingTests(TestCase):
    """AuditLog.record is the single entry point later work will call."""

    def setUp(self):
        self.officer = User.objects.create_user(
            'officer1', 'o1@example.com', 'pw',
            first_name='Aditya', last_name='Shekhawat')
        self.applicant = User.objects.create_user('applicant9', 'a9@example.com', 'pw')

    def test_records_actor_action_and_entity(self):
        entry = AuditLog.record(
            AuditLog.ACTION_APPROVE, AuditLog.ENTITY_APPLICATION,
            actor=self.officer, entity_id=42, entity_label='NOC-2026-0042',
            summary='Application approved after inspection')

        self.assertEqual(entry.actor, self.officer)
        self.assertEqual(entry.action, 'APPROVE')
        self.assertEqual(entry.entity_type, 'APPLICATION')
        self.assertEqual(entry.entity_id, 42)
        self.assertEqual(entry.summary, 'Application approved after inspection')

    def test_actor_label_uses_the_full_name(self):
        entry = AuditLog.record(
            AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=self.officer)

        self.assertEqual(entry.actor_label, 'Aditya Shekhawat')

    def test_actor_label_falls_back_to_the_username(self):
        entry = AuditLog.record(
            AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=self.applicant)

        self.assertEqual(entry.actor_label, 'applicant9')

    def test_automated_action_has_no_actor(self):
        entry = AuditLog.record(
            AuditLog.ACTION_STATUS_CHANGE, AuditLog.ENTITY_APPLICATION,
            entity_id=7, summary='Escalated by the monitoring command')

        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, '')

    def test_passing_an_entity_fills_id_and_label(self):
        application = make_application(self.applicant)

        entry = AuditLog.record(
            AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
            actor=self.applicant, entity=application, summary='Application submitted')

        self.assertEqual(entry.entity_id, application.pk)
        self.assertIn(application.application_id, entry.entity_label)

    def test_changes_round_trip_as_structured_data(self):
        entry = AuditLog.record(
            AuditLog.ACTION_STATUS_CHANGE, AuditLog.ENTITY_APPLICATION,
            entity_id=3,
            changes={'status': {'from': 'PENDING', 'to': 'UNDER_REVIEW'}})

        entry.refresh_from_db()
        self.assertEqual(entry.changes['status']['to'], 'UNDER_REVIEW')

    def test_overlong_label_and_summary_are_truncated_not_rejected(self):
        entry = AuditLog.record(
            AuditLog.ACTION_UPDATE, AuditLog.ENTITY_BUILDING,
            entity_id=1, entity_label='B' * 400, summary='S' * 400)

        self.assertEqual(len(entry.entity_label), 150)
        self.assertEqual(len(entry.summary), 255)

    def test_newest_entry_comes_first(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='first')
        AuditLog.record(AuditLog.ACTION_APPROVE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='second')

        self.assertEqual(AuditLog.objects.first().summary, 'second')


class AuditLogDurabilityTests(TestCase):
    """
    An audit entry is evidence: it must outlive both its subject and its
    actor, and it must not be editable after the fact.
    """

    def setUp(self):
        self.officer = User.objects.create_user(
            'officer2', 'o2@example.com', 'pw', first_name='Fire', last_name='Officer')

    def test_entry_cannot_be_modified(self):
        entry = AuditLog.record(
            AuditLog.ACTION_APPROVE, AuditLog.ENTITY_APPLICATION,
            actor=self.officer, entity_id=5, summary='Approved')

        entry.summary = 'Rewritten after the fact'
        with self.assertRaises(ValueError):
            entry.save()

        entry.refresh_from_db()
        self.assertEqual(entry.summary, 'Approved')

    def test_entry_survives_deletion_of_its_actor(self):
        AuditLog.record(AuditLog.ACTION_APPROVE, AuditLog.ENTITY_APPLICATION,
                        actor=self.officer, entity_id=5, summary='Approved')

        self.officer.delete()

        entry = AuditLog.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, 'Fire Officer')

    def test_entry_survives_deletion_of_its_subject(self):
        applicant = User.objects.create_user('applicant10', 'a10@example.com', 'pw')
        application = make_application(applicant)
        label = application.application_id

        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity=application, summary='Submitted')
        application.delete()

        entry = AuditLog.objects.get()
        self.assertIn(label, entry.entity_label)
        self.assertEqual(Application.objects.count(), 0)

    def test_database_rejects_a_zero_entity_id(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditLog.objects.create(
                    action=AuditLog.ACTION_UPDATE,
                    entity_type=AuditLog.ENTITY_APPLICATION,
                    entity_id=0, summary='Invalid subject')

    def test_null_entity_id_is_allowed_for_system_events(self):
        entry = AuditLog.record(
            AuditLog.ACTION_LOGIN, AuditLog.ENTITY_SYSTEM, actor=self.officer)

        self.assertIsNone(entry.entity_id)


class ConstraintIntegrityTests(TestCase):
    """
    The CHECK constraints added to the original eleven tables.

    Each one mirrors a rule the application layer already applies. These tests
    assert the database applies it too, by writing values that bypass Django's
    own validation the way a data migration or a SQL client would.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant11', 'a11@example.com', 'pw')

    def _create(self, **overrides):
        with transaction.atomic():
            return make_application(self.user, **overrides)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(status='NOT_A_REAL_STATUS')

    def test_invalid_building_type_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(building_type='CASTLE')

    def test_invalid_occupancy_type_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(occupancy_type='NOWHERE')

    def test_invalid_application_type_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(application_type='TRANSFER')

    def test_zero_floors_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(num_floors=0)

    def test_more_than_two_hundred_floors_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(num_floors=201)

    def test_zero_builtup_area_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(builtup_area=Decimal('0'))

    def test_implausible_construction_year_is_rejected(self):
        with self.assertRaises(IntegrityError):
            self._create(year_construction=1200)

    def test_valid_boundary_values_are_accepted(self):
        application = self._create(num_floors=200, year_construction=1800,
                                   builtup_area=Decimal('0.01'))
        self.assertEqual(application.num_floors, 200)


class ConstraintDriftTests(TestCase):
    """
    The CHECK constraints list their allowed values literally, so that the
    teammates' model files need no restructuring. That duplication is only
    safe while it stays in step with the model's own choices, which is what
    this test enforces: add a status to a model and forget the constraint,
    and this fails.
    """

    CASES = [
        ('applicants', 'Application', 'status', 'application_status_valid'),
        ('applicants', 'Application', 'application_type', 'application_type_valid'),
        ('applicants', 'Application', 'building_type', 'application_building_type_valid'),
        ('applicants', 'Application', 'occupancy_type', 'application_occupancy_type_valid'),
        ('applicants', 'ApplicationDocument', 'document_type', 'document_type_valid'),
        ('officers', 'DocumentVerification', 'status', 'docverification_status_valid'),
        ('officers', 'ApplicationReview', 'status', 'review_status_valid'),
        ('officers', 'ApplicationReview', 'recommendation', 'review_recommendation_valid'),
        ('officers', 'Inspection', 'status', 'inspection_status_valid'),
        ('officers', 'InspectionChecklistItem', 'status', 'checklistitem_status_valid'),
        ('officers', 'InspectionReport', 'overall_result', 'inspectionreport_result_valid'),
        ('officers', 'Deficiency', 'severity', 'deficiency_severity_valid'),
        ('officers', 'Deficiency', 'status', 'deficiency_status_valid'),
        ('officers', 'DeficiencyRectification', 'status', 'rectification_status_valid'),
    ]

    def test_every_constraint_matches_its_field_choices(self):
        from django.apps import apps as registry

        for app_label, model_name, field_name, constraint_name in self.CASES:
            with self.subTest(constraint=constraint_name):
                model = registry.get_model(app_label, model_name)
                field_values = {c[0] for c in model._meta.get_field(field_name).choices}

                constraint = next(
                    (c for c in model._meta.constraints if c.name == constraint_name),
                    None)
                self.assertIsNotNone(
                    constraint, f'{constraint_name} is missing from {model_name}.Meta')

                condition = constraint.condition if getattr(constraint, 'condition', None) is not None else getattr(constraint, 'check', None)
                lookup, allowed = condition.children[0]
                self.assertTrue(lookup.endswith('__in'), lookup)
                self.assertEqual(
                    set(allowed), field_values,
                    f'{constraint_name} does not match {model_name}.{field_name} choices')


@skipUnless(connection.vendor == 'postgresql',
            'The composite foreign key is only created on PostgreSQL')
class DeficiencyApplicationConsistencyTests(TestCase):
    """
    officers_deficiency stores application_id even though it is derivable
    through inspection_id. The composite foreign key makes that redundancy
    safe: the database rejects a deficiency whose application disagrees with
    its inspection's application.

    The constraint is DEFERRABLE INITIALLY DEFERRED, so it is checked when the
    transaction commits rather than at insert. These tests force the check
    with SET CONSTRAINTS ALL IMMEDIATE, because Django's TestCase rolls its
    transaction back and would otherwise never reach a commit.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant12', 'a12@example.com', 'pw')
        self.application_a = make_application(self.user)
        self.application_b = make_application(
            self.user, building_address='77 Station Road')
        self.inspection = Inspection.objects.create(
            application=self.application_a,
            scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0),
            status='SCHEDULED')

    def _force_constraint_check(self):
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def test_matching_application_is_accepted(self):
        Deficiency.objects.create(
            application=self.application_a, inspection=self.inspection,
            title='Blocked fire exit', description='Rear exit obstructed',
            severity='MAJOR', status='OPEN')

        self._force_constraint_check()
        self.assertEqual(Deficiency.objects.count(), 1)

    def test_mismatched_application_is_rejected_by_the_database(self):
        Deficiency.objects.create(
            application=self.application_b,   # belongs to a different application
            inspection=self.inspection,
            title='Wrong application', description='Should not be storable',
            severity='MINOR', status='OPEN')

        with self.assertRaises(IntegrityError):
            self._force_constraint_check()


@skipUnless(connection.vendor == 'postgresql',
            'The reporting views are only created on PostgreSQL')
class ReportingViewTests(TestCase):
    """
    The views created by adminpanel/migrations/0004_reporting_views.

    Each is queried through raw SQL, which is how the reporting layer reads
    them, so a view whose definition stops matching the schema fails here.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant13', 'a13@example.com', 'pw')
        self.application = make_application(self.user)

    def _rows(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def test_application_overview_exposes_one_row_per_application(self):
        rows = self._rows('select reference, status, open_deficiency_count, '
                          'age_in_days from v_application_overview')

        self.assertEqual(len(rows), 1)
        reference, status, open_deficiencies, age = rows[0]
        self.assertEqual(reference, self.application.application_id)
        self.assertEqual(status, 'PENDING')
        self.assertEqual(open_deficiencies, 0)
        self.assertEqual(age, 0)

    def test_application_overview_counts_open_deficiencies(self):
        inspection = Inspection.objects.create(
            application=self.application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='COMPLETED')
        Deficiency.objects.create(
            application=self.application, inspection=inspection,
            title='Blocked exit', description='Rear exit obstructed',
            severity='MAJOR', status='OPEN')

        rows = self._rows('select deficiency_count, open_deficiency_count, '
                          'last_inspection_status from v_application_overview')
        self.assertEqual(rows[0], (1, 1, 'COMPLETED'))

    def test_officer_workload_lists_officers_with_a_profile(self):
        officer = User.objects.create_user('officer9', 'o9@example.com', 'pw')
        OfficerProfile.objects.create(
            user=officer, officer_id='FO-909', designation='Inspector')

        rows = self._rows('select username, officer_reference, inspections_total '
                          'from v_officer_workload')
        self.assertEqual(rows, [('officer9', 'FO-909', 0)])

    def test_deficiency_summary_groups_by_severity_and_status(self):
        inspection = Inspection.objects.create(
            application=self.application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='COMPLETED')
        for severity in ('MINOR', 'MAJOR'):
            Deficiency.objects.create(
                application=self.application, inspection=inspection,
                title=f'{severity} issue', description='x',
                severity=severity, status='OPEN')

        rows = self._rows('select severity, status, deficiencies '
                          'from v_deficiency_summary order by severity')
        self.assertEqual(rows, [('MAJOR', 'OPEN', 1), ('MINOR', 'OPEN', 1)])

    def test_department_statistics_is_materialized_and_needs_refreshing(self):
        # A materialized view holds the result of its last refresh, so the
        # application created in setUp is not visible until one happens.
        self.assertEqual(
            self._rows('select count(*) from mv_department_statistics')[0][0], 0)

        call_command('refreshviews', '--blocking', verbosity=0)

        rows = self._rows('select status, applications from mv_department_statistics')
        self.assertEqual(rows, [('PENDING', 1)])


@skipUnless(connection.vendor == 'postgresql',
            'The audit triggers are only created on PostgreSQL')
class AuditTriggerTests(TestCase):
    """
    The triggers created by adminpanel/migrations/0005_audit_triggers.

    Every test here changes a status with queryset.update(), which issues SQL
    directly and never calls Model.save(). That is the case the triggers exist
    for: a change the application layer would not have recorded.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant14', 'a14@example.com', 'pw')
        self.application = make_application(self.user)
        AuditLog.objects.all().delete()

    def test_application_status_change_is_recorded(self):
        Application.objects.filter(pk=self.application.pk).update(status='UNDER_REVIEW')

        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, 'STATUS_CHANGE')
        self.assertEqual(entry.entity_type, 'APPLICATION')
        self.assertEqual(entry.entity_id, self.application.pk)
        self.assertEqual(entry.entity_label, self.application.application_id)
        self.assertEqual(entry.changes,
                         {'status': {'from': 'PENDING', 'to': 'UNDER_REVIEW'}})

    def test_trigger_entries_have_no_actor(self):
        Application.objects.filter(pk=self.application.pk).update(status='APPROVED')

        entry = AuditLog.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_label, 'database trigger')

    def test_update_that_does_not_change_status_records_nothing(self):
        Application.objects.filter(pk=self.application.pk).update(remarks='edited')

        self.assertEqual(AuditLog.objects.count(), 0)

    def test_writing_the_same_status_again_records_nothing(self):
        Application.objects.filter(pk=self.application.pk).update(status='PENDING')

        self.assertEqual(AuditLog.objects.count(), 0)

    def test_inspection_status_change_is_recorded(self):
        inspection = Inspection.objects.create(
            application=self.application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='SCHEDULED')
        AuditLog.objects.all().delete()

        Inspection.objects.filter(pk=inspection.pk).update(status='COMPLETED')

        entry = AuditLog.objects.get()
        self.assertEqual(entry.entity_type, 'INSPECTION')
        self.assertEqual(entry.entity_id, inspection.pk)

    def test_deficiency_status_change_is_recorded_with_its_title(self):
        inspection = Inspection.objects.create(
            application=self.application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='COMPLETED')
        deficiency = Deficiency.objects.create(
            application=self.application, inspection=inspection,
            title='Blocked fire exit', description='x',
            severity='MAJOR', status='OPEN')
        AuditLog.objects.all().delete()

        Deficiency.objects.filter(pk=deficiency.pk).update(status='CLOSED')

        entry = AuditLog.objects.get()
        self.assertEqual(entry.entity_type, 'DEFICIENCY')
        self.assertEqual(entry.entity_label, 'Blocked fire exit')

    def test_several_rows_updated_at_once_are_each_recorded(self):
        second = make_application(self.user, building_address='77 Station Road')
        AuditLog.objects.all().delete()

        Application.objects.filter(
            pk__in=[self.application.pk, second.pk]).update(status='REJECTED')

        self.assertEqual(AuditLog.objects.count(), 2)


class AdminAccessControlTests(TestCase):
    """
    Who may reach the admin portal.

    An applicant is a plain account, an officer owns an OfficerProfile, and an
    administrator carries is_staff. These tests pin that separation down,
    including the case of an account that is somehow both.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin', 'admin@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user(
            'applicant15', 'a15@example.com', 'pw')
        self.officer = User.objects.create_user('officer10', 'o10@example.com', 'pw')
        OfficerProfile.objects.create(
            user=self.officer, officer_id='FO-010', designation='Inspector')
        self.home = reverse('adminpanel:admin_home')
        self.login_url = reverse('adminpanel:login')

    def test_anonymous_visitor_is_sent_to_sign_in_with_next(self):
        response = self.client.get(self.home)

        self.assertRedirects(response, f'{self.login_url}?next={self.home}')

    def test_administrator_reaches_the_portal(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.home)
        self.assertEqual(response.status_code, 200)

    def test_applicant_is_refused(self):
        self.client.force_login(self.applicant)

        response = self.client.get(self.home)
        self.assertRedirects(response, reverse('home'))

    def test_officer_is_refused(self):
        self.client.force_login(self.officer)

        response = self.client.get(self.home)
        self.assertRedirects(response, reverse('home'))

    def test_officer_who_is_also_staff_is_still_refused(self):
        # An account that is both is treated as the narrower role, so that
        # granting staff to an officer does not quietly confer admin rights.
        self.officer.is_staff = True
        self.officer.save(update_fields=['is_staff'])
        self.client.force_login(self.officer)

        response = self.client.get(self.home)
        self.assertRedirects(response, reverse('home'))

    def test_deactivated_administrator_is_refused(self):
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        self.client.force_login(self.admin)

        response = self.client.get(self.home)
        self.assertEqual(response.status_code, 302)


class AdminSignInTests(TestCase):
    """The sign-in form itself, and what it records."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin2', 'admin2@example.com', 'correct-horse', is_staff=True)
        self.login_url = reverse('adminpanel:login')
        AuditLog.objects.all().delete()

    def test_valid_credentials_sign_in_and_redirect(self):
        response = self.client.post(
            self.login_url,
            {'username': 'deptadmin2', 'password': 'correct-horse'})

        self.assertRedirects(response, reverse('adminpanel:admin_home'))
        self.assertEqual(response.wsgi_request.user, self.admin)

    def test_next_is_honoured_after_sign_in(self):
        response = self.client.post(
            self.login_url,
            {'username': 'deptadmin2', 'password': 'correct-horse',
             'next': '/admin-panel/'})

        self.assertRedirects(response, '/admin-panel/')

    def test_wrong_password_is_rejected_and_audited(self):
        response = self.client.post(
            self.login_url, {'username': 'deptadmin2', 'password': 'wrong'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        entry = AuditLog.objects.get()
        self.assertIn('Failed admin sign-in', entry.summary)
        self.assertIsNone(entry.actor)

    def test_failure_message_does_not_reveal_whether_the_account_exists(self):
        for username in ('deptadmin2', 'no-such-account'):
            response = self.client.post(
                self.login_url, {'username': username, 'password': 'wrong'})
            self.assertContains(response, 'Invalid username or password.')

    def test_non_admin_with_valid_credentials_is_refused_and_audited(self):
        User.objects.create_user('plainuser', 'p@example.com', 'letmein')

        response = self.client.post(
            self.login_url, {'username': 'plainuser', 'password': 'letmein'})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        entry = AuditLog.objects.get()
        self.assertIn('not an administrator', entry.summary)
        self.assertIsNotNone(entry.actor)

    def test_successful_sign_in_is_audited(self):
        self.client.post(self.login_url,
                         {'username': 'deptadmin2', 'password': 'correct-horse'})

        entry = AuditLog.objects.get()
        self.assertEqual(entry.summary, 'Administrator signed in')
        self.assertEqual(entry.actor, self.admin)

    def test_already_signed_in_admin_skips_the_form(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.login_url)
        self.assertRedirects(response, reverse('adminpanel:admin_home'))

    def test_sign_out_requires_post(self):
        self.client.force_login(self.admin)

        self.assertRedirects(self.client.get(reverse('adminpanel:logout')),
                             reverse('adminpanel:admin_home'))

        response = self.client.post(reverse('adminpanel:logout'))
        self.assertRedirects(response, self.login_url)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


class AdminDashboardTests(TestCase):
    """The department dashboard and the sources each figure comes from."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin3', 'admin3@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user(
            'applicant16', 'a16@example.com', 'pw')
        self.url = reverse('adminpanel:dashboard')

    def test_dashboard_requires_an_administrator(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('adminpanel:login')}?next={self.url}")

        self.client.force_login(self.applicant)
        self.assertRedirects(self.client.get(self.url), reverse('home'))

    def test_headline_counts_reflect_the_data(self):
        make_application(self.applicant)
        make_application(self.applicant, building_address='77 Station Road',
                         status='NOC_ISSUED')
        self.client.force_login(self.admin)

        counts = self.client.get(self.url).context['counts']
        self.assertEqual(counts['applications'], 2)
        self.assertEqual(counts['nocs_issued'], 1)
        self.assertEqual(counts['awaiting_action'], 1)

    def test_open_deficiencies_are_counted(self):
        application = make_application(self.applicant)
        inspection = Inspection.objects.create(
            application=application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='COMPLETED')
        Deficiency.objects.create(
            application=application, inspection=inspection, title='Blocked exit',
            description='x', severity='CRITICAL', status='OPEN')
        self.client.force_login(self.admin)

        response = self.client.get(self.url)
        self.assertEqual(response.context['counts']['open_deficiencies'], 1)

    def test_dashboard_renders_for_an_empty_department(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Department Dashboard')


@skipUnless(connection.vendor == 'postgresql',
            'The materialized view only exists on PostgreSQL')
class DashboardStatisticsSourceTests(TestCase):
    """
    The status breakdown is precomputed, and the dashboard says so.

    These tests pin the behaviour that makes a materialized view honest: new
    applications do not appear until a refresh happens, and the page reports
    when that last was.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin4', 'admin4@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user(
            'applicant17', 'a17@example.com', 'pw')
        self.client.force_login(self.admin)
        self.url = reverse('adminpanel:dashboard')

    def test_new_application_is_absent_until_a_refresh(self):
        make_application(self.applicant)

        response = self.client.get(self.url)
        self.assertTrue(response.context['status_is_precomputed'])
        self.assertEqual(list(response.context['status_breakdown']), [])
        self.assertIsNone(response.context['last_refreshed_at'])

    def test_refresh_populates_the_breakdown_and_is_recorded(self):
        make_application(self.applicant)
        AuditLog.objects.all().delete()

        response = self.client.post(reverse('adminpanel:refresh_statistics'))
        self.assertRedirects(response, self.url)

        breakdown = self.client.get(self.url).context['status_breakdown']
        self.assertEqual(list(breakdown), [('PENDING', 1, 0)])

        entry = AuditLog.objects.get(summary='Reporting statistics refreshed')
        self.assertEqual(entry.actor, self.admin)

    def test_dashboard_reports_when_it_was_last_refreshed(self):
        make_application(self.applicant)
        self.client.post(reverse('adminpanel:refresh_statistics'))

        response = self.client.get(self.url)
        self.assertIsNotNone(response.context['last_refreshed_at'])

    def test_refresh_requires_post(self):
        response = self.client.get(reverse('adminpanel:refresh_statistics'))
        self.assertRedirects(response, self.url)

    def test_refresh_requires_an_administrator(self):
        self.client.force_login(self.applicant)

        response = self.client.post(reverse('adminpanel:refresh_statistics'))
        self.assertRedirects(response, reverse('home'))


class RefreshAuditTests(TestCase):
    """One refresh must produce exactly one audit entry, whichever route ran it."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin5', 'admin5@example.com', 'pw', is_staff=True)
        AuditLog.objects.all().delete()

    @skipUnless(connection.vendor == 'postgresql', 'needs the materialized view')
    def test_dashboard_refresh_records_one_entry_with_the_actor(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('adminpanel:refresh_statistics'))

        entry = AuditLog.objects.get(summary='Reporting statistics refreshed')
        self.assertEqual(entry.actor, self.admin)

    @skipUnless(connection.vendor == 'postgresql', 'needs the materialized view')
    def test_command_line_refresh_records_one_entry_without_an_actor(self):
        call_command('refreshviews', '--blocking', verbosity=0)

        entry = AuditLog.objects.get(summary='Reporting statistics refreshed')
        self.assertIsNone(entry.actor)


class ActivityFeedTests(TestCase):
    """The recent-activity feed on the dashboard."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin6', 'admin6@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user(
            'applicant18', 'a18@example.com', 'pw')
        self.url = reverse('adminpanel:dashboard')
        AuditLog.objects.all().delete()

    def test_feed_shows_recorded_entries_newest_first(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        actor=self.applicant, entity_id=1, summary='older')
        AuditLog.record(AuditLog.ACTION_APPROVE, AuditLog.ENTITY_APPLICATION,
                        actor=self.admin, entity_id=1, summary='newer')
        self.client.force_login(self.admin)

        activity = self.client.get(self.url).context['activity']
        self.assertEqual([e.summary for e in activity], ['newer', 'older'])

    def test_feed_can_be_filtered_by_entity(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='an application')
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_INSPECTION,
                        entity_id=2, summary='an inspection')
        self.client.force_login(self.admin)

        activity = self.client.get(self.url, {'entity': 'INSPECTION'}).context['activity']
        self.assertEqual([e.summary for e in activity], ['an inspection'])

    def test_feed_can_be_filtered_by_action(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='created')
        AuditLog.record(AuditLog.ACTION_REJECT, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='rejected')
        self.client.force_login(self.admin)

        activity = self.client.get(self.url, {'action': 'REJECT'}).context['activity']
        self.assertEqual([e.summary for e in activity], ['rejected'])

    def test_unknown_filter_values_are_ignored_not_passed_to_the_query(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='kept')
        self.client.force_login(self.admin)

        response = self.client.get(self.url, {'entity': 'NOT_A_TYPE',
                                              'action': 'NOT_AN_ACTION'})
        self.assertEqual([e.summary for e in response.context['activity']], ['kept'])
        self.assertEqual(response.context['activity_filters']['selected_entity'], '')

    def test_activity_counts_cover_the_last_seven_days(self):
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        entity_id=1, summary='recent')
        old = AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                              entity_id=2, summary='old')
        AuditLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        self.client.force_login(self.admin)

        counts = self.client.get(self.url).context['activity_counts']
        self.assertEqual(counts, [('CREATE', 1)])

    @skipUnless(connection.vendor == 'postgresql', 'needs the audit triggers')
    def test_trigger_written_entries_appear_without_an_actor(self):
        application = make_application(self.applicant)
        AuditLog.objects.all().delete()
        Application.objects.filter(pk=application.pk).update(status='APPROVED')
        self.client.force_login(self.admin)

        activity = self.client.get(self.url).context['activity']
        self.assertEqual(len(activity), 1)
        self.assertIsNone(activity[0].actor)
        self.assertEqual(activity[0].actor_label, 'database trigger')


class ApplicantListTests(TestCase):
    """The applicant management listing: who appears, search, filters, paging."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin7', 'admin7@example.com', 'pw', is_staff=True)
        self.url = reverse('adminpanel:applicant_list')

        self.alice = User.objects.create_user(
            'alice', 'alice@example.com', 'pw',
            first_name='Alice', last_name='Kumar')
        self.bob = User.objects.create_user(
            'bob', 'bob@example.com', 'pw', first_name='Bob', last_name='Singh')
        make_application(self.alice)
        self.client.force_login(self.admin)

    def _listed(self, **params):
        response = self.client.get(self.url, params)
        return [u.username for u in response.context['page'].object_list]

    def test_requires_an_administrator(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url),
                             f'{reverse("adminpanel:login")}?next={self.url}')

    def test_applicants_are_listed_with_their_application_count(self):
        response = self.client.get(self.url)
        listed = {u.username: u.application_count
                  for u in response.context['page'].object_list}

        self.assertEqual(listed, {'alice': 1, 'bob': 0})

    def test_applicant_who_never_applied_still_appears(self):
        self.assertIn('bob', self._listed())

    def test_officers_and_administrators_are_excluded(self):
        officer = User.objects.create_user('officer11', 'o11@example.com', 'pw')
        OfficerProfile.objects.create(
            user=officer, officer_id='FO-011', designation='Inspector')

        listed = self._listed()
        self.assertNotIn('officer11', listed)
        self.assertNotIn('deptadmin7', listed)

    def test_search_matches_name_email_and_username(self):
        for term in ('Alice', 'alice@example.com', 'alice'):
            self.assertEqual(self._listed(q=term), ['alice'], term)

    def test_search_matches_the_mobile_number_on_the_profile(self):
        profile = ApplicantProfile.objects.get(user=self.alice)
        profile.mobile_number = '9876543210'
        profile.save()

        self.assertEqual(self._listed(q='98765'), ['alice'])

    def test_search_matches_an_application_number(self):
        application = self.alice.fire_noc_applications.get()

        self.assertEqual(self._listed(q=application.application_id), ['alice'])

    def test_search_returning_nothing_is_not_an_error(self):
        response = self.client.get(self.url, {'q': 'nobody-by-that-name'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 0)

    def test_filter_by_whether_they_have_applied(self):
        self.assertEqual(self._listed(status='with_applications'), ['alice'])
        self.assertEqual(self._listed(status='no_applications'), ['bob'])

    def test_filter_by_account_state(self):
        self.bob.is_active = False
        self.bob.save(update_fields=['is_active'])

        self.assertEqual(self._listed(status='active'), ['alice'])
        self.assertEqual(self._listed(status='inactive'), ['bob'])

    def test_sorting_by_application_count(self):
        self.assertEqual(self._listed(sort='applications'), ['alice', 'bob'])

    def test_unknown_sort_falls_back_to_the_default(self):
        response = self.client.get(self.url, {'sort': 'nonsense'})

        self.assertEqual(response.context['sort'], queries.DEFAULT_APPLICANT_SORT)

    def test_results_are_paged(self):
        User.objects.bulk_create([
            User(username=f'bulk{i}', email=f'b{i}@example.com')
            for i in range(25)])

        first = self.client.get(self.url)
        self.assertEqual(len(first.context['page'].object_list), 20)
        self.assertEqual(first.context['total'], 27)

        second = self.client.get(self.url, {'page': 2})
        self.assertEqual(len(second.context['page'].object_list), 7)

    def test_filters_are_carried_into_the_paging_links(self):
        response = self.client.get(self.url, {'q': 'alice', 'status': 'active'})

        self.assertIn('q=alice', response.context['querystring'])
        self.assertIn('status=active', response.context['querystring'])

    def test_each_applicant_appears_once_however_many_applications(self):
        make_application(self.alice, building_address='77 Station Road')
        make_application(self.alice, building_address='9 Third Road')

        self.assertEqual(self._listed(q='alice'), ['alice'])


class ApplicantDetailTests(TestCase):
    """The applicant detail page: record, history and activity."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin8', 'admin8@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user(
            'carol', 'carol@example.com', 'pw', first_name='Carol', last_name='Mehta')
        self.client.force_login(self.admin)
        self.url = reverse('adminpanel:applicant_detail', args=[self.applicant.pk])

    def test_requires_an_administrator(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url),
                             f'{reverse("adminpanel:login")}?next={self.url}')

    def test_unknown_applicant_returns_404(self):
        url = reverse('adminpanel:applicant_detail', args=[999999])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_officer_account_is_refused(self):
        officer = User.objects.create_user('officer12', 'o12@example.com', 'pw')
        OfficerProfile.objects.create(
            user=officer, officer_id='FO-012', designation='Inspector')

        response = self.client.get(
            reverse('adminpanel:applicant_detail', args=[officer.pk]))
        self.assertRedirects(response, reverse('adminpanel:applicant_list'))

    def test_applicant_with_no_applications_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['applications'], [])
        self.assertEqual(response.context['summary']['total'], 0)

    def test_application_history_is_listed_newest_first(self):
        make_application(self.applicant, building_name='First Tower')
        make_application(self.applicant, building_address='77 Station Road',
                         building_name='Second Tower')

        history = self.client.get(self.url).context['applications']
        self.assertEqual([a['building_name'] for a in history],
                         ['Second Tower', 'First Tower'])

    def test_summary_counts_reflect_the_history(self):
        make_application(self.applicant)
        make_application(self.applicant, building_address='77 Station Road',
                         status='NOC_ISSUED')
        make_application(self.applicant, building_address='9 Third Road',
                         status='REJECTED')

        summary = self.client.get(self.url).context['summary']
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['issued'], 1)
        self.assertEqual(summary['in_progress'], 1)

    def test_open_deficiencies_are_counted_across_applications(self):
        application = make_application(self.applicant)
        inspection = Inspection.objects.create(
            application=application, scheduled_date=date(2026, 12, 1),
            scheduled_time=time(10, 0), status='COMPLETED')
        Deficiency.objects.create(
            application=application, inspection=inspection, title='Blocked exit',
            description='x', severity='MAJOR', status='OPEN')

        summary = self.client.get(self.url).context['summary']
        self.assertEqual(summary['open_deficiencies'], 1)

    def test_profile_details_are_shown_when_present(self):
        make_application(self.applicant, mobile_number='9876543210')

        response = self.client.get(self.url)
        self.assertEqual(response.context['profile'].mobile_number, '9876543210')

    def test_missing_profile_is_reported_rather_than_hidden(self):
        response = self.client.get(self.url)

        self.assertIsNone(response.context['profile'])
        self.assertContains(response, 'No normalized applicant record')

    def test_activity_includes_actions_taken_by_others_on_their_application(self):
        application = make_application(self.applicant)
        officer = User.objects.create_user('officer13', 'o13@example.com', 'pw')
        AuditLog.objects.all().delete()
        AuditLog.record(AuditLog.ACTION_REJECT, AuditLog.ENTITY_APPLICATION,
                        actor=officer, entity=application,
                        summary='Rejected after inspection')

        activity = self.client.get(self.url).context['activity']
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0].actor, officer)

    def test_activity_excludes_other_applicants_entries(self):
        other = User.objects.create_user('dave', 'dave@example.com', 'pw')
        make_application(self.applicant)
        AuditLog.objects.all().delete()
        AuditLog.record(AuditLog.ACTION_CREATE, AuditLog.ENTITY_APPLICATION,
                        actor=other, entity_id=99999, summary='someone else')

        self.assertEqual(self.client.get(self.url).context['activity'], [])

    def test_listing_links_to_the_detail_page(self):
        response = self.client.get(reverse('adminpanel:applicant_list'))

        self.assertContains(response, f'/admin-panel/applicants/{self.applicant.pk}/')
