from datetime import date, time, timedelta
from decimal import Decimal
from io import StringIO
from unittest import skipUnless

from django.contrib.auth.models import User
from django.contrib.messages import constants as message_constants
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from officers.models import (ApplicationReview, Deficiency, DocumentVerification,
                             Inspection, InspectionReport, OfficerProfile)

from applicants.models import Application, ApplicationDocument

from . import queries, services
from .models import NOC, ApplicantProfile, AuditLog, Building, PinCode
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


class OfficerManagementTests(TestCase):
    """Officer listing and detail."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin9', 'admin9@example.com', 'pw', is_staff=True)
        self.user = User.objects.create_user(
            'ravi', 'ravi@example.com', 'pw', first_name='Ravi', last_name='Sharma')
        self.profile = OfficerProfile.objects.create(
            user=self.user, officer_id='FO-101', designation='Station Officer',
            badge_number='B-77', phone='9811122233')
        self.list_url = reverse('adminpanel:officer_list')
        self.detail_url = reverse('adminpanel:officer_detail', args=[self.profile.pk])
        self.client.force_login(self.admin)

    def _listed(self, **params):
        response = self.client.get(self.list_url, params)
        return [p.officer_id for p in response.context['page'].object_list]

    def test_listing_requires_an_administrator(self):
        self.client.logout()
        self.assertRedirects(
            self.client.get(self.list_url),
            f'{reverse("adminpanel:login")}?next={self.list_url}')

    def test_officers_are_listed_and_applicants_are_not(self):
        User.objects.create_user('plain', 'plain@example.com', 'pw')

        self.assertEqual(self._listed(), ['FO-101'])

    def test_search_matches_officer_id_designation_badge_and_name(self):
        for term in ('FO-101', 'Station', 'B-77', 'Ravi', 'ravi@example.com'):
            self.assertEqual(self._listed(q=term), ['FO-101'], term)

    def test_filter_by_active_state(self):
        self.assertEqual(self._listed(status='active'), ['FO-101'])

        self.profile.is_active = False
        self.profile.save(update_fields=['is_active'])
        self.assertEqual(self._listed(status='active'), [])
        self.assertEqual(self._listed(status='inactive'), ['FO-101'])

    def test_a_disabled_account_counts_as_deactivated(self):
        # The profile is still active, but the account cannot sign in.
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        self.assertEqual(self._listed(status='active'), [])
        self.assertEqual(self._listed(status='inactive'), ['FO-101'])

    def test_unknown_sort_falls_back_to_the_default(self):
        response = self.client.get(self.list_url, {'sort': 'nonsense'})

        self.assertEqual(response.context['sort'], queries.DEFAULT_OFFICER_SORT)

    @skipUnless(connection.vendor == 'postgresql', 'needs v_officer_workload')
    def test_workload_is_attached_to_each_row(self):
        applicant = User.objects.create_user('applicant19', 'a19@example.com', 'pw')
        application = make_application(applicant)
        Inspection.objects.create(
            application=application, officer=self.user,
            scheduled_date=date(2026, 12, 1), scheduled_time=time(10, 0),
            status='COMPLETED')

        row = self.client.get(self.list_url).context['page'].object_list[0]
        self.assertEqual(row.workload['inspections_total'], 1)
        self.assertEqual(row.workload['inspections_completed'], 1)

    def test_detail_shows_the_officer_record(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['profile'], self.profile)
        self.assertContains(response, 'FO-101')
        self.assertContains(response, 'B-77')

    def test_detail_lists_inspections_conducted(self):
        applicant = User.objects.create_user('applicant20', 'a20@example.com', 'pw')
        application = make_application(applicant)
        Inspection.objects.create(
            application=application, officer=self.user,
            scheduled_date=date(2026, 12, 1), scheduled_time=time(10, 0),
            status='SCHEDULED')

        inspections = self.client.get(self.detail_url).context['inspections']
        self.assertEqual(len(inspections), 1)
        self.assertEqual(inspections[0].application, application)

    def test_detail_shows_recorded_actions(self):
        AuditLog.objects.all().delete()
        AuditLog.record(AuditLog.ACTION_APPROVE, AuditLog.ENTITY_INSPECTION,
                        actor=self.user, entity_id=1, summary='Completed inspection')

        activity = self.client.get(self.detail_url).context['activity']
        self.assertEqual([e.summary for e in activity], ['Completed inspection'])

    def test_unknown_officer_returns_404(self):
        url = reverse('adminpanel:officer_detail', args=[999999])

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_listing_links_to_the_detail_page(self):
        response = self.client.get(self.list_url)

        self.assertContains(response, f'/admin-panel/officers/{self.profile.pk}/')


class OfficerActivationTests(TestCase):
    """Activating and deactivating an officer, and what gets recorded."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin10', 'admin10@example.com', 'pw', is_staff=True)
        self.user = User.objects.create_user('meera', 'meera@example.com', 'pw')
        self.profile = OfficerProfile.objects.create(
            user=self.user, officer_id='FO-202', designation='Inspector')
        self.url = reverse('adminpanel:officer_set_active', args=[self.profile.pk])
        self.detail_url = reverse('adminpanel:officer_detail', args=[self.profile.pk])
        self.client.force_login(self.admin)
        AuditLog.objects.all().delete()

    def _refresh(self):
        self.profile.refresh_from_db()
        self.user.refresh_from_db()

    def test_requires_an_administrator(self):
        self.client.logout()

        response = self.client.post(self.url, {'action': 'deactivate'})
        self.assertRedirects(response, f'{reverse("adminpanel:login")}?next={self.url}')
        self._refresh()
        self.assertTrue(self.profile.is_active)

    def test_get_does_not_change_anything(self):
        response = self.client.get(self.url)

        self.assertRedirects(response, self.detail_url)
        self._refresh()
        self.assertTrue(self.profile.is_active)

    def test_deactivation_clears_both_the_profile_and_the_account(self):
        response = self.client.post(self.url, {'action': 'deactivate'})

        self.assertRedirects(response, self.detail_url)
        self._refresh()
        self.assertFalse(self.profile.is_active)
        self.assertFalse(self.user.is_active, 'the account must be disabled too')

    def test_deactivated_officer_cannot_sign_in(self):
        self.client.post(self.url, {'action': 'deactivate'})
        self.client.logout()

        signed_in = self.client.login(username='meera', password='pw')
        self.assertFalse(signed_in)

    def test_reactivation_restores_both_flags(self):
        self.client.post(self.url, {'action': 'deactivate'})

        self.client.post(self.url, {'action': 'activate'})
        self._refresh()
        self.assertTrue(self.profile.is_active)
        self.assertTrue(self.user.is_active)

    def test_change_is_audited_against_the_administrator(self):
        self.client.post(self.url, {'action': 'deactivate'})

        entry = AuditLog.objects.get()
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.entity_type, 'OFFICER')
        self.assertIn('FO-202', entry.summary)
        self.assertEqual(entry.changes['is_active'], {'from': True, 'to': False})

    def test_outstanding_work_is_recorded_at_the_moment_of_the_decision(self):
        applicant = User.objects.create_user('applicant21', 'a21@example.com', 'pw')
        application = make_application(applicant)
        Inspection.objects.create(
            application=application, officer=self.user,
            scheduled_date=date(2026, 12, 1), scheduled_time=time(10, 0),
            status='SCHEDULED')

        self.client.post(self.url, {'action': 'deactivate'})

        entry = AuditLog.objects.get()
        self.assertEqual(entry.changes['outstanding']['scheduled_inspections'], 1)
        self.assertIn('scheduled inspection', entry.summary)

    def test_deactivation_is_allowed_despite_outstanding_work_but_warns(self):
        applicant = User.objects.create_user('applicant22', 'a22@example.com', 'pw')
        application = make_application(applicant)
        Inspection.objects.create(
            application=application, officer=self.user,
            scheduled_date=date(2026, 12, 1), scheduled_time=time(10, 0),
            status='SCHEDULED')

        response = self.client.post(self.url, {'action': 'deactivate'}, follow=True)

        self._refresh()
        self.assertFalse(self.profile.is_active)
        warnings = [m.message for m in response.context['messages']
                    if m.level_tag == 'warning']
        self.assertTrue(any('need reassigning' in m for m in warnings), warnings)

    def test_repeating_the_same_action_changes_nothing_and_is_not_audited(self):
        self.client.post(self.url, {'action': 'activate'})

        self.assertEqual(AuditLog.objects.count(), 0)
        self._refresh()
        self.assertTrue(self.profile.is_active)

    def test_unrecognised_action_is_rejected(self):
        response = self.client.post(self.url, {'action': 'delete'})

        self.assertRedirects(response, self.detail_url)
        self._refresh()
        self.assertTrue(self.profile.is_active)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_detail_page_offers_the_right_control_for_the_current_state(self):
        active = self.client.get(self.detail_url)
        self.assertContains(active, 'Deactivate officer')
        self.assertNotContains(active, 'Reactivate officer')

        self.client.post(self.url, {'action': 'deactivate'})
        inactive = self.client.get(self.detail_url)
        self.assertContains(inactive, 'Reactivate officer')

    def test_detail_page_warns_before_deactivating_someone_with_work(self):
        applicant = User.objects.create_user('applicant23', 'a23@example.com', 'pw')
        application = make_application(applicant)
        Inspection.objects.create(
            application=application, officer=self.user,
            scheduled_date=date(2026, 12, 1), scheduled_time=time(10, 0),
            status='SCHEDULED')

        response = self.client.get(self.detail_url)
        self.assertContains(response, 'will need reassigning')


def issue_noc(application, **overrides):
    """A certificate for an application, with sensible defaults."""
    issued = overrides.pop('issued_at', timezone.now())
    valid_from = overrides.pop('valid_from', issued.date())
    years = NOC.validity_years_for(application.occupancy_type)
    values = dict(
        application=application,
        noc_number=NOC.next_number(issued.year),
        issued_at=issued,
        valid_from=valid_from,
        valid_until=valid_from.replace(year=valid_from.year + years),
    )
    values.update(overrides)
    return NOC.objects.create(**values)


class NOCNumberingTests(TestCase):
    """The certificate number series, which is separate from the application's."""

    def setUp(self):
        self.applicant = User.objects.create_user('nocuser', 'n@example.com', 'pw')
        self.application = make_application(self.applicant)

    def test_first_number_of_a_year(self):
        self.assertEqual(NOC.next_number(2026), 'FN/2026/00001')

    def test_numbers_increment(self):
        issue_noc(self.application, noc_number='FN/2026/00001',
                  issued_at=timezone.now())

        self.assertEqual(NOC.next_number(2026), 'FN/2026/00002')

    def test_series_restarts_each_year(self):
        issue_noc(self.application, noc_number='FN/2026/00007')

        self.assertEqual(NOC.next_number(2027), 'FN/2027/00001')
        self.assertEqual(NOC.next_number(2026), 'FN/2026/00008')

    def test_number_is_padded_so_it_sorts_correctly(self):
        issue_noc(self.application, noc_number='FN/2026/00009')

        self.assertEqual(NOC.next_number(2026), 'FN/2026/00010')

    def test_certificate_number_is_not_the_application_number(self):
        noc = issue_noc(self.application)

        self.assertNotEqual(noc.noc_number, self.application.application_id)
        self.assertTrue(noc.noc_number.startswith('FN/'))

    def test_numbers_are_unique_in_the_database(self):
        issue_noc(self.application, noc_number='FN/2026/00001')
        second = make_application(self.applicant, building_address='77 Station Road')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                issue_noc(second, noc_number='FN/2026/00001')


class NOCValidityTests(TestCase):
    """Validity periods, stored rather than derived."""

    def setUp(self):
        self.applicant = User.objects.create_user('nocuser2', 'n2@example.com', 'pw')

    def test_residential_buildings_get_three_years(self):
        self.assertEqual(NOC.validity_years_for('RESIDENTIAL'), 3)

    def test_other_occupancies_get_one_year(self):
        for occupancy in ('BUSINESS', 'ASSEMBLY', 'INDUSTRIAL', 'HEALTHCARE'):
            self.assertEqual(NOC.validity_years_for(occupancy), 1, occupancy)

    def test_an_active_in_date_certificate_is_valid(self):
        noc = issue_noc(make_application(self.applicant))

        self.assertTrue(noc.is_currently_valid)
        self.assertFalse(noc.is_expired)

    def test_a_past_end_date_makes_it_expired_even_while_marked_active(self):
        application = make_application(self.applicant)
        noc = issue_noc(
            application,
            valid_from=date(2020, 1, 1),
            valid_until=date(2021, 1, 1))

        self.assertEqual(noc.status, NOC.STATUS_ACTIVE)
        self.assertTrue(noc.is_expired, 'the calendar passing is what expires it')
        self.assertFalse(noc.is_currently_valid)

    def test_a_revoked_certificate_is_not_valid_even_while_in_date(self):
        noc = issue_noc(make_application(self.applicant),
                        status=NOC.STATUS_REVOKED)

        self.assertFalse(noc.is_expired)
        self.assertFalse(noc.is_currently_valid)

    def test_dates_do_not_move_when_the_application_is_edited(self):
        application = make_application(self.applicant)
        noc = issue_noc(application)
        issued, until = noc.issued_at, noc.valid_until

        application.remarks = 'Edited long after issue'
        application.save()

        noc.refresh_from_db()
        self.assertEqual(noc.issued_at, issued)
        self.assertEqual(noc.valid_until, until)

    def test_days_until_expiry(self):
        today = timezone.localdate()
        noc = issue_noc(make_application(self.applicant),
                        valid_from=today, valid_until=today + timedelta(days=30))

        self.assertEqual(noc.days_until_expiry, 30)

    def test_database_rejects_an_end_date_before_the_start(self):
        application = make_application(self.applicant)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                issue_noc(application, valid_from=date(2026, 6, 1),
                          valid_until=date(2026, 1, 1))


class NOCUniquenessTests(TestCase):
    """One live certificate per application, with revoked ones retained."""

    def setUp(self):
        self.applicant = User.objects.create_user('nocuser3', 'n3@example.com', 'pw')
        self.application = make_application(self.applicant)

    def test_one_application_cannot_hold_two_active_certificates(self):
        issue_noc(self.application)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                issue_noc(self.application)

    def test_a_revoked_certificate_does_not_block_reissuing(self):
        revoked = issue_noc(self.application, status=NOC.STATUS_REVOKED)

        replacement = issue_noc(self.application)

        self.assertEqual(NOC.objects.filter(application=self.application).count(), 2)
        self.assertEqual(replacement.status, NOC.STATUS_ACTIVE)
        self.assertEqual(revoked.status, NOC.STATUS_REVOKED)

    def test_an_expired_certificate_still_blocks_a_second_live_one(self):
        # Expiry is not withdrawal: the certificate remains the one that was
        # issued for that application, so reissuing needs renewal, not a
        # second row.
        issue_noc(self.application, status=NOC.STATUS_EXPIRED)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                issue_noc(self.application)

    def test_database_rejects_an_unknown_status(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                issue_noc(self.application, status='CANCELLED')


class NOCIntegrationContractTests(TestCase):
    """
    The applicant module contains a runtime hook that looks for a model named
    NOC carrying an `application` field, and reads `noc_number` and
    `issued_at` off it. These tests pin that contract, because breaking it
    fails silently: the timeline stage simply stops appearing.
    """

    def setUp(self):
        self.applicant = User.objects.create_user('nocuser4', 'n4@example.com', 'pw')
        self.application = make_application(self.applicant)

    def test_model_exposes_the_names_the_applicant_module_looks_for(self):
        field_names = [f.name for f in NOC._meta.get_fields()]

        self.assertEqual(NOC.__name__.lower(), 'noc')
        self.assertIn('application', field_names)
        self.assertIn('noc_number', field_names)
        self.assertIn('issued_at', field_names)

    def test_the_applicant_timeline_finds_the_certificate(self):
        noc = issue_noc(self.application)
        self.client.force_login(self.applicant)

        response = self.client.get(
            reverse('applicants:application_timeline',
                    args=[self.application.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, noc.noc_number)

    def test_the_timeline_has_no_issued_stage_without_a_certificate(self):
        self.client.force_login(self.applicant)

        response = self.client.get(
            reverse('applicants:application_timeline',
                    args=[self.application.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'FN/')


def make_issuable_application(applicant, officer, **overrides):
    """
    An application that has passed every check an officer applies.

    Documents verified, inspection completed with a satisfactory report, no
    unresolved deficiencies, and recommended for approval. Built through the
    real models rather than by forcing a status, so the eligibility gate is
    exercised as it would be in use.
    """
    application = make_application(applicant, status='APPROVED', **overrides)

    document = ApplicationDocument.objects.create(
        application=application, document_type='FIRE_SAFETY_PLAN',
        document_name='plan.pdf', file='documents/plan.pdf')
    DocumentVerification.objects.create(
        document=document, verified_by=officer, status='VERIFIED',
        verified_at=timezone.now())

    inspection = Inspection.objects.create(
        application=application, officer=officer,
        scheduled_date=date(2026, 11, 1), scheduled_time=time(10, 0),
        status='COMPLETED', completed_at=timezone.now())
    InspectionReport.objects.create(
        inspection=inspection, overall_result='SATISFACTORY',
        completed_at=timezone.now())

    ApplicationReview.objects.create(
        application=application, reviewed_by=officer,
        status='DOCUMENTS_VERIFIED', recommendation='RECOMMENDED_FOR_APPROVAL',
        recommended_by=officer, recommended_at=timezone.now())

    return application


class IssuanceEligibilityTests(TestCase):
    """What stands between an application and a certificate."""

    def setUp(self):
        self.applicant = User.objects.create_user('iss1', 'i1@example.com', 'pw')
        self.officer = User.objects.create_user('issofficer', 'io@example.com', 'pw')
        OfficerProfile.objects.create(
            user=self.officer, officer_id='FO-301', designation='Inspector')

    def test_a_fully_checked_application_can_be_issued(self):
        application = make_issuable_application(self.applicant, self.officer)

        self.assertEqual(services.issuance_blockers(application), [])
        self.assertTrue(services.can_issue(application))

    def test_a_bare_application_cannot_be_issued(self):
        application = make_application(self.applicant)

        self.assertTrue(services.issuance_blockers(application))
        self.assertFalse(services.can_issue(application))

    def test_without_an_officer_recommendation_it_is_refused(self):
        application = make_issuable_application(self.applicant, self.officer)
        application.officer_review.recommendation = 'PENDING'
        application.officer_review.save()

        reasons = services.issuance_blockers(application)
        self.assertTrue(any('recommended' in r for r in reasons), reasons)

    def test_an_open_deficiency_blocks_issue(self):
        application = make_issuable_application(self.applicant, self.officer)
        Deficiency.objects.create(
            application=application, inspection=application.inspections.first(),
            title='Blocked exit', description='x', severity='MAJOR', status='OPEN')

        self.assertFalse(services.can_issue(application))

    def test_a_rejected_application_is_refused(self):
        application = make_issuable_application(self.applicant, self.officer)
        Application.objects.filter(pk=application.pk).update(status='REJECTED')
        application.refresh_from_db()

        reasons = services.issuance_blockers(application)
        self.assertTrue(any('rejected' in r.lower() for r in reasons), reasons)

    def test_an_existing_certificate_blocks_a_second(self):
        application = make_issuable_application(self.applicant, self.officer)
        services.issue_noc(application, actor=self.officer)

        reasons = services.issuance_blockers(application)
        self.assertTrue(any('already been issued' in r for r in reasons), reasons)

    def test_a_revoked_certificate_does_not_block_reissue(self):
        application = make_issuable_application(self.applicant, self.officer)
        noc = services.issue_noc(application, actor=self.officer)
        NOC.objects.filter(pk=noc.pk).update(status=NOC.STATUS_REVOKED)
        Application.objects.filter(pk=application.pk).update(status='APPROVED')
        application.refresh_from_db()

        self.assertEqual(services.issuance_blockers(application), [])


class IssuanceTests(TestCase):
    """Issuing a certificate, and what it changes."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin11', 'admin11@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user('iss2', 'i2@example.com', 'pw')
        self.officer = User.objects.create_user('issofficer2', 'io2@example.com', 'pw')
        OfficerProfile.objects.create(
            user=self.officer, officer_id='FO-302', designation='Inspector')
        self.application = make_issuable_application(self.applicant, self.officer)
        AuditLog.objects.all().delete()

    def test_issuing_creates_a_certificate_with_its_own_number(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        self.assertTrue(noc.noc_number.startswith('FN/'))
        self.assertEqual(noc.status, NOC.STATUS_ACTIVE)
        self.assertEqual(noc.issued_by, self.admin)
        self.assertTrue(noc.is_currently_valid)

    def test_issuing_moves_the_application_to_noc_issued(self):
        services.issue_noc(self.application, actor=self.admin)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'NOC_ISSUED')

    def test_validity_follows_the_occupancy_type(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        self.assertEqual(noc.valid_until.year - noc.valid_from.year, 1)

    def test_residential_buildings_are_issued_for_three_years(self):
        residential = make_issuable_application(
            self.applicant, self.officer,
            building_address='9 Residential Lane', occupancy_type='RESIDENTIAL')

        noc = services.issue_noc(residential, actor=self.admin)
        self.assertEqual(noc.valid_until.year - noc.valid_from.year, 3)

    def test_issuing_is_audited(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        entry = AuditLog.objects.get(action='ISSUE')
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.entity_type, 'NOC')
        self.assertIn(noc.noc_number, entry.summary)
        self.assertEqual(entry.changes['noc_number'], noc.noc_number)

    def test_refusal_names_every_unmet_condition(self):
        bare = make_application(self.applicant, building_address='77 Station Road')

        with self.assertRaises(services.IssuanceRefused) as refused:
            services.issue_noc(bare, actor=self.admin)

        self.assertTrue(len(refused.exception.reasons) >= 1)

    def test_a_refused_issue_leaves_nothing_behind(self):
        bare = make_application(self.applicant, building_address='77 Station Road')

        with self.assertRaises(services.IssuanceRefused):
            services.issue_noc(bare, actor=self.admin)

        self.assertEqual(NOC.objects.count(), 0)
        bare.refresh_from_db()
        self.assertNotEqual(bare.status, 'NOC_ISSUED')

    def test_consecutive_issues_get_consecutive_numbers(self):
        second = make_issuable_application(
            self.applicant, self.officer, building_address='77 Station Road')

        first_noc = services.issue_noc(self.application, actor=self.admin)
        second_noc = services.issue_noc(second, actor=self.admin)

        self.assertNotEqual(first_noc.noc_number, second_noc.noc_number)
        self.assertEqual(
            int(second_noc.noc_number.rsplit('/', 1)[1]),
            int(first_noc.noc_number.rsplit('/', 1)[1]) + 1)


class NOCScreenTests(TestCase):
    """The certificates screen and the issue action."""

    def setUp(self):
        self.admin = User.objects.create_user(
            'deptadmin12', 'admin12@example.com', 'pw', is_staff=True)
        self.applicant = User.objects.create_user('iss3', 'i3@example.com', 'pw')
        self.officer = User.objects.create_user('issofficer3', 'io3@example.com', 'pw')
        OfficerProfile.objects.create(
            user=self.officer, officer_id='FO-303', designation='Inspector')
        self.application = make_issuable_application(self.applicant, self.officer)
        self.url = reverse('adminpanel:noc_list')
        self.issue_url = reverse('adminpanel:noc_issue', args=[self.application.pk])
        self.client.force_login(self.admin)

    def test_screen_requires_an_administrator(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url),
                             f'{reverse("adminpanel:login")}?next={self.url}')

    def test_ready_applications_are_listed(self):
        ready = self.client.get(self.url).context['ready']

        self.assertEqual([a.pk for a, _ in ready], [self.application.pk])

    def test_blocked_applications_show_their_reasons(self):
        Deficiency.objects.create(
            application=self.application,
            inspection=self.application.inspections.first(),
            title='Blocked exit', description='x', severity='MAJOR', status='OPEN')

        response = self.client.get(self.url)
        self.assertEqual(response.context['ready'], [])
        self.assertEqual(len(response.context['blocked']), 1)

    def test_issuing_through_the_screen_creates_the_certificate(self):
        response = self.client.post(self.issue_url, follow=True)

        self.assertEqual(NOC.objects.count(), 1)
        self.assertContains(response, NOC.objects.get().noc_number)

    def test_issue_requires_post(self):
        self.client.get(self.issue_url)

        self.assertEqual(NOC.objects.count(), 0)

    def test_issue_requires_an_administrator(self):
        self.client.force_login(self.applicant)

        self.client.post(self.issue_url)
        self.assertEqual(NOC.objects.count(), 0)

    def test_a_refused_issue_reports_the_reasons_on_screen(self):
        bare = make_application(self.applicant, building_address='77 Station Road')

        response = self.client.post(
            reverse('adminpanel:noc_issue', args=[bare.pk]), follow=True)

        # The project maps ERROR to the Bootstrap tag "danger", so the level
        # constant is checked rather than the tag string.
        errors = [m.message for m in response.context['messages']
                  if m.level == message_constants.ERROR]
        self.assertTrue(errors, 'the refusal reasons must reach the page')
        self.assertTrue(any('recommended' in e for e in errors), errors)
        self.assertEqual(NOC.objects.count(), 0)

    def test_issued_certificates_are_listed_and_searchable(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        listed = self.client.get(self.url, {'q': noc.noc_number})
        self.assertEqual([n.pk for n in listed.context['page'].object_list], [noc.pk])


class ApplicantFacingCertificateTests(TestCase):
    """
    The applicant module's certificate pages, now reading issued records.

    These live here rather than in the applicant module's tests because the
    behaviour they pin belongs to the NOC work: a certificate page needs a
    certificate, and approval alone is not one.
    """

    def setUp(self):
        self.applicant = User.objects.create_user('cert1', 'c1@example.com', 'pw')
        self.officer = User.objects.create_user('certofficer', 'co@example.com', 'pw')
        OfficerProfile.objects.create(
            user=self.officer, officer_id='FO-401', designation='Inspector')
        self.admin = User.objects.create_user(
            'deptadmin13', 'admin13@example.com', 'pw', is_staff=True)
        self.application = make_issuable_application(self.applicant, self.officer)
        self.client.force_login(self.applicant)

    def test_approved_without_a_certificate_shows_nothing(self):
        response = self.client.get(reverse('applicants:my_nocs'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['noc_list'], [])

    def test_certificate_page_is_404_before_issue(self):
        url = reverse('applicants:noc_certificate', args=[self.application.pk])

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_issued_certificate_appears_with_its_own_number(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        response = self.client.get(reverse('applicants:my_nocs'))
        self.assertEqual(len(response.context['noc_list']), 1)
        self.assertContains(response, noc.noc_number)
        self.assertContains(response, self.application.application_id)

    def test_certificate_page_shows_the_stored_dates(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        response = self.client.get(
            reverse('applicants:noc_certificate', args=[self.application.pk]))
        self.assertEqual(response.context['certificate_number'], noc.noc_number)
        self.assertEqual(response.context['issue_date'], noc.issued_at.date())
        self.assertEqual(response.context['valid_until'], noc.valid_until)

    def test_editing_the_application_does_not_move_the_certificate_dates(self):
        noc = services.issue_noc(self.application, actor=self.admin)
        url = reverse('applicants:noc_certificate', args=[self.application.pk])
        before = self.client.get(url).context['issue_date']

        self.application.remarks = 'Edited after issue'
        self.application.save()

        after = self.client.get(url).context['issue_date']
        self.assertEqual(before, after)
        self.assertEqual(after, noc.issued_at.date())

    def test_another_applicant_cannot_read_the_certificate(self):
        services.issue_noc(self.application, actor=self.admin)
        other = User.objects.create_user('cert2', 'c2@example.com', 'pw')
        self.client.force_login(other)

        url = reverse('applicants:noc_certificate', args=[self.application.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_pdf_is_named_after_the_certificate(self):
        noc = services.issue_noc(self.application, actor=self.admin)

        response = self.client.get(
            reverse('applicants:noc_certificate_pdf', args=[self.application.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn(noc.noc_number.replace('/', '_'),
                      response['Content-Disposition'])

    def test_verification_number_is_stable_across_requests(self):
        # The previous implementation used Python's hash(), which is
        # randomised per process, so the printed "verification hash" changed
        # after every server restart.
        services.issue_noc(self.application, actor=self.admin)
        url = reverse('applicants:noc_certificate_pdf', args=[self.application.pk])

        first = self.client.get(url).content
        second = self.client.get(url).content

        self.assertEqual(first, second)


class CertificateExpiryTests(TestCase):
    """The sweep that marks lapsed certificates expired."""

    def setUp(self):
        self.applicant = User.objects.create_user('exp1', 'e1@example.com', 'pw')
        self.admin = User.objects.create_user(
            'deptadmin14', 'admin14@example.com', 'pw', is_staff=True)
        self.today = timezone.localdate()
        AuditLog.objects.all().delete()

    def _certificate(self, *, valid_until, status=NOC.STATUS_ACTIVE, address='12 MI Road'):
        application = make_application(self.applicant, building_address=address)
        return issue_noc(application, status=status,
                         valid_from=valid_until - timedelta(days=365),
                         valid_until=valid_until)

    def test_a_lapsed_certificate_is_marked_expired(self):
        noc = self._certificate(valid_until=self.today - timedelta(days=1))

        expired = services.expire_due_certificates()

        noc.refresh_from_db()
        self.assertEqual([n.pk for n in expired], [noc.pk])
        self.assertEqual(noc.status, NOC.STATUS_EXPIRED)

    def test_a_certificate_expiring_today_is_still_valid(self):
        # Validity runs to the end of the day it expires, so "today" is in
        # date, not out of it.
        noc = self._certificate(valid_until=self.today)

        services.expire_due_certificates()

        noc.refresh_from_db()
        self.assertEqual(noc.status, NOC.STATUS_ACTIVE)

    def test_a_future_certificate_is_untouched(self):
        noc = self._certificate(valid_until=self.today + timedelta(days=30))

        services.expire_due_certificates()

        noc.refresh_from_db()
        self.assertEqual(noc.status, NOC.STATUS_ACTIVE)

    def test_a_revoked_certificate_is_not_overwritten(self):
        # Withdrawal is a stronger statement than lapsing; overwriting it
        # would lose the reason the certificate is not valid.
        noc = self._certificate(valid_until=self.today - timedelta(days=10),
                                status=NOC.STATUS_REVOKED)

        services.expire_due_certificates()

        noc.refresh_from_db()
        self.assertEqual(noc.status, NOC.STATUS_REVOKED)

    def test_expiry_is_audited_without_an_actor(self):
        noc = self._certificate(valid_until=self.today - timedelta(days=1))

        services.expire_due_certificates()

        entry = AuditLog.objects.get(entity_type='NOC')
        self.assertIsNone(entry.actor, 'the calendar expired it, not a person')
        self.assertIn(noc.noc_number, entry.summary)
        self.assertEqual(entry.changes['status'],
                         {'from': 'ACTIVE', 'to': 'EXPIRED'})

    def test_running_the_sweep_twice_changes_nothing_the_second_time(self):
        self._certificate(valid_until=self.today - timedelta(days=1))

        services.expire_due_certificates()
        before = AuditLog.objects.count()
        second = services.expire_due_certificates()

        self.assertEqual(second, [])
        self.assertEqual(AuditLog.objects.count(), before)

    def test_the_command_reports_what_it_expired(self):
        self._certificate(valid_until=self.today - timedelta(days=1))
        output = StringIO()

        call_command('expirenocs', stdout=output)

        self.assertIn('1 certificate(s) expired', output.getvalue())

    def test_dry_run_changes_nothing(self):
        noc = self._certificate(valid_until=self.today - timedelta(days=1))
        output = StringIO()

        call_command('expirenocs', '--dry-run', stdout=output)

        noc.refresh_from_db()
        self.assertEqual(noc.status, NOC.STATUS_ACTIVE)
        self.assertIn('would expire', output.getvalue())


class RenewalTrackingTests(TestCase):
    """Certificates approaching expiry, and whether a renewal was filed."""

    def setUp(self):
        self.applicant = User.objects.create_user('ren1', 'r1@example.com', 'pw')
        self.admin = User.objects.create_user(
            'deptadmin15', 'admin15@example.com', 'pw', is_staff=True)
        self.today = timezone.localdate()

    def _certificate(self, days_ahead, address='12 MI Road'):
        application = make_application(self.applicant, building_address=address)
        valid_until = self.today + timedelta(days=days_ahead)
        return issue_noc(application,
                         valid_from=valid_until - timedelta(days=365),
                         valid_until=valid_until)

    def test_a_certificate_inside_the_window_is_listed(self):
        noc = self._certificate(30)

        due = services.certificates_due_for_renewal()
        self.assertEqual([n.pk for n in due], [noc.pk])

    def test_a_certificate_beyond_the_window_is_not(self):
        self._certificate(200)

        self.assertEqual(list(services.certificates_due_for_renewal()), [])

    def test_an_already_lapsed_certificate_is_not_a_renewal_candidate(self):
        # It needs expiring, not chasing; the sweep handles it.
        self._certificate(-5)

        self.assertEqual(list(services.certificates_due_for_renewal()), [])

    def test_soonest_to_lapse_comes_first(self):
        later = self._certificate(50, address='77 Station Road')
        sooner = self._certificate(5, address='12 MI Road')

        due = list(services.certificates_due_for_renewal())
        self.assertEqual([n.pk for n in due], [sooner.pk, later.pk])

    def test_a_filed_renewal_is_detected(self):
        noc = self._certificate(20)
        self.assertFalse(services.has_renewal_application(noc))

        make_application(self.applicant, building_address='12 MI Road',
                         application_type='RENEWAL')

        self.assertTrue(services.has_renewal_application(noc))

    def test_a_renewal_for_a_different_building_does_not_count(self):
        noc = self._certificate(20)
        make_application(self.applicant, building_address='99 Other Road',
                         application_type='RENEWAL')

        self.assertFalse(services.has_renewal_application(noc))

    def test_a_rejected_renewal_does_not_count(self):
        noc = self._certificate(20)
        renewal = make_application(self.applicant, building_address='12 MI Road',
                                   application_type='RENEWAL')
        Application.objects.filter(pk=renewal.pk).update(status='REJECTED')

        self.assertFalse(services.has_renewal_application(noc))

    def test_the_screen_lists_certificates_due_for_renewal(self):
        noc = self._certificate(20)
        self.client.force_login(self.admin)

        response = self.client.get(reverse('adminpanel:noc_list'))

        self.assertEqual([n.pk for n, _ in response.context['renewals']], [noc.pk])
        self.assertContains(response, 'Due for renewal')
