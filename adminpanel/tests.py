from datetime import date, time
from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from officers.models import Deficiency, Inspection, OfficerProfile

from applicants.models import Application

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
