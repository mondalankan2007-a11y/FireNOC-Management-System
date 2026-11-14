from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from applicants.models import Application

from .models import ApplicantProfile, AuditLog, Building, PinCode


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
    Application permits values that Building's constraints reject. Such an
    application must still be saved, and must not be given invented values.
    """

    def setUp(self):
        self.user = User.objects.create_user('applicant2', 'a2@example.com', 'pw')

    def test_zero_floors_leaves_the_building_unlinked(self):
        application = make_application(self.user, num_floors=0)

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 0)
        self.assertIsNone(application.building_id)

    def test_zero_builtup_area_leaves_the_building_unlinked(self):
        application = make_application(self.user, builtup_area=Decimal('0'))

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 0)
        self.assertIsNone(application.building_id)

    def test_blank_pin_code_leaves_the_building_unlinked(self):
        application = make_application(self.user, pin_code='')

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 0)
        self.assertEqual(PinCode.objects.count(), 0)
        self.assertIsNone(application.building_id)

    def test_unusable_application_still_gets_an_applicant_profile(self):
        application = make_application(self.user, num_floors=0)

        application.refresh_from_db()
        self.assertEqual(ApplicantProfile.objects.count(), 1)
        self.assertIsNotNone(application.applicant_profile_id)

    def test_unusable_application_is_still_saved_normally(self):
        application = make_application(self.user, num_floors=0)

        application.refresh_from_db()
        self.assertTrue(application.application_id.startswith('NOC-'))
        self.assertEqual(application.building_name, 'Sunrise Tower')


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
        application = make_application(
            self.user, num_floors='0', builtup_area='0.00')

        application.refresh_from_db()
        self.assertEqual(Building.objects.count(), 0)
        self.assertIsNone(application.building_id)

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
