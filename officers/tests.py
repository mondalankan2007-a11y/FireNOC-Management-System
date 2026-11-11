from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse, resolve
from officers.models import OfficerProfile, create_officer_user
from officers.views import dashboard, officer_login, officer_logout, is_officer


class OfficerAuthenticationAndDashboardTests(TestCase):
    """
    Comprehensive test suite for Commit 2 of the Fire Officer Module:
    - Officer authentication (login, validation, logout, access control)
    - Officer dashboard (protected access, metrics, layout, empty state)
    - Non-regression of Applicant and system routes
    """

    def setUp(self):
        # URLs
        self.officer_login_url = reverse('officers:login')
        self.officer_logout_url = reverse('officers:logout')
        self.officer_home_url = reverse('officers:officer_home')
        self.officer_dashboard_url = reverse('officers:dashboard')
        self.applicant_login_url = reverse('login')
        self.applicant_home_url = reverse('applicants:applicant_home')

        # Test Officer Credentials
        self.officer_password = 'FireSafety#Officer2026'
        self.officer_user, self.officer_profile = create_officer_user(
            username='officer_sharma',
            email='sharma@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-101',
            first_name='Rajesh',
            last_name='Sharma',
            designation='Divisional Fire Inspection Officer',
            badge_number='BADGE-8842',
            phone='9876501234',
        )

        # Test Applicant User (Non-Officer)
        self.applicant_password = 'Applicant#Pass2026'
        self.applicant_user = User.objects.create_user(
            username='applicant_singh',
            email='singh@example.com',
            password=self.applicant_password,
            first_name='Gurpreet',
            last_name='Singh'
        )

    # =========================================================================
    # Part 1: Officer Authentication Tests
    # =========================================================================

    def test_officer_login_page_loads(self):
        """1. Verify Officer login page loads with HTTP 200 and expected elements."""
        response = self.client.get(self.officer_login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'officers/login.html')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'Fire Officer Login')
        self.assertContains(response, 'Officer ID or Official Email')

    def test_invalid_officer_credentials(self):
        """2. Verify submitting invalid credentials shows error message and does not log in."""
        response = self.client.post(self.officer_login_url, {
            'identifier': 'FO-101',
            'password': 'WrongPassword123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid Officer ID / Email or password')
        # Ensure session was not created
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_empty_officer_credentials(self):
        """Verify submitting empty credentials shows validation error."""
        response = self.client.post(self.officer_login_url, {
            'identifier': '',
            'password': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Both Officer ID / Email and password are required')

    def test_valid_officer_login_with_officer_id(self):
        """3a. Verify valid Officer login using Officer ID (e.g. FO-101)."""
        response = self.client.post(self.officer_login_url, {
            'identifier': 'FO-101',
            'password': self.officer_password,
        })
        self.assertRedirects(response, self.officer_home_url)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.officer_user.pk)

    def test_valid_officer_login_with_email(self):
        """3b. Verify valid Officer login using official email."""
        response = self.client.post(self.officer_login_url, {
            'identifier': 'sharma@firenoc.gov.in',
            'password': self.officer_password,
        })
        self.assertRedirects(response, self.officer_home_url)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.officer_user.pk)

    def test_valid_officer_login_with_username(self):
        """3c. Verify valid Officer login using username."""
        response = self.client.post(self.officer_login_url, {
            'identifier': 'officer_sharma',
            'password': self.officer_password,
        })
        self.assertRedirects(response, self.officer_home_url)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.officer_user.pk)

    def test_inactive_officer_account_cannot_login(self):
        """Verify an inactive officer account cannot log in."""
        self.officer_user.is_active = False
        self.officer_user.save()

        response = self.client.post(self.officer_login_url, {
            'identifier': 'FO-101',
            'password': self.officer_password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'deactivated')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_officer_profile_cannot_login(self):
        """Verify an officer with inactive profile is denied access."""
        self.officer_profile.is_active = False
        self.officer_profile.save()

        response = self.client.post(self.officer_login_url, {
            'identifier': 'FO-101',
            'password': self.officer_password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Access denied')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_applicant_cannot_login_at_officer_portal(self):
        """Verify an applicant cannot log in through the officer login portal."""
        response = self.client.post(self.officer_login_url, {
            'identifier': self.applicant_user.email,
            'password': self.applicant_password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Access denied. This account does not have Fire Officer privileges')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_officer_logout_works(self):
        """5. Verify Officer logout clears session and redirects to officer login."""
        self.client.login(username='officer_sharma', password=self.officer_password)
        self.assertIn('_auth_user_id', self.client.session)

        response = self.client.post(self.officer_logout_url)
        self.assertRedirects(response, self.officer_login_url)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_officer_already_logged_in_redirects_from_login_page(self):
        """Verify an already authenticated officer is redirected to dashboard."""
        self.client.login(username='officer_sharma', password=self.officer_password)
        response = self.client.get(self.officer_login_url)
        self.assertRedirects(response, self.officer_home_url)

    def test_next_parameter_redirect(self):
        """Verify safe redirect to next URL after successful login."""
        response = self.client.post(f"{self.officer_login_url}?next=/officer/dashboard/", {
            'identifier': 'FO-101',
            'password': self.officer_password,
        })
        self.assertRedirects(response, '/officer/dashboard/')

    def test_open_redirect_is_prevented(self):
        """Verify malicious external next parameter is ignored."""
        response = self.client.post(f"{self.officer_login_url}?next=https://malicious-site.com", {
            'identifier': 'FO-101',
            'password': self.officer_password,
        })
        self.assertRedirects(response, self.officer_home_url)

    # =========================================================================
    # Part 2: Officer Dashboard Tests
    # =========================================================================

    def test_officer_dashboard_requires_authentication(self):
        """4. Verify unauthenticated user accessing /officer/ is redirected to login."""
        response = self.client.get(self.officer_home_url)
        expected_redirect = f"{self.officer_login_url}?next={self.officer_home_url}"
        self.assertRedirects(response, expected_redirect)

    def test_officer_dashboard_rejects_applicant(self):
        """Verify an authenticated applicant cannot access the officer dashboard."""
        self.client.login(username='applicant_singh', password=self.applicant_password)
        response = self.client.get(self.officer_home_url)
        self.assertRedirects(response, self.officer_login_url)

    def test_officer_dashboard_renders_for_officer(self):
        """8. Verify officer dashboard renders with all statistics and empty state."""
        self.client.login(username='officer_sharma', password=self.officer_password)
        response = self.client.get(self.officer_home_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'officers/officer_home.html')
        self.assertTemplateUsed(response, 'base.html')

        content = response.content.decode('utf-8')

        # Header branding & officer name
        self.assertIn('Rajesh Sharma', content)
        self.assertIn('FO-101', content)
        self.assertIn('Divisional Fire Inspection Officer', content)

        # Minimum required statistics
        self.assertIn('Total Applications', content)
        self.assertIn('Pending Applications', content)
        self.assertIn('Under Verification', content)
        self.assertIn('Scheduled Inspections', content)
        self.assertIn('Completed Inspections', content)

        # Meaningful empty state
        self.assertIn('No applications are currently awaiting officer review.', content)

        # Sidebar navigation items
        self.assertIn('Dashboard', content)
        self.assertIn('Applications', content)
        self.assertIn('Document Verification', content)
        self.assertIn('Inspections', content)
        self.assertIn('Deficiencies', content)
        self.assertIn('Logout', content)

    def test_dashboard_route_alias(self):
        """Verify /officer/dashboard/ works identically to /officer/."""
        self.client.login(username='officer_sharma', password=self.officer_password)
        response = self.client.get(self.officer_dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rajesh Sharma')

    # =========================================================================
    # Non-regression: Applicant Module Tests
    # =========================================================================

    def test_existing_applicant_login_still_works(self):
        """6. Verify existing Applicant login is completely functional."""
        response = self.client.post(self.applicant_login_url, {
            'email': self.applicant_user.email,
            'password': self.applicant_password,
        })
        self.assertRedirects(response, reverse('applicants:dashboard'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.applicant_user.pk)

    def test_existing_applicant_routes_still_work(self):
        """7. Verify applicant routes remain functional."""
        # Unauthenticated access to /applicant/ redirects to applicant login
        response = self.client.get(self.applicant_home_url)
        self.assertRedirects(response, f"{self.applicant_login_url}?next={self.applicant_home_url}")

        # Authenticated applicant access to dashboard
        self.client.login(username='applicant_singh', password=self.applicant_password)
        resp_dash = self.client.get(reverse('applicants:dashboard'))
        self.assertEqual(resp_dash.status_code, 200)

    # =========================================================================
    # URL and Model Integrity Tests
    # =========================================================================

    def test_no_url_conflicts_exist(self):
        """9. Verify URL resolution for all officer and applicant routes."""
        self.assertEqual(resolve('/officer/').func, dashboard)
        self.assertEqual(resolve('/officer/dashboard/').func, dashboard)
        self.assertEqual(resolve('/officer/login/').func, officer_login)
        self.assertEqual(resolve('/officer/logout/').func, officer_logout)

    def test_officer_profile_str(self):
        """Verify string representation of OfficerProfile."""
        expected = "Rajesh Sharma (FO-101)"
        self.assertEqual(str(self.officer_profile), expected)

    def test_is_officer_helper(self):
        """Verify is_officer helper accuracy."""
        self.assertTrue(is_officer(self.officer_user))
        self.assertFalse(is_officer(self.applicant_user))
        self.assertFalse(is_officer(None))


# ===========================================================================
# Commit 3 Tests: Application Queue, Document Verification, Application Review
# ===========================================================================
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from applicants.models import Application, ApplicationDocument
from officers.models import DocumentVerification, ApplicationReview
from officers.views import application_list, application_detail, document_verify, application_review


class OfficerApplicationVerificationTests(TestCase):
    """
    Test suite for Commit 3 of the Fire Officer Module.
    Covers:
    - Officer application queue access and authentication
    - Application detail page
    - Document verification (approve / reject)
    - Application review workflow
    - Dashboard statistics backed by real database records
    - Non-officer access denial
    - Non-regression of Applicant routes
    """

    def setUp(self):
        # --- URLs ---
        self.officer_login_url = reverse('officers:login')
        self.officer_home_url = reverse('officers:officer_home')
        self.application_list_url = reverse('officers:application_list')
        self.applicant_home_url = reverse('applicants:applicant_home')
        self.applicant_login_url = reverse('login')

        # --- Officer credentials ---
        self.officer_password = 'FireOfficer#2026Commit3'
        self.officer_user, self.officer_profile = create_officer_user(
            username='officer_commit3',
            email='commit3@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-C3-001',
            first_name='Priya',
            last_name='Nair',
            designation='Senior Fire Inspection Officer',
        )

        # --- Applicant user (non-officer) ---
        self.applicant_password = 'ApplicantPass#Commit3'
        self.applicant_user = User.objects.create_user(
            username='applicant_c3',
            email='applicant3@example.com',
            password=self.applicant_password,
            first_name='Ravi',
            last_name='Kumar',
        )

        # --- Sample Application ---
        self.application = Application.objects.create(
            applicant=self.applicant_user,
            full_name='Ravi Kumar',
            email='applicant3@example.com',
            mobile_number='9876543210',
            building_name='Sunrise Towers',
            building_type='COMMERCIAL',
            building_address='12 MG Road',
            city='Bengaluru',
            state='Karnataka',
            pin_code='560001',
            num_floors=5,
            builtup_area='2500.00',
            year_construction=2015,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Apply for Fire NOC for commercial office building.',
            status='PENDING',
        )

        # --- Sample Document (with an in-memory file) ---
        fake_file = SimpleUploadedFile(
            name='blueprint.pdf',
            content=b'%PDF-1.4 fake pdf content',
            content_type='application/pdf',
        )
        self.document = ApplicationDocument.objects.create(
            application=self.application,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Architectural Blueprint',
            file=fake_file,
        )

    # =========================================================================
    # Test 1: Application list requires authentication
    # =========================================================================

    def test_application_list_requires_authentication(self):
        """1. Unauthenticated access to /officer/applications/ redirects to login."""
        response = self.client.get(self.application_list_url)
        expected_redirect = f"{self.officer_login_url}?next={self.application_list_url}"
        self.assertRedirects(response, expected_redirect)

    # =========================================================================
    # Test 2: Officer can access application list
    # =========================================================================

    def test_officer_can_access_application_list(self):
        """2. Authenticated officer gets HTTP 200 on application list page."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        response = self.client.get(self.application_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'officers/application_list.html')
        # The created application should be visible
        self.assertContains(response, self.application.application_id)
        self.assertContains(response, 'Sunrise Towers')

    # =========================================================================
    # Test 3: Applicant / non-officer cannot access application list
    # =========================================================================

    def test_applicant_cannot_access_application_list(self):
        """3. Authenticated applicant is denied access to officer application list."""
        self.client.login(username='applicant_c3', password=self.applicant_password)
        response = self.client.get(self.application_list_url)
        self.assertRedirects(response, self.officer_login_url)

    # =========================================================================
    # Test 4: Application detail page loads for valid application
    # =========================================================================

    def test_application_detail_loads_for_officer(self):
        """4. Application detail page returns HTTP 200 for a valid application."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:application_detail', args=[self.application.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'officers/application_detail.html')
        # All 6 sections should be present
        content = response.content.decode('utf-8')
        self.assertIn('Applicant Information', content)
        self.assertIn('Building Information', content)
        self.assertIn('Application Information', content)
        self.assertIn('Documents', content)
        self.assertIn('Verification Status', content)
        self.assertIn('Officer Actions', content)
        # Applicant data shown correctly
        self.assertIn('Ravi Kumar', content)
        self.assertIn('Sunrise Towers', content)
        self.assertIn('Architectural Blueprint', content)

    # =========================================================================
    # Test 5: Invalid application ID returns 404
    # =========================================================================

    def test_application_detail_returns_404_for_invalid_id(self):
        """5. Application detail page returns HTTP 404 for a non-existent application."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:application_detail', args=[999999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    # =========================================================================
    # Test 6: Existing applicant routes still work (non-regression)
    # =========================================================================

    def test_existing_applicant_routes_still_work(self):
        """6. Existing Applicant module routes remain functional after Commit 3."""
        # Applicant login page loads
        response = self.client.get(self.applicant_login_url)
        self.assertEqual(response.status_code, 200)

        # Unauthenticated applicant home redirects to login
        response = self.client.get(self.applicant_home_url)
        self.assertRedirects(response, f"{self.applicant_login_url}?next={self.applicant_home_url}")

        # Authenticated applicant can access dashboard
        self.client.login(username='applicant_c3', password=self.applicant_password)
        response = self.client.get(reverse('applicants:dashboard'))
        self.assertEqual(response.status_code, 200)

    # =========================================================================
    # Test 7: Document verification — VERIFY action
    # =========================================================================

    def test_document_verify_action_sets_verified_status(self):
        """7. POST with action=VERIFY updates document verification status to VERIFIED."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])
        response = self.client.post(url, {
            'action': 'VERIFY',
            'officer_remarks': 'Blueprint is complete and compliant.',
        })
        self.assertRedirects(response, reverse('officers:application_detail', args=[self.application.pk]))

        self.document.refresh_from_db()
        verification = DocumentVerification.objects.get(document=self.document)
        self.assertEqual(verification.status, 'VERIFIED')
        self.assertEqual(verification.officer_remarks, 'Blueprint is complete and compliant.')
        self.assertEqual(verification.verified_by, self.officer_user)

    # =========================================================================
    # Test 8: Document rejection — REJECT action preserves file
    # =========================================================================

    def test_document_reject_action_sets_rejected_status_and_preserves_file(self):
        """8. POST with action=REJECT updates status to REJECTED and does not delete the file."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])

        file_name_before = self.document.file.name

        response = self.client.post(url, {
            'action': 'REJECT',
            'officer_remarks': 'Missing fire exit markings on blueprint.',
        })
        self.assertRedirects(response, reverse('officers:application_detail', args=[self.application.pk]))

        self.document.refresh_from_db()
        verification = DocumentVerification.objects.get(document=self.document)
        self.assertEqual(verification.status, 'REJECTED')
        self.assertEqual(verification.officer_remarks, 'Missing fire exit markings on blueprint.')

        # File must NOT be deleted
        self.assertEqual(self.document.file.name, file_name_before)
        self.assertTrue(bool(self.document.file))

    # =========================================================================
    # Test 9: Officer remarks are saved and reflected
    # =========================================================================

    def test_officer_remarks_are_saved_and_shown(self):
        """9. Officer remarks entered during document verification are persisted."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])
        self.client.post(url, {
            'action': 'VERIFY',
            'officer_remarks': 'Fire extinguisher layout confirmed as per NBC 2016.',
        })
        verification = DocumentVerification.objects.get(document=self.document)
        self.assertEqual(verification.officer_remarks, 'Fire extinguisher layout confirmed as per NBC 2016.')

        # The remark should also appear on the detail page
        detail_url = reverse('officers:application_detail', args=[self.application.pk])
        response = self.client.get(detail_url)
        self.assertContains(response, 'Fire extinguisher layout confirmed as per NBC 2016.')

    # =========================================================================
    # Test 10: Application review — status transitions
    # =========================================================================

    def test_application_review_updates_status_to_under_review(self):
        """10a. POST with verification_status=UNDER_REVIEW transitions application correctly."""
        self.client.login(username='officer_commit3', password=self.officer_password)
        url = reverse('officers:application_review', args=[self.application.pk])
        response = self.client.post(url, {
            'verification_status': 'UNDER_REVIEW',
            'officer_remarks': 'Initial desk audit commenced.',
        })
        self.assertRedirects(response, reverse('officers:application_detail', args=[self.application.pk]))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'UNDER_REVIEW')

        review = ApplicationReview.objects.get(application=self.application)
        self.assertEqual(review.status, 'UNDER_REVIEW')
        self.assertEqual(review.officer_remarks, 'Initial desk audit commenced.')
        self.assertEqual(review.reviewed_by, self.officer_user)

    def test_application_review_updates_status_to_documents_verified(self):
        """10b. POST with verification_status=DOCUMENTS_VERIFIED transitions application correctly."""
        self.client.login(username='officer_commit3', password=self.officer_password)

        # First verify the document so no rejected docs block the transition
        verify_url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])
        self.client.post(verify_url, {'action': 'VERIFY', 'officer_remarks': 'All clear.'})

        # Now mark the application as Documents Verified
        url = reverse('officers:application_review', args=[self.application.pk])
        response = self.client.post(url, {
            'verification_status': 'DOCUMENTS_VERIFIED',
            'officer_remarks': 'All documents verified, ready for site inspection.',
        })
        self.assertRedirects(response, reverse('officers:application_detail', args=[self.application.pk]))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'DOCUMENTS_VERIFIED')

    def test_cannot_set_documents_verified_when_docs_rejected(self):
        """10c. DOCUMENTS_VERIFIED is blocked when a rejected document exists."""
        self.client.login(username='officer_commit3', password=self.officer_password)

        # Reject the document first
        reject_url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])
        self.client.post(reject_url, {'action': 'REJECT', 'officer_remarks': 'Missing info.'})

        # Attempt to mark Documents Verified — should be blocked
        review_url = reverse('officers:application_review', args=[self.application.pk])
        response = self.client.post(review_url, {
            'verification_status': 'DOCUMENTS_VERIFIED',
            'officer_remarks': 'Trying to mark verified despite rejected docs.',
        })
        self.assertRedirects(response, reverse('officers:application_detail', args=[self.application.pk]))

        self.application.refresh_from_db()
        # Status must NOT have changed to DOCUMENTS_VERIFIED
        self.assertNotEqual(self.application.status, 'DOCUMENTS_VERIFIED')

    # =========================================================================
    # Test 11: Dashboard statistics reflect database state
    # =========================================================================

    def test_dashboard_statistics_reflect_database_state(self):
        """11. Dashboard stats (total, pending, under_verification) reflect actual DB records."""
        self.client.login(username='officer_commit3', password=self.officer_password)

        # Create a second application in UNDER_REVIEW state
        Application.objects.create(
            applicant=self.applicant_user,
            full_name='Another Applicant',
            email='another@example.com',
            mobile_number='9999999999',
            building_name='City Mall',
            building_type='COMMERCIAL',
            building_address='45 Brigade Road',
            city='Bengaluru',
            state='Karnataka',
            pin_code='560025',
            num_floors=8,
            builtup_area='5000.00',
            year_construction=2010,
            occupancy_type='ASSEMBLY',
            application_type='RENEWAL',
            purpose='NOC renewal for shopping mall.',
            status='UNDER_REVIEW',
        )

        response = self.client.get(self.officer_home_url)
        self.assertEqual(response.status_code, 200)

        stats = response.context['stats']
        self.assertEqual(stats['total_applications'], 2)
        # First app is PENDING
        self.assertGreaterEqual(stats['pending_applications'], 1)
        # Second app is UNDER_REVIEW
        self.assertGreaterEqual(stats['applications_under_verification'], 1)

    # =========================================================================
    # Test 12: Non-officer cannot perform verification or review actions
    # =========================================================================

    def test_non_officer_cannot_verify_documents(self):
        """12a. Applicant cannot POST to document_verify endpoint."""
        self.client.login(username='applicant_c3', password=self.applicant_password)
        url = reverse('officers:document_verify', args=[self.application.pk, self.document.pk])
        response = self.client.post(url, {
            'action': 'VERIFY',
            'officer_remarks': 'Attempting to verify as applicant.',
        })
        # Must redirect to officer login (access denied)
        self.assertRedirects(response, self.officer_login_url)

        # Verification status must remain untouched (no verification record or PENDING)
        verification_exists = DocumentVerification.objects.filter(document=self.document).exists()
        if verification_exists:
            verification = DocumentVerification.objects.get(document=self.document)
            self.assertNotEqual(verification.status, 'VERIFIED')

    def test_non_officer_cannot_submit_application_review(self):
        """12b. Applicant cannot POST to application_review endpoint."""
        self.client.login(username='applicant_c3', password=self.applicant_password)
        url = reverse('officers:application_review', args=[self.application.pk])
        response = self.client.post(url, {
            'verification_status': 'UNDER_REVIEW',
            'officer_remarks': 'Applicant trying to review their own application.',
        })
        self.assertRedirects(response, self.officer_login_url)

        self.application.refresh_from_db()
        # Status must remain PENDING — not changed by the applicant
        self.assertEqual(self.application.status, 'PENDING')


# ===========================================================================
# Commit 4 Tests: Inspection Management, Checklist, Report, State Machine
# ===========================================================================
import datetime
from django.utils import timezone
from officers.models import Inspection, InspectionChecklistItem, InspectionReport


class OfficerInspectionManagementTests(TestCase):
    """
    Comprehensive test suite for Commit 4 of the Fire Officer Module:
    - Inspection, InspectionChecklistItem, InspectionReport models
    - Officer authentication & access control
    - Inspection scheduling & validation
    - Inspection queue & detail views
    - Inspection state machine (Scheduled -> In Progress -> Completed / Cancelled)
    - Fire safety checklist editing & lock upon completion
    - Inspection report submission & result choices
    - Ownership enforcement & dashboard/application-detail integration
    """

    def setUp(self):
        self.officer_login_url = reverse('officers:login')
        self.officer_home_url = reverse('officers:officer_home')
        self.inspection_list_url = reverse('officers:inspection_list')

        self.officer_password = 'FireOfficer#2026Commit4'
        self.officer_user, self.officer_profile = create_officer_user(
            username='officer_commit4',
            email='commit4@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-C4-001',
            first_name='Vikram',
            last_name='Rao',
            designation='Chief Fire Inspector',
        )

        self.other_officer_user, self.other_officer_profile = create_officer_user(
            username='officer_other4',
            email='other4@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-C4-002',
            first_name='Meera',
            last_name='Iyer',
        )

        self.applicant_password = 'ApplicantPass#Commit4'
        self.applicant_user = User.objects.create_user(
            username='applicant_c4',
            email='applicant4@example.com',
            password=self.applicant_password,
            first_name='Anil',
            last_name='Desai',
        )

        self.eligible_app = Application.objects.create(
            applicant=self.applicant_user,
            full_name='Anil Desai',
            email='applicant4@example.com',
            mobile_number='9876543211',
            building_name='Horizon Plaza',
            building_type='COMMERCIAL',
            building_address='100 Anna Salai',
            city='Chennai',
            state='Tamil Nadu',
            pin_code='600002',
            num_floors=6,
            builtup_area='3200.00',
            year_construction=2018,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='New Fire NOC for commercial complex.',
            status='DOCUMENTS_VERIFIED',
        )

        self.pending_app = Application.objects.create(
            applicant=self.applicant_user,
            full_name='Anil Desai',
            email='applicant4@example.com',
            mobile_number='9876543211',
            building_name='Green Apartments',
            building_type='RESIDENTIAL',
            building_address='22 Besant Nagar',
            city='Chennai',
            state='Tamil Nadu',
            pin_code='600090',
            num_floors=4,
            builtup_area='1800.00',
            year_construction=2020,
            occupancy_type='RESIDENTIAL',
            application_type='NEW_NOC',
            purpose='Residential NOC.',
            status='PENDING',
        )

        self.future_date = (timezone.localdate() + datetime.timedelta(days=3)).isoformat()
        self.past_date = (timezone.localdate() - datetime.timedelta(days=2)).isoformat()

    def _schedule_sample_inspection(self, app=None, officer=None, status=Inspection.STATUS_SCHEDULED):
        return Inspection.objects.create(
            application=app or self.eligible_app,
            officer=officer or self.officer_user,
            scheduled_date=timezone.localdate() + datetime.timedelta(days=2),
            scheduled_time=datetime.time(10, 30),
            location='100 Anna Salai, Chennai',
            status=status,
            officer_remarks='Initial inspection scheduled.',
        )

    # =========================================================================
    # Model Tests
    # =========================================================================

    def test_inspection_model_creation_and_choices(self):
        """Model: Inspection creates properly and exposes expected status choices."""
        insp = self._schedule_sample_inspection()
        self.assertEqual(insp.status, Inspection.STATUS_SCHEDULED)
        self.assertEqual(insp.get_status_display(), 'Scheduled')
        choices = dict(Inspection.STATUS_CHOICES)
        self.assertEqual(set(choices.values()), {'Scheduled', 'In Progress', 'Completed', 'Cancelled'})
        self.assertIn(self.eligible_app.application_id, str(insp))

    def test_checklist_and_report_model_creation(self):
        """Model: InspectionChecklistItem and InspectionReport create properly."""
        insp = self._schedule_sample_inspection(status=Inspection.STATUS_IN_PROGRESS)
        item = InspectionChecklistItem.objects.create(
            inspection=insp,
            item_type='EXTINGUISHER_AVAILABLE',
            status=InspectionChecklistItem.STATUS_COMPLIANT,
            remarks='CO2 and ABC extinguishers installed on every floor.',
        )
        self.assertEqual(item.get_status_display(), 'Compliant')

        report = InspectionReport.objects.create(
            inspection=insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='All fire safety provisions verified.',
            officer_remarks='Recommended for next stage.',
            completed_at=timezone.now(),
        )
        self.assertEqual(report.get_overall_result_display(), 'Satisfactory')
        self.assertEqual(insp.report, report)

    # =========================================================================
    # Authentication & Access Control
    # =========================================================================

    def test_unauthenticated_user_cannot_access_inspections(self):
        """Auth: Unauthenticated access to inspection routes redirects to officer login."""
        insp = self._schedule_sample_inspection()
        for url in [
            self.inspection_list_url,
            reverse('officers:schedule_inspection', args=[self.eligible_app.pk]),
            reverse('officers:inspection_detail', args=[insp.pk]),
        ]:
            resp = self.client.get(url)
            self.assertRedirects(resp, f"{self.officer_login_url}?next={url}")

    def test_non_officer_cannot_access_inspections(self):
        """Auth: Authenticated applicant is denied access to inspection routes."""
        self.client.login(username='applicant_c4', password=self.applicant_password)
        insp = self._schedule_sample_inspection()

        resp_list = self.client.get(self.inspection_list_url)
        self.assertRedirects(resp_list, self.officer_login_url)

        resp_start = self.client.post(reverse('officers:inspection_start', args=[insp.pk]))
        self.assertRedirects(resp_start, self.officer_login_url)
        insp.refresh_from_db()
        self.assertEqual(insp.status, Inspection.STATUS_SCHEDULED)

    # =========================================================================
    # Scheduling Tests
    # =========================================================================

    def test_officer_can_schedule_valid_inspection(self):
        """Scheduling: Officer schedules valid inspection; officer auto-assigned; app updated."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        url = reverse('officers:schedule_inspection', args=[self.eligible_app.pk])

        # Also attempt to spoof officer ID in POST — must be ignored
        resp = self.client.post(url, {
            'scheduled_date': self.future_date,
            'scheduled_time': '11:00',
            'location': '100 Anna Salai Main Gate',
            'officer_remarks': 'Check hydrant pressure and alarms.',
            'officer': self.other_officer_user.pk,
        })
        insp = Inspection.objects.get(application=self.eligible_app)
        self.assertRedirects(resp, reverse('officers:inspection_detail', args=[insp.pk]))
        self.assertEqual(insp.officer, self.officer_user)
        self.assertNotEqual(insp.officer, self.other_officer_user)
        self.assertEqual(insp.status, Inspection.STATUS_SCHEDULED)
        self.assertEqual(insp.checklist_items.count(), 12)

        self.eligible_app.refresh_from_db()
        self.assertEqual(self.eligible_app.status, 'UNDER_INSPECTION')

    def test_get_schedule_does_not_create_inspection(self):
        """Scheduling: GET request renders form without modifying database."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        url = reverse('officers:schedule_inspection', args=[self.eligible_app.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Inspection.objects.count(), 0)

    def test_ineligible_or_invalid_application_cannot_be_scheduled(self):
        """Scheduling: Pending/non-existent applications cannot be scheduled."""
        self.client.login(username='officer_commit4', password=self.officer_password)

        # Non-existent application
        resp_404 = self.client.post(
            reverse('officers:schedule_inspection', args=[999999]),
            {'scheduled_date': self.future_date, 'scheduled_time': '10:00'}
        )
        self.assertEqual(resp_404.status_code, 404)

        # PENDING application
        resp_pending = self.client.post(
            reverse('officers:schedule_inspection', args=[self.pending_app.pk]),
            {'scheduled_date': self.future_date, 'scheduled_time': '10:00'}
        )
        self.assertRedirects(resp_pending, reverse('officers:application_detail', args=[self.pending_app.pk]))
        self.assertEqual(Inspection.objects.filter(application=self.pending_app).count(), 0)

    def test_past_inspection_cannot_be_scheduled(self):
        """Scheduling: Past inspection date or past time today is rejected."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        url = reverse('officers:schedule_inspection', args=[self.eligible_app.pk])
        resp = self.client.post(url, {
            'scheduled_date': self.past_date,
            'scheduled_time': '10:00',
            'location': '100 Anna Salai',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'cannot be in the past')
        self.assertEqual(Inspection.objects.count(), 0)

        # Past time today
        past_dt = timezone.localtime() - datetime.timedelta(minutes=30)
        if past_dt.date() == timezone.localdate():
            resp_time = self.client.post(url, {
                'scheduled_date': timezone.localdate().isoformat(),
                'scheduled_time': past_dt.time().strftime('%H:%M'),
                'location': '100 Anna Salai',
            })
            self.assertEqual(resp_time.status_code, 200)
            self.assertContains(resp_time, 'cannot be in the past')
            self.assertEqual(Inspection.objects.count(), 0)

    # =========================================================================
    # List & Detail Views
    # =========================================================================

    def test_inspection_list_and_filter(self):
        """List: Officer sees inspections and can filter by status."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        insp_sched = self._schedule_sample_inspection(status=Inspection.STATUS_SCHEDULED)
        insp_comp = self._schedule_sample_inspection(app=self.pending_app, status=Inspection.STATUS_COMPLETED)

        resp_all = self.client.get(self.inspection_list_url)
        self.assertEqual(resp_all.status_code, 200)
        self.assertContains(resp_all, 'Horizon Plaza')
        self.assertContains(resp_all, 'Green Apartments')

        resp_comp = self.client.get(f"{self.inspection_list_url}?status=COMPLETED")
        self.assertEqual(resp_comp.status_code, 200)
        self.assertContains(resp_comp, 'Green Apartments')
        self.assertNotContains(resp_comp, 'Horizon Plaza')
        self.assertEqual(insp_sched.status, Inspection.STATUS_SCHEDULED)
        self.assertEqual(insp_comp.status, Inspection.STATUS_COMPLETED)

    def test_inspection_detail_view(self):
        """Detail: Officer views full inspection details and 12 checklist items."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        insp = self._schedule_sample_inspection()
        resp = self.client.get(reverse('officers:inspection_detail', args=[insp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'officers/inspection_detail.html')
        self.assertContains(resp, 'Horizon Plaza')
        self.assertContains(resp, 'Fire extinguishers available')
        self.assertContains(resp, 'Start Inspection')

    # =========================================================================
    # State Machine Transitions
    # =========================================================================

    def test_valid_state_transitions(self):
        """State machine: Scheduled -> In Progress -> Completed, and Scheduled -> Cancelled."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        insp = self._schedule_sample_inspection()

        # Start
        self.client.post(reverse('officers:inspection_start', args=[insp.pk]))
        insp.refresh_from_db()
        self.assertEqual(insp.status, Inspection.STATUS_IN_PROGRESS)
        self.assertIsNotNone(insp.started_at)

        # Complete with report
        self.client.post(reverse('officers:inspection_complete', args=[insp.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': 'Building meets all fire norms.',
            'officer_remarks': 'Ready for next step.',
        })
        insp.refresh_from_db()
        self.assertEqual(insp.status, Inspection.STATUS_COMPLETED)
        self.assertIsNotNone(insp.completed_at)

        # Cancel from Scheduled on another inspection
        insp2 = self._schedule_sample_inspection(app=self.pending_app)
        self.client.post(reverse('officers:inspection_cancel', args=[insp2.pk]), {
            'cancel_reason': 'Applicant requested reschedule.',
        })
        insp2.refresh_from_db()
        self.assertEqual(insp2.status, Inspection.STATUS_CANCELLED)
        self.assertIn('Applicant requested reschedule.', insp2.officer_remarks)

    def test_invalid_state_transitions_rejected(self):
        """State machine: Invalid transitions (e.g. Completed->Start, Cancelled->Complete) blocked."""
        self.client.login(username='officer_commit4', password=self.officer_password)

        # Scheduled -> Completed directly must fail
        insp_sched = self._schedule_sample_inspection()
        self.client.post(reverse('officers:inspection_complete', args=[insp_sched.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': 'Trying to skip start.',
        })
        insp_sched.refresh_from_db()
        self.assertEqual(insp_sched.status, Inspection.STATUS_SCHEDULED)

        # Completed -> Start or Cancel must fail
        insp_comp = self._schedule_sample_inspection(app=self.pending_app, status=Inspection.STATUS_COMPLETED)
        self.client.post(reverse('officers:inspection_start', args=[insp_comp.pk]))
        insp_comp.refresh_from_db()
        self.assertEqual(insp_comp.status, Inspection.STATUS_COMPLETED)
        self.client.post(reverse('officers:inspection_cancel', args=[insp_comp.pk]))
        insp_comp.refresh_from_db()
        self.assertEqual(insp_comp.status, Inspection.STATUS_COMPLETED)

        # Cancelled -> Start or Complete must fail
        insp_canc = self._schedule_sample_inspection(status=Inspection.STATUS_CANCELLED)
        self.client.post(reverse('officers:inspection_start', args=[insp_canc.pk]))
        insp_canc.refresh_from_db()
        self.assertEqual(insp_canc.status, Inspection.STATUS_CANCELLED)
        self.client.post(reverse('officers:inspection_complete', args=[insp_canc.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': 'Trying to complete cancelled.',
        })
        insp_canc.refresh_from_db()
        self.assertEqual(insp_canc.status, Inspection.STATUS_CANCELLED)

    # =========================================================================
    # Checklist & Report Tests
    # =========================================================================

    def test_checklist_editable_in_progress_and_locked_when_completed(self):
        """Checklist: Editable during In Progress (all 3 statuses); read-only when Completed."""
        self.client.login(username='officer_commit4', password=self.officer_password)
        insp = self._schedule_sample_inspection(status=Inspection.STATUS_IN_PROGRESS)
        save_url = reverse('officers:inspection_checklist_save', args=[insp.pk])

        self.client.post(save_url, {
            'checklist_EXTINGUISHER_AVAILABLE_status': InspectionChecklistItem.STATUS_COMPLIANT,
            'checklist_EXTINGUISHER_AVAILABLE_remarks': 'Checked 12 units.',
            'checklist_ALARM_FUNCTIONAL_status': InspectionChecklistItem.STATUS_NON_COMPLIANT,
            'checklist_ALARM_FUNCTIONAL_remarks': 'Panel battery dead.',
            'checklist_HYDRANT_WATER_status': InspectionChecklistItem.STATUS_NOT_APPLICABLE,
        })

        ext_item = insp.checklist_items.get(item_type='EXTINGUISHER_AVAILABLE')
        alarm_item = insp.checklist_items.get(item_type='ALARM_FUNCTIONAL')
        hyd_item = insp.checklist_items.get(item_type='HYDRANT_WATER')
        self.assertEqual(ext_item.status, InspectionChecklistItem.STATUS_COMPLIANT)
        self.assertEqual(ext_item.remarks, 'Checked 12 units.')
        self.assertEqual(alarm_item.status, InspectionChecklistItem.STATUS_NON_COMPLIANT)
        self.assertEqual(hyd_item.status, InspectionChecklistItem.STATUS_NOT_APPLICABLE)

        # Complete inspection
        self.client.post(reverse('officers:inspection_complete', args=[insp.pk]), {
            'overall_result': InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            'general_observations': 'Alarm panel battery requires replacement.',
        })
        insp.refresh_from_db()
        self.assertEqual(insp.status, Inspection.STATUS_COMPLETED)

        # Attempt to modify checklist after completion — must be ignored
        self.client.post(save_url, {
            'checklist_ALARM_FUNCTIONAL_status': InspectionChecklistItem.STATUS_COMPLIANT,
            'checklist_ALARM_FUNCTIONAL_remarks': 'Tampered after completion',
        })
        alarm_item.refresh_from_db()
        self.assertEqual(alarm_item.status, InspectionChecklistItem.STATUS_NON_COMPLIANT)
        self.assertEqual(alarm_item.remarks, 'Panel battery dead.')

    def test_report_results_and_required_fields_validation(self):
        """Report: Satisfactory, Unsatisfactory, Requires Rectification work; missing fields blocked."""
        self.client.login(username='officer_commit4', password=self.officer_password)

        # Missing general_observations fails to complete
        insp1 = self._schedule_sample_inspection(status=Inspection.STATUS_IN_PROGRESS)
        self.client.post(reverse('officers:inspection_complete', args=[insp1.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': '',
        })
        insp1.refresh_from_db()
        self.assertEqual(insp1.status, Inspection.STATUS_IN_PROGRESS)

        # Unsatisfactory works
        self.client.post(reverse('officers:inspection_complete', args=[insp1.pk]), {
            'overall_result': InspectionReport.RESULT_UNSATISFACTORY,
            'general_observations': 'Major safety exits locked.',
        })
        insp1.refresh_from_db()
        self.assertEqual(insp1.status, Inspection.STATUS_COMPLETED)
        self.assertEqual(insp1.report.overall_result, InspectionReport.RESULT_UNSATISFACTORY)

    # =========================================================================
    # Security / Ownership & Integration Tests
    # =========================================================================

    def test_other_officer_cannot_modify_assigned_inspection(self):
        """Security: Another officer cannot start/edit/complete/cancel an assigned inspection."""
        insp = self._schedule_sample_inspection(officer=self.officer_user, status=Inspection.STATUS_SCHEDULED)

        self.client.login(username='officer_other4', password=self.officer_password)
        self.client.post(reverse('officers:inspection_start', args=[insp.pk]))
        insp.refresh_from_db()
        self.assertEqual(insp.status, Inspection.STATUS_SCHEDULED)

    def test_dashboard_stats_and_application_detail_integration(self):
        """Integration: Dashboard inspection counts and application detail inspection card reflect DB."""
        self.client.login(username='officer_commit4', password=self.officer_password)

        # Before scheduling: application detail shows Schedule Inspection link
        app_detail_url = reverse('officers:application_detail', args=[self.eligible_app.pk])
        resp_before = self.client.get(app_detail_url)
        self.assertContains(resp_before, 'Schedule Inspection')

        # Schedule 1 + complete 1
        insp_sched = self._schedule_sample_inspection(status=Inspection.STATUS_SCHEDULED)
        self._schedule_sample_inspection(app=self.pending_app, status=Inspection.STATUS_COMPLETED)

        # Application detail now shows View Inspection
        resp_after = self.client.get(app_detail_url)
        self.assertContains(resp_after, 'View Inspection')
        self.assertContains(resp_after, reverse('officers:inspection_detail', args=[insp_sched.pk]))

        # Dashboard counts match DB
        resp_dash = self.client.get(self.officer_home_url)
        self.assertEqual(resp_dash.status_code, 200)
        self.assertEqual(resp_dash.context['stats']['scheduled_inspections'], 1)
        self.assertEqual(resp_dash.context['stats']['completed_inspections'], 1)
        self.assertContains(resp_dash, 'Upcoming Inspections')
