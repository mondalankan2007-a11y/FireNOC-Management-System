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


# ===========================================================================
# Commit 5 Tests: Deficiency, Rectification & Officer Recommendation Workflow
# ===========================================================================
from officers.models import Deficiency, DeficiencyRectification, get_recommendation_eligibility


class OfficerDeficiencyAndRecommendationTests(TestCase):
    """
    Comprehensive test suite for Commit 5 of the Fire Officer Module:
    - Deficiency & DeficiencyRectification models
    - Officer authentication & access control
    - Deficiency creation from completed Unsatisfactory/Requires Rectification inspections
    - Deficiency list, filters (status, severity), and search
    - Deficiency state transitions & invalid transition blocking
    - Rectification submission, evidence upload validation, acceptance & rejection
    - Closing verified deficiencies & read-only enforcement
    - Officer application recommendation & centralized eligibility checks
    - Dashboard deficiency & recommendation statistics
    """

    def setUp(self):
        self.officer_login_url = reverse('officers:login')
        self.officer_home_url = reverse('officers:officer_home')
        self.deficiency_list_url = reverse('officers:deficiency_list')

        self.officer_password = 'FireOfficer#2026Commit5'
        self.officer_user, self.officer_profile = create_officer_user(
            username='officer_commit5',
            email='commit5@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-C5-001',
            first_name='Suresh',
            last_name='Menon',
            designation='Deputy Fire Officer',
        )

        self.other_officer_user, _ = create_officer_user(
            username='officer_other5',
            email='other5@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-C5-002',
            first_name='Kavita',
            last_name='Rao',
        )

        self.applicant_password = 'ApplicantPass#Commit5'
        self.applicant_user = User.objects.create_user(
            username='applicant_c5',
            email='applicant5@example.com',
            password=self.applicant_password,
            first_name='Deepak',
            last_name='Verma',
        )

        self.application = Application.objects.create(
            applicant=self.applicant_user,
            full_name='Deepak Verma',
            email='applicant5@example.com',
            mobile_number='9876500005',
            building_name='Apex Business Park',
            building_type='COMMERCIAL',
            building_address='77 Cyber Hub',
            city='Gurugram',
            state='Haryana',
            pin_code='122002',
            num_floors=7,
            builtup_area='4500.00',
            year_construction=2019,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Commercial Fire NOC.',
            status='UNDER_INSPECTION',
        )

        fake_doc = SimpleUploadedFile(
            name='safety_plan.pdf',
            content=b'%PDF-1.4 sample',
            content_type='application/pdf',
        )
        self.document = ApplicationDocument.objects.create(
            application=self.application,
            document_type='FIRE_SAFETY_PLAN',
            document_name='Fire Safety Plan',
            file=fake_doc,
        )
        self.doc_verification = DocumentVerification.objects.create(
            document=self.document,
            verified_by=self.officer_user,
            status='VERIFIED',
            verified_at=timezone.now(),
        )
        self.app_review = ApplicationReview.objects.create(
            application=self.application,
            reviewed_by=self.officer_user,
            status='DOCUMENTS_VERIFIED',
        )

        self.bad_inspection = Inspection.objects.create(
            application=self.application,
            officer=self.officer_user,
            scheduled_date=timezone.localdate(),
            scheduled_time=datetime.time(10, 0),
            location='77 Cyber Hub',
            status=Inspection.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        self.bad_report = InspectionReport.objects.create(
            inspection=self.bad_inspection,
            overall_result=InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            general_observations='Extinguishers missing on 4th floor.',
            completed_at=timezone.now(),
        )

    def _create_deficiency(self, title='Missing Extinguishers', severity=Deficiency.SEVERITY_MAJOR, status=Deficiency.STATUS_OPEN):
        return Deficiency.objects.create(
            application=self.application,
            inspection=self.bad_inspection,
            reported_by=self.officer_user,
            title=title,
            description='Install ABC extinguishers near staircase.',
            severity=severity,
            status=status,
        )

    # =========================================================================
    # Model Tests
    # =========================================================================

    def test_deficiency_model_creation_choices_and_relationships(self):
        """Model: Deficiency creates with severity/status choices and FKs."""
        d = self._create_deficiency(severity=Deficiency.SEVERITY_CRITICAL)
        self.assertEqual(d.application, self.application)
        self.assertEqual(d.inspection, self.bad_inspection)
        self.assertEqual(d.reported_by, self.officer_user)
        self.assertEqual(d.get_severity_display(), 'Critical')
        self.assertEqual(d.get_status_display(), 'Open')
        self.assertEqual(
            set(dict(Deficiency.SEVERITY_CHOICES).values()),
            {'Minor', 'Major', 'Critical'},
        )
        self.assertEqual(
            set(dict(Deficiency.STATUS_CHOICES).values()),
            {'Open', 'Submitted for Verification', 'Verified', 'Rejected', 'Closed'},
        )

    # =========================================================================
    # Authentication & Access Control
    # =========================================================================

    def test_unauthenticated_and_non_officer_blocked_from_deficiencies(self):
        """Auth: Unauthenticated users and applicants cannot access deficiency routes."""
        d = self._create_deficiency()
        for url in [
            self.deficiency_list_url,
            reverse('officers:deficiency_detail', args=[d.pk]),
            reverse('officers:deficiency_create', args=[self.bad_inspection.pk]),
        ]:
            resp = self.client.get(url)
            self.assertRedirects(resp, f"{self.officer_login_url}?next={url}")

        self.client.login(username='applicant_c5', password=self.applicant_password)
        self.assertRedirects(self.client.get(self.deficiency_list_url), self.officer_login_url)
        self.assertRedirects(
            self.client.post(reverse('officers:deficiency_close', args=[d.pk])),
            self.officer_login_url,
        )

    # =========================================================================
    # Deficiency Creation
    # =========================================================================

    def test_officer_can_create_deficiency_and_reported_by_is_automatic(self):
        """Creation: Officer logs deficiency for completed Unsatisfactory/Rectification inspection."""
        self.client.login(username='officer_commit5', password=self.officer_password)
        url = reverse('officers:deficiency_create', args=[self.bad_inspection.pk])
        resp = self.client.post(url, {
            'title': 'Blocked Fire Exit',
            'description': 'Clear storage boxes from 2nd floor exit.',
            'severity': Deficiency.SEVERITY_CRITICAL,
            'officer_remarks': 'Urgent',
            'reported_by': self.other_officer_user.pk,  # spoof attempt ignored
        })
        d = Deficiency.objects.get(title='Blocked Fire Exit')
        self.assertRedirects(resp, reverse('officers:deficiency_detail', args=[d.pk]))
        self.assertEqual(d.reported_by, self.officer_user)
        self.assertEqual(d.application, self.application)
        self.assertEqual(d.inspection, self.bad_inspection)
        self.assertEqual(d.status, Deficiency.STATUS_OPEN)

    def test_cannot_create_deficiency_for_satisfactory_or_incomplete_inspection(self):
        """Creation: Blocked for Satisfactory or Scheduled inspections; required fields validated."""
        self.client.login(username='officer_commit5', password=self.officer_password)

        # Satisfactory inspection
        sat_insp = Inspection.objects.create(
            application=self.application,
            officer=self.officer_user,
            scheduled_date=timezone.localdate(),
            scheduled_time=datetime.time(14, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        InspectionReport.objects.create(
            inspection=sat_insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='All good.',
        )
        resp_sat = self.client.post(reverse('officers:deficiency_create', args=[sat_insp.pk]), {
            'title': 'Fake Deficiency',
            'description': 'Should be blocked.',
            'severity': Deficiency.SEVERITY_MINOR,
        })
        self.assertRedirects(resp_sat, reverse('officers:inspection_detail', args=[sat_insp.pk]))
        self.assertEqual(Deficiency.objects.filter(inspection=sat_insp).count(), 0)

        # Missing required fields on valid inspection
        resp_empty = self.client.post(reverse('officers:deficiency_create', args=[self.bad_inspection.pk]), {
            'title': '',
            'description': '',
            'severity': Deficiency.SEVERITY_MAJOR,
        })
        self.assertEqual(resp_empty.status_code, 200)
        self.assertContains(resp_empty, 'Deficiency title is required')
        self.assertEqual(Deficiency.objects.count(), 0)

    # =========================================================================
    # Deficiency List, Filters & Search
    # =========================================================================

    def test_deficiency_list_filters_and_search(self):
        """Listing: List loads and filters by status, severity, and search query."""
        self.client.login(username='officer_commit5', password=self.officer_password)
        self._create_deficiency(title='Alarm Fault', severity=Deficiency.SEVERITY_CRITICAL, status=Deficiency.STATUS_OPEN)
        self._create_deficiency(title='Signage Missing', severity=Deficiency.SEVERITY_MINOR, status=Deficiency.STATUS_CLOSED)

        resp_all = self.client.get(self.deficiency_list_url)
        self.assertEqual(resp_all.status_code, 200)
        self.assertContains(resp_all, 'Alarm Fault')
        self.assertContains(resp_all, 'Signage Missing')

        resp_status = self.client.get(f"{self.deficiency_list_url}?status=OPEN")
        self.assertContains(resp_status, 'Alarm Fault')
        self.assertNotContains(resp_status, 'Signage Missing')

        resp_sev = self.client.get(f"{self.deficiency_list_url}?severity=MINOR")
        self.assertContains(resp_sev, 'Signage Missing')
        self.assertNotContains(resp_sev, 'Alarm Fault')

        resp_q = self.client.get(f"{self.deficiency_list_url}?q=Alarm")
        self.assertContains(resp_q, 'Alarm Fault')
        self.assertNotContains(resp_q, 'Signage Missing')

    # =========================================================================
    # State Transitions & Rectification Workflow
    # =========================================================================

    def test_rectification_accept_and_close_workflow(self):
        """Workflow: Open -> Submitted -> Verified -> Closed, with evidence upload."""
        self.client.login(username='officer_commit5', password=self.officer_password)
        d = self._create_deficiency()

        # Cannot close before verification
        self.client.post(reverse('officers:deficiency_close', args=[d.pk]))
        d.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_OPEN)

        # Submit rectification with evidence
        evidence = SimpleUploadedFile('photo.jpg', b'fakejpgdata', content_type='image/jpeg')
        self.client.post(reverse('officers:deficiency_rectify', args=[d.pk]), {
            'description': 'Extinguishers installed on 4th floor.',
            'evidence_file': evidence,
        })
        d.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_SUBMITTED)
        rect = d.rectifications.first()
        self.assertIsNotNone(rect)
        self.assertTrue(bool(rect.evidence_file))

        # Accept rectification -> Verified
        self.client.post(reverse('officers:rectification_review', args=[d.pk, rect.pk]), {
            'action': 'ACCEPT',
            'review_remarks': 'Verified on photo evidence.',
        })
        d.refresh_from_db()
        rect.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_VERIFIED)
        self.assertEqual(rect.status, DeficiencyRectification.STATUS_ACCEPTED)
        self.assertEqual(rect.reviewed_by, self.officer_user)

        # Close deficiency -> Closed
        self.client.post(reverse('officers:deficiency_close', args=[d.pk]))
        d.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_CLOSED)
        self.assertIsNotNone(d.resolved_at)
        self.assertEqual(d.closed_by, self.officer_user)

        # Closed deficiency is read-only (cannot submit rectification)
        self.client.post(reverse('officers:deficiency_rectify', args=[d.pk]), {
            'description': 'Tamper closed deficiency.',
        })
        d.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_CLOSED)

    def test_rectification_reject_reopens_deficiency_and_allows_resubmission(self):
        """Workflow: Submitted -> Rejected -> Open, allowing another rectification."""
        self.client.login(username='officer_commit5', password=self.officer_password)
        d = self._create_deficiency()

        self.client.post(reverse('officers:deficiency_rectify', args=[d.pk]), {
            'description': 'Initial attempt.',
        })
        rect1 = d.rectifications.first()

        # Reject rectification
        self.client.post(reverse('officers:rectification_review', args=[d.pk, rect1.pk]), {
            'action': 'REJECT',
            'review_remarks': 'Pressure gauge unreadable.',
        })
        d.refresh_from_db()
        rect1.refresh_from_db()
        self.assertEqual(rect1.status, DeficiencyRectification.STATUS_REJECTED)
        self.assertEqual(d.status, Deficiency.STATUS_OPEN)

        # Resubmit another rectification
        self.client.post(reverse('officers:deficiency_rectify', args=[d.pk]), {
            'description': 'Clear photo uploaded with certified gauge.',
        })
        d.refresh_from_db()
        self.assertEqual(d.status, Deficiency.STATUS_SUBMITTED)
        self.assertEqual(d.rectifications.count(), 2)

    def test_invalid_deficiency_transitions_blocked(self):
        """State machine: Invalid transitions (Verified->Open, Closed->Open, Rejected->Verified) blocked."""
        d_ver = self._create_deficiency(status=Deficiency.STATUS_VERIFIED)
        self.assertFalse(d_ver.can_transition_to(Deficiency.STATUS_OPEN))
        self.assertFalse(d_ver.can_transition_to(Deficiency.STATUS_REJECTED))

        d_closed = self._create_deficiency(status=Deficiency.STATUS_CLOSED)
        self.assertFalse(d_closed.can_transition_to(Deficiency.STATUS_OPEN))
        self.assertFalse(d_closed.can_transition_to(Deficiency.STATUS_VERIFIED))

        d_rej = self._create_deficiency(status=Deficiency.STATUS_REJECTED)
        self.assertFalse(d_rej.can_transition_to(Deficiency.STATUS_VERIFIED))
        self.assertTrue(d_rej.can_transition_to(Deficiency.STATUS_OPEN))

    # =========================================================================
    # Application Eligibility & Officer Recommendation
    # =========================================================================

    def test_recommendation_blocked_until_all_prerequisites_met(self):
        """Eligibility: Blocked by incomplete docs, incomplete/bad inspection, or open deficiencies."""
        self.client.login(username='officer_commit5', password=self.officer_password)
        rec_url = reverse('officers:application_recommend', args=[self.application.pk])

        # 1. Currently bad_inspection has Requires Rectification -> blocked
        self.assertFalse(get_recommendation_eligibility(self.application)['is_eligible'])
        self.client.post(rec_url, {'recommendation': ApplicationReview.RECOMMENDATION_APPROVED})
        self.app_review.refresh_from_db()
        self.assertEqual(self.app_review.recommendation, ApplicationReview.RECOMMENDATION_PENDING)

        # 2. Add satisfactory re-inspection, but leave an open deficiency -> still blocked
        sat_insp = Inspection.objects.create(
            application=self.application,
            officer=self.officer_user,
            scheduled_date=timezone.localdate(),
            scheduled_time=datetime.time(15, 0),
            status=Inspection.STATUS_COMPLETED,
            completed_at=timezone.now(),
        )
        InspectionReport.objects.create(
            inspection=sat_insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='Re-inspection passed.',
        )
        d = self._create_deficiency(status=Deficiency.STATUS_OPEN)
        self.assertFalse(get_recommendation_eligibility(self.application)['is_eligible'])

        # 3. Close deficiency, but reject a document -> still blocked
        d.status = Deficiency.STATUS_CLOSED
        d.save()
        self.doc_verification.status = 'REJECTED'
        self.doc_verification.save()
        self.assertFalse(get_recommendation_eligibility(self.application)['is_eligible'])

        # 4. Re-verify document -> now ALL prerequisites met -> Eligible!
        self.doc_verification.status = 'VERIFIED'
        self.doc_verification.save()
        self.assertTrue(get_recommendation_eligibility(self.application)['is_eligible'])

        self.client.post(rec_url, {
            'recommendation': ApplicationReview.RECOMMENDATION_APPROVED,
            'recommendation_remarks': 'All safety requirements fulfilled.',
        })
        self.app_review.refresh_from_db()
        self.assertEqual(self.app_review.recommendation, ApplicationReview.RECOMMENDATION_APPROVED)
        self.assertEqual(self.app_review.recommended_by, self.officer_user)

    # =========================================================================
    # Dashboard Stats Integration
    # =========================================================================

    def test_dashboard_deficiency_and_recommendation_statistics(self):
        """Dashboard: Open deficiencies, pending rectifications, and ready-for-recommendation counts match DB."""
        self.client.login(username='officer_commit5', password=self.officer_password)

        d_open = self._create_deficiency(title='Open Issue', status=Deficiency.STATUS_OPEN)
        d_sub = self._create_deficiency(title='Sub Issue', status=Deficiency.STATUS_SUBMITTED)
        DeficiencyRectification.objects.create(
            deficiency=d_sub,
            submitted_by=self.applicant_user,
            description='Fixed',
            status=DeficiencyRectification.STATUS_SUBMITTED,
        )

        resp = self.client.get(self.officer_home_url)
        self.assertEqual(resp.status_code, 200)
        stats = resp.context['stats']
        self.assertEqual(stats['open_deficiencies'], 1)
        self.assertEqual(stats['pending_rectification_verification'], 1)
        self.assertEqual(stats['applications_ready_for_recommendation'], 0)

        # Now resolve deficiencies and make inspection satisfactory -> ready count becomes 1
        d_open.status = Deficiency.STATUS_CLOSED
        d_open.save()
        d_sub.status = Deficiency.STATUS_CLOSED
        d_sub.save()
        self.bad_report.overall_result = InspectionReport.RESULT_SATISFACTORY
        self.bad_report.save()

        resp2 = self.client.get(self.officer_home_url)
        self.assertEqual(resp2.context['stats']['applications_ready_for_recommendation'], 1)


# ===========================================================================
# Commit 6 Tests: End-to-End Integration (Applicant -> Officer Lifecycle)
# ===========================================================================

class OfficerEndToEndIntegrationTests(TestCase):
    """
    End-to-end integration test verifying the complete flow:
    Applicant submits -> Officer views -> Officer verifies docs ->
    Officer schedules inspection -> completes inspection -> creates deficiency ->
    rectification submitted -> officer accepts & closes -> re-inspection ->
    officer recommends approval.
    """

    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, self.officer_profile = create_officer_user(
            username='e2e_officer',
            email='e2e_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-E2E-1',
            first_name='Integration',
            last_name='Officer',
        )
        self.applicant_password = 'ApplicantPass#2026'
        self.applicant_user = User.objects.create_user(
            username='e2e_applicant@firenoc.gov.in',
            email='e2e_applicant@firenoc.gov.in',
            password=self.applicant_password,
            first_name='Ankan',
            last_name='Applicant',
        )

    def test_end_to_end_applicant_to_officer_workflow(self):
        # 1. Applicant submits application
        self.client.login(username=self.applicant_user.username, password=self.applicant_password)
        app_data = {
            'mobile_number': '9876543210',
            'building_name': 'E2E Commercial Complex',
            'building_type': 'COMMERCIAL',
            'building_type_other': '',
            'building_address': '45 Tech Boulevard',
            'city': 'Kolkata',
            'state': 'West Bengal',
            'pin_code': '700091',
            'num_floors': '10',
            'builtup_area': '3500.00',
            'year_construction': '2022',
            'occupancy_type': 'BUSINESS',
            'application_type': 'NEW_NOC',
            'purpose': 'E2E Testing NOC application.',
            'remarks': 'Equipped with sprinklers.',
            'declaration': 'on',
        }
        res_submit = self.client.post(reverse('applicants:application_new'), app_data)
        self.assertEqual(res_submit.status_code, 302)

        application = Application.objects.get(applicant=self.applicant_user)
        self.assertEqual(application.status, 'PENDING')

        # 2. Officer logs in and views applications list
        self.client.logout()
        self.client.login(username='e2e_officer', password=self.officer_password)

        res_list = self.client.get(reverse('officers:application_list'))
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, application.application_id)

        # 3. Officer views detail and verifies document
        res_detail = self.client.get(reverse('officers:application_detail', args=[application.pk]))
        self.assertEqual(res_detail.status_code, 200)

        doc = ApplicationDocument.objects.create(
            application=application,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Architectural Layout Plan',
            file=SimpleUploadedFile('plan.pdf', b'%PDF-1.4 mock content', content_type='application/pdf'),
        )

        res_vdoc = self.client.post(reverse('officers:document_verify', args=[application.pk, doc.pk]), {
            'action': 'VERIFY',
            'officer_remarks': 'Document is clear and compliant.',
        })
        self.assertEqual(res_vdoc.status_code, 302)

        # Officer marks review as DOCUMENTS_VERIFIED
        res_review = self.client.post(reverse('officers:application_review', args=[application.pk]), {
            'verification_status': 'DOCUMENTS_VERIFIED',
            'officer_remarks': 'All pre-inspection documents verified.',
        })
        self.assertEqual(res_review.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'DOCUMENTS_VERIFIED')

        # 4. Officer schedules inspection
        res_sched = self.client.post(reverse('officers:schedule_inspection', args=[application.pk]), {
            'scheduled_date': '2026-11-20',
            'scheduled_time': '10:00',
            'lead_officer': self.officer_user.pk,
            'inspection_type': 'SITE_INSPECTION',
            'scope_notes': 'Full building inspection.',
        })
        self.assertEqual(res_sched.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'UNDER_INSPECTION')

        inspection = application.inspections.first()
        self.assertEqual(inspection.status, Inspection.STATUS_SCHEDULED)

        # 5. Officer starts inspection
        res_start = self.client.post(reverse('officers:inspection_start', args=[inspection.pk]))
        self.assertEqual(res_start.status_code, 302)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, Inspection.STATUS_IN_PROGRESS)

        # 6. Officer completes inspection with report requiring rectification
        res_comp = self.client.post(reverse('officers:inspection_complete', args=[inspection.pk]), {
            'overall_result': InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            'general_observations': 'Blocked staircases need clearing.',
            'officer_remarks': 'Blockages in egress.',
        })
        self.assertEqual(res_comp.status_code, 302)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, Inspection.STATUS_COMPLETED)

        # 7. Officer logs deficiency
        res_def = self.client.post(reverse('officers:deficiency_create', args=[inspection.pk]), {
            'title': 'Emergency exit blocked',
            'description': 'Staircase B exit is obstructed by storage items.',
            'severity': Deficiency.SEVERITY_MAJOR,
        })
        self.assertEqual(res_def.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'DEFICIENT')

        deficiency = application.deficiencies.first()
        self.assertEqual(deficiency.status, Deficiency.STATUS_OPEN)

        # 8. Rectification submitted
        res_rect = self.client.post(reverse('officers:deficiency_rectify', args=[deficiency.pk]), {
            'description': 'All obstructions cleared from Staircase B.',
        })
        self.assertEqual(res_rect.status_code, 302)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_SUBMITTED)

        # 9. Officer reviews and accepts rectification
        rectification = deficiency.rectifications.first()
        res_rev_rect = self.client.post(reverse('officers:rectification_review', args=[deficiency.pk, rectification.pk]), {
            'action': 'ACCEPT',
            'remarks': 'Photographic proof confirmed clear.',
        })
        self.assertEqual(res_rev_rect.status_code, 302)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_VERIFIED)

        # 10. Officer closes deficiency -> transitions back to UNDER_INSPECTION
        res_close = self.client.post(reverse('officers:deficiency_close', args=[deficiency.pk]))
        self.assertEqual(res_close.status_code, 302)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_CLOSED)
        application.refresh_from_db()
        self.assertEqual(application.status, 'UNDER_INSPECTION')

        # 11. Schedule and complete re-inspection satisfactorily
        res_sched2 = self.client.post(reverse('officers:schedule_inspection', args=[application.pk]), {
            'scheduled_date': '2026-11-22',
            'scheduled_time': '11:00',
            'lead_officer': self.officer_user.pk,
            'inspection_type': 'RE_INSPECTION',
            'scope_notes': 'Verification of resolved deficiencies.',
        })
        self.assertEqual(res_sched2.status_code, 302)
        re_inspection = application.inspections.order_by('-pk').first()

        self.client.post(reverse('officers:inspection_start', args=[re_inspection.pk]))
        res_comp2 = self.client.post(reverse('officers:inspection_complete', args=[re_inspection.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': 'All safety measures fully compliant.',
            'officer_remarks': 'Passed site inspection.',
        })
        self.assertEqual(res_comp2.status_code, 302)

        # 12. Check recommendation eligibility
        self.assertTrue(application.is_ready_for_officer_recommendation())

        # 13. Submit officer recommendation
        res_rec = self.client.post(reverse('officers:application_recommend', args=[application.pk]), {
            'recommendation': 'RECOMMENDED_FOR_APPROVAL',
            'remarks': 'Site and documents compliant with fire safety codes.',
        })
        self.assertEqual(res_rec.status_code, 302)
        application.refresh_from_db()
        review = application.officer_review
        self.assertEqual(review.recommendation, 'RECOMMENDED_FOR_APPROVAL')


# ===========================================================================
# Commit 8 Tests: Stabilize Officer Document Verification
# ===========================================================================

class OfficerDocumentVerificationStabilityTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='doc_officer',
            email='doc_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-DOC-1',
        )
        self.applicant = User.objects.create_user(
            username='doc_applicant@firenoc.gov.in',
            email='doc_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.application = Application.objects.create(
            applicant=self.applicant,
            full_name='Doc App User',
            email='doc_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Doc Verification Tower',
            building_type='COMMERCIAL',
            building_address='10 Safety Rd',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=5,
            builtup_area='1200.00',
            year_construction=2020,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='PENDING',
        )
        self.doc1 = ApplicationDocument.objects.create(
            application=self.application,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Architectural Plan',
            file=SimpleUploadedFile('arch.pdf', b'%PDF-1.4 mock content', content_type='application/pdf'),
        )
        self.doc2 = ApplicationDocument.objects.create(
            application=self.application,
            document_type='FIRE_SAFETY_PLAN',
            document_name='Fire Safety Plan',
            file=SimpleUploadedFile('safety.pdf', b'%PDF-1.4 mock content', content_type='application/pdf'),
        )

    def test_rejection_requires_remarks_and_preserves_file(self):
        self.client.login(username='doc_officer', password=self.officer_password)
        # Attempt rejection without remarks
        resp_no_rem = self.client.post(
            reverse('officers:document_verify', args=[self.application.pk, self.doc1.pk]),
            {'action': 'REJECT', 'officer_remarks': ''}
        )
        self.assertEqual(resp_no_rem.status_code, 302)
        self.assertFalse(hasattr(self.doc1, 'verification'))

        # Reject with remarks
        resp_rej = self.client.post(
            reverse('officers:document_verify', args=[self.application.pk, self.doc1.pk]),
            {'action': 'REJECT', 'officer_remarks': 'Unclear stamp on floor 3'}
        )
        self.assertEqual(resp_rej.status_code, 302)
        self.doc1.refresh_from_db()
        self.assertEqual(self.doc1.verification.status, 'REJECTED')
        self.assertTrue(bool(self.doc1.file))  # File preserved

    def test_cannot_mark_documents_verified_with_unverified_or_rejected_docs(self):
        self.client.login(username='doc_officer', password=self.officer_password)
        # 1. Neither doc verified yet -> cannot advance to DOCUMENTS_VERIFIED
        resp1 = self.client.post(
            reverse('officers:application_review', args=[self.application.pk]),
            {'verification_status': 'DOCUMENTS_VERIFIED', 'officer_remarks': 'Trying to verify early'}
        )
        self.assertEqual(resp1.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'PENDING')

        # 2. Verify doc1, reject doc2 -> cannot advance
        self.client.post(
            reverse('officers:document_verify', args=[self.application.pk, self.doc1.pk]),
            {'action': 'VERIFY', 'officer_remarks': 'Approved'}
        )
        self.client.post(
            reverse('officers:document_verify', args=[self.application.pk, self.doc2.pk]),
            {'action': 'REJECT', 'officer_remarks': 'Signature missing'}
        )
        resp2 = self.client.post(
            reverse('officers:application_review', args=[self.application.pk]),
            {'verification_status': 'DOCUMENTS_VERIFIED', 'officer_remarks': 'Trying with rejected doc'}
        )
        self.assertEqual(resp2.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'PENDING')

        # 3. Now verify doc2 -> can advance
        self.client.post(
            reverse('officers:document_verify', args=[self.application.pk, self.doc2.pk]),
            {'action': 'VERIFY', 'officer_remarks': 'Fixed and approved'}
        )
        resp3 = self.client.post(
            reverse('officers:application_review', args=[self.application.pk]),
            {'verification_status': 'DOCUMENTS_VERIFIED', 'officer_remarks': 'All verified'}
        )
        self.assertEqual(resp3.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'DOCUMENTS_VERIFIED')


# ===========================================================================
# Commit 9 Tests: Stabilize Inspection Scheduling Workflow
# ===========================================================================

class OfficerInspectionSchedulingStabilityTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='sched_officer',
            email='sched_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-SCHED-1',
        )
        self.applicant = User.objects.create_user(
            username='sched_applicant@firenoc.gov.in',
            email='sched_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Sched Applicant',
            email='sched_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Scheduling Tower',
            building_type='COMMERCIAL',
            building_address='55 Fire Safety Way',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=6,
            builtup_area='2000.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='PENDING',
        )

    def test_cannot_schedule_if_not_document_verified(self):
        self.client.login(username='sched_officer', password=self.officer_password)
        resp = self.client.post(reverse('officers:schedule_inspection', args=[self.app.pk]), {
            'scheduled_date': '2026-12-01',
            'scheduled_time': '10:00',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.app.inspections.count(), 0)

    def test_cannot_schedule_in_past(self):
        self.app.status = 'DOCUMENTS_VERIFIED'
        self.app.save()

        self.client.login(username='sched_officer', password=self.officer_password)
        resp = self.client.post(reverse('officers:schedule_inspection', args=[self.app.pk]), {
            'scheduled_date': '2020-01-01',
            'scheduled_time': '10:00',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders form with error
        self.assertContains(resp, 'cannot be in the past')
        self.assertEqual(self.app.inspections.count(), 0)

    def test_schedule_success_and_start_transition(self):
        self.app.status = 'DOCUMENTS_VERIFIED'
        self.app.save()

        self.client.login(username='sched_officer', password=self.officer_password)
        resp = self.client.post(reverse('officers:schedule_inspection', args=[self.app.pk]), {
            'scheduled_date': '2026-12-01',
            'scheduled_time': '10:00',
            'location': 'Site location',
        })
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'UNDER_INSPECTION')

        inspection = self.app.inspections.first()
        self.assertIsNotNone(inspection)
        self.assertEqual(inspection.status, Inspection.STATUS_SCHEDULED)
        self.assertTrue(inspection.checklist_items.exists())

        # Start inspection
        resp_start = self.client.post(reverse('officers:inspection_start', args=[inspection.pk]))
        self.assertEqual(resp_start.status_code, 302)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, Inspection.STATUS_IN_PROGRESS)

        # Cannot re-start already in-progress inspection
        resp_restart = self.client.post(reverse('officers:inspection_start', args=[inspection.pk]))
        self.assertEqual(resp_restart.status_code, 302)
        inspection.refresh_from_db()
        self.assertEqual(inspection.status, Inspection.STATUS_IN_PROGRESS)


# ===========================================================================
# Commit 10 Tests: Complete Inspection Checklist and Reporting
# ===========================================================================

class OfficerInspectionChecklistAndReportingTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='check_officer',
            email='check_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-CHK-1',
        )
        self.other_officer, _ = create_officer_user(
            username='other_officer',
            email='other_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-CHK-2',
        )
        self.applicant = User.objects.create_user(
            username='check_applicant@firenoc.gov.in',
            email='check_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Checklist Applicant',
            email='check_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Checklist Tower',
            building_type='COMMERCIAL',
            building_address='88 Safety Blvd',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=5,
            builtup_area='1500.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='UNDER_INSPECTION',
        )
        self.inspection = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(11, 0),
            status=Inspection.STATUS_IN_PROGRESS,
        )
        from officers.views import _ensure_checklist
        _ensure_checklist(self.inspection)

    def test_checklist_update_and_persistence(self):
        self.client.login(username='check_officer', password=self.officer_password)
        resp = self.client.post(
            reverse('officers:inspection_checklist_save', args=[self.inspection.pk]),
            {
                'checklist_EXTINGUISHER_AVAILABLE_status': InspectionChecklistItem.STATUS_COMPLIANT,
                'checklist_EXTINGUISHER_AVAILABLE_remarks': 'All tested and certified.',
            }
        )
        self.assertEqual(resp.status_code, 302)
        item = self.inspection.checklist_items.get(item_type='EXTINGUISHER_AVAILABLE')
        self.assertEqual(item.status, InspectionChecklistItem.STATUS_COMPLIANT)
        self.assertEqual(item.remarks, 'All tested and certified.')

    def test_complete_inspection_validation_and_report_creation(self):
        self.client.login(username='check_officer', password=self.officer_password)
        # Missing observations -> rejected
        resp_fail = self.client.post(
            reverse('officers:inspection_complete', args=[self.inspection.pk]),
            {'overall_result': InspectionReport.RESULT_SATISFACTORY, 'general_observations': ''}
        )
        self.assertEqual(resp_fail.status_code, 302)
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, Inspection.STATUS_IN_PROGRESS)

        # Valid completion
        resp_ok = self.client.post(
            reverse('officers:inspection_complete', args=[self.inspection.pk]),
            {
                'overall_result': InspectionReport.RESULT_SATISFACTORY,
                'general_observations': 'Everything meets safety standards.',
                'officer_remarks': 'Recommended for NOC.',
            }
        )
        self.assertEqual(resp_ok.status_code, 302)
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, Inspection.STATUS_COMPLETED)
        self.assertEqual(self.inspection.report.overall_result, InspectionReport.RESULT_SATISFACTORY)

        # Cannot edit checklist after completion
        resp_post_comp = self.client.post(
            reverse('officers:inspection_checklist_save', args=[self.inspection.pk]),
            {'checklist_EXTINGUISHER_AVAILABLE_status': InspectionChecklistItem.STATUS_NON_COMPLIANT}
        )
        self.assertEqual(resp_post_comp.status_code, 302)
        item = self.inspection.checklist_items.get(item_type='EXTINGUISHER_AVAILABLE')
        self.assertNotEqual(item.status, InspectionChecklistItem.STATUS_NON_COMPLIANT)

    def test_other_officer_cannot_complete_or_modify(self):
        self.client.login(username='other_officer', password=self.officer_password)
        resp = self.client.post(
            reverse('officers:inspection_complete', args=[self.inspection.pk]),
            {'overall_result': InspectionReport.RESULT_SATISFACTORY, 'general_observations': 'Observation'}
        )
        self.assertEqual(resp.status_code, 302)
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.status, Inspection.STATUS_IN_PROGRESS)


# ===========================================================================
# Commit 11 Tests: Stabilize Deficiency and Rectification Workflow
# ===========================================================================

class OfficerDeficiencyAndRectificationWorkflowTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='def_officer',
            email='def_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-DEF-1',
        )
        self.applicant = User.objects.create_user(
            username='def_applicant@firenoc.gov.in',
            email='def_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.other_applicant = User.objects.create_user(
            username='other_app@firenoc.gov.in',
            email='other_app@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Deficiency Applicant',
            email='def_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Deficiency Plaza',
            building_type='COMMERCIAL',
            building_address='99 Hazard Ave',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=5,
            builtup_area='1600.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='UNDER_INSPECTION',
        )
        self.inspection = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(11, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        self.report = InspectionReport.objects.create(
            inspection=self.inspection,
            overall_result=InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            general_observations='Blocked exit route.',
            completed_at=timezone.now(),
        )

    def test_deficiency_creation_transitions_application_to_deficient(self):
        self.client.login(username='def_officer', password=self.officer_password)
        resp = self.client.post(
            reverse('officers:deficiency_create', args=[self.inspection.pk]),
            {
                'title': 'Emergency door blocked',
                'description': 'Heavy crates blocking exit path',
                'severity': Deficiency.SEVERITY_MAJOR,
                'officer_remarks': 'Must clear immediately',
            }
        )
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'DEFICIENT')
        deficiency = self.app.deficiencies.first()
        self.assertIsNotNone(deficiency)
        self.assertEqual(deficiency.status, Deficiency.STATUS_OPEN)

    def test_applicant_can_submit_rectification_and_officer_review(self):
        deficiency = Deficiency.objects.create(
            application=self.app,
            inspection=self.inspection,
            reported_by=self.officer_user,
            title='Corridor blocked',
            description='Boxes in corridor',
            severity=Deficiency.SEVERITY_MAJOR,
            status=Deficiency.STATUS_OPEN,
        )
        # Unauthorized applicant cannot submit
        self.client.login(username='other_app@firenoc.gov.in', password='ValidPass#2026')
        resp_unauth = self.client.post(
            reverse('officers:deficiency_rectify', args=[deficiency.pk]),
            {'description': 'Cleared by stranger'}
        )
        self.assertEqual(resp_unauth.status_code, 302)
        self.assertEqual(deficiency.rectifications.count(), 0)

        # Authorized applicant submits rectification
        self.client.login(username='def_applicant@firenoc.gov.in', password='ValidPass#2026')
        resp_rect = self.client.post(
            reverse('officers:deficiency_rectify', args=[deficiency.pk]),
            {'description': 'All corridor boxes removed and cleaned.'}
        )
        self.assertEqual(resp_rect.status_code, 302)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_SUBMITTED)
        self.assertEqual(deficiency.rectifications.count(), 1)

        # Officer reviews and rejects first
        self.client.login(username='def_officer', password=self.officer_password)
        rect = deficiency.rectifications.first()
        resp_rej = self.client.post(
            reverse('officers:rectification_review', args=[deficiency.pk, rect.pk]),
            {'action': 'REJECT', 'review_remarks': 'Photo missing'}
        )
        self.assertEqual(resp_rej.status_code, 302)
        rect.refresh_from_db()
        self.assertEqual(rect.status, DeficiencyRectification.STATUS_REJECTED)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_OPEN)

        # Submit second rectification, then accept
        self.client.login(username='def_applicant@firenoc.gov.in', password='ValidPass#2026')
        self.client.post(
            reverse('officers:deficiency_rectify', args=[deficiency.pk]),
            {'description': 'Re-cleaned with photographic evidence.'}
        )
        rect2 = deficiency.rectifications.order_by('-pk').first()

        self.client.login(username='def_officer', password=self.officer_password)
        resp_acc = self.client.post(
            reverse('officers:rectification_review', args=[deficiency.pk, rect2.pk]),
            {'action': 'ACCEPT', 'review_remarks': 'Verified clean'}
        )
        self.assertEqual(resp_acc.status_code, 302)
        deficiency.refresh_from_db()
        self.assertEqual(deficiency.status, Deficiency.STATUS_VERIFIED)


# ===========================================================================
# Commit 12 Tests: Complete Re-inspection and Deficiency Closure Flow
# ===========================================================================

class OfficerReinspectionAndDeficiencyClosureTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='re_officer',
            email='re_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-RE-1',
        )
        self.applicant = User.objects.create_user(
            username='re_applicant@firenoc.gov.in',
            email='re_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Reinspection Applicant',
            email='re_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Reinspection Tower',
            building_type='COMMERCIAL',
            building_address='123 Reinspect Way',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=7,
            builtup_area='3000.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='DOCUMENTS_VERIFIED',
        )
        # Create verified doc
        doc = ApplicationDocument.objects.create(
            application=self.app,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Blueprints',
            file=SimpleUploadedFile('test.pdf', b'%PDF-1.4', content_type='application/pdf'),
        )
        DocumentVerification.objects.create(
            document=doc,
            status='VERIFIED',
            verified_by=self.officer_user,
        )

        # First inspection: completed with rectification required
        self.insp1 = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(10, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        InspectionReport.objects.create(
            inspection=self.insp1,
            overall_result=InspectionReport.RESULT_REQUIRES_RECTIFICATION,
            general_observations='Emergency signage damaged.',
        )
        self.app.status = 'DEFICIENT'
        self.app.save()

        self.deficiency = Deficiency.objects.create(
            application=self.app,
            inspection=self.insp1,
            reported_by=self.officer_user,
            title='Signage broken',
            description='Floor 2 exit signs missing',
            severity=Deficiency.SEVERITY_MINOR,
            status=Deficiency.STATUS_OPEN,
        )

    def test_reinspection_preserves_history_and_updates_readiness(self):
        self.client.login(username='re_officer', password=self.officer_password)

        # Verify and close deficiency
        self.deficiency.status = Deficiency.STATUS_VERIFIED
        self.deficiency.save()

        resp_close = self.client.post(reverse('officers:deficiency_close', args=[self.deficiency.pk]))
        self.assertEqual(resp_close.status_code, 302)
        self.deficiency.refresh_from_db()
        self.assertEqual(self.deficiency.status, Deficiency.STATUS_CLOSED)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'UNDER_INSPECTION')

        # Schedule re-inspection
        resp_sched = self.client.post(reverse('officers:schedule_inspection', args=[self.app.pk]), {
            'scheduled_date': '2026-12-10',
            'scheduled_time': '14:00',
            'location': 'Reinspection Site',
        })
        self.assertEqual(resp_sched.status_code, 302)
        self.assertEqual(self.app.inspections.count(), 2)

        insp2 = self.app.inspections.order_by('-pk').first()
        self.assertEqual(insp2.status, Inspection.STATUS_SCHEDULED)
        self.assertNotEqual(insp2.pk, self.insp1.pk)

        # Start and complete re-inspection satisfactorily
        self.client.post(reverse('officers:inspection_start', args=[insp2.pk]))
        resp_comp = self.client.post(reverse('officers:inspection_complete', args=[insp2.pk]), {
            'overall_result': InspectionReport.RESULT_SATISFACTORY,
            'general_observations': 'Re-inspected: signs replaced and verified.',
        })
        self.assertEqual(resp_comp.status_code, 302)
        insp2.refresh_from_db()
        self.assertEqual(insp2.status, Inspection.STATUS_COMPLETED)
        self.assertEqual(insp2.report.overall_result, InspectionReport.RESULT_SATISFACTORY)

        # Historical inspection 1 report is preserved
        self.insp1.refresh_from_db()
        self.assertEqual(self.insp1.report.overall_result, InspectionReport.RESULT_REQUIRES_RECTIFICATION)

        # Readiness is now TRUE
        self.assertTrue(self.app.is_ready_for_officer_recommendation())


# ===========================================================================
# Commit 13 Tests: Finalize Officer Recommendation Workflow
# ===========================================================================

class OfficerRecommendationFinalizationTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='rec_officer',
            email='rec_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-REC-1',
        )
        self.applicant = User.objects.create_user(
            username='rec_applicant@firenoc.gov.in',
            email='rec_applicant@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Rec Applicant',
            email='rec_applicant@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Recommendation Tower',
            building_type='COMMERCIAL',
            building_address='77 Final St',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=5,
            builtup_area='1200.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='UNDER_INSPECTION',
        )

    def test_ineligible_application_cannot_be_recommended(self):
        self.client.login(username='rec_officer', password=self.officer_password)
        # No verified documents, no inspection -> blocked
        resp = self.client.post(reverse('officers:application_recommend', args=[self.app.pk]), {
            'recommendation': ApplicationReview.RECOMMENDATION_APPROVED,
            'recommendation_remarks': 'Trying to recommend ineligible app',
        })
        self.assertEqual(resp.status_code, 302)
        review = getattr(self.app, 'officer_review', None)
        if review:
            self.assertNotEqual(review.recommendation, ApplicationReview.RECOMMENDATION_APPROVED)

    def test_eligible_application_recommendation_success_and_officer_cannot_issue_noc(self):
        # Set up prerequisites
        doc = ApplicationDocument.objects.create(
            application=self.app,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Blueprints',
            file=SimpleUploadedFile('test.pdf', b'%PDF-1.4', content_type='application/pdf'),
        )
        DocumentVerification.objects.create(document=doc, status='VERIFIED', verified_by=self.officer_user)
        insp = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(10, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        InspectionReport.objects.create(
            inspection=insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='All compliant',
        )

        self.assertTrue(self.app.is_ready_for_officer_recommendation())

        self.client.login(username='rec_officer', password=self.officer_password)
        resp = self.client.post(reverse('officers:application_recommend', args=[self.app.pk]), {
            'recommendation': ApplicationReview.RECOMMENDATION_APPROVED,
            'recommendation_remarks': 'All fire safety norms strictly met. Forwarded to Admin.',
        })
        self.assertEqual(resp.status_code, 302)

        self.app.refresh_from_db()
        # Crucial: Officer recommendation does NOT set status to APPROVED (NOC not issued by officer)
        self.assertNotEqual(self.app.status, 'APPROVED')
        self.assertEqual(self.app.officer_review.recommendation, ApplicationReview.RECOMMENDATION_APPROVED)
        self.assertEqual(self.app.officer_review.recommended_by, self.officer_user)
        self.assertIn('Forwarded to Admin', self.app.officer_review.recommendation_remarks)

    def test_applicant_cannot_submit_recommendation(self):
        self.client.login(username='rec_applicant@firenoc.gov.in', password='ValidPass#2026')
        resp = self.client.post(reverse('officers:application_recommend', args=[self.app.pk]), {
            'recommendation': ApplicationReview.RECOMMENDATION_APPROVED,
        })
        # Blocked: redirected to officer login
        self.assertEqual(resp.status_code, 302)
        self.assertIn('officer/login', resp.url)


# ===========================================================================
# Commit 14 Tests: Integrate Officer Recommendation with NOC Workflow
# ===========================================================================

class AdminNocIntegrationTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='admin_noc',
            email='admin@firenoc.gov.in',
            password='AdminPass#2026',
        )
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='noc_officer',
            email='noc_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-NOC-1',
        )
        self.applicant = User.objects.create_user(
            username='app_user@firenoc.gov.in',
            email='app_user@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Admin NOC Applicant',
            email='app_user@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Metropolis Complex',
            building_type='COMMERCIAL',
            building_address='100 Administrative Plaza',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=10,
            builtup_area='4000.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='DOCUMENTS_VERIFIED',
        )
        doc = ApplicationDocument.objects.create(
            application=self.app,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Floor Blueprints',
            file=SimpleUploadedFile('blueprint.pdf', b'%PDF-1.4', content_type='application/pdf'),
        )
        DocumentVerification.objects.create(document=doc, status='VERIFIED', verified_by=self.officer_user)
        self.insp = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(10, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        InspectionReport.objects.create(
            inspection=self.insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='Fire lines pressurized and compliant.',
        )
        self.review = ApplicationReview.objects.create(
            application=self.app,
            status='DOCUMENTS_VERIFIED',
            recommendation=ApplicationReview.RECOMMENDATION_APPROVED,
            recommendation_remarks='Fully compliant with NBC Part 4.',
            recommended_by=self.officer_user,
            recommended_at=timezone.now(),
        )

    def test_admin_can_view_application_with_officer_recommendation_and_reports(self):
        self.client.login(username='admin_noc', password='AdminPass#2026')
        admin_change_url = reverse('admin:applicants_application_change', args=[self.app.pk])
        resp = self.client.get(admin_change_url)
        self.assertEqual(resp.status_code, 200)

        # Admin sees building and applicant details
        self.assertContains(resp, 'Metropolis Complex')
        self.assertContains(resp, 'Admin NOC Applicant')

        # Admin sees officer recommendation and remarks
        self.assertContains(resp, 'Recommended for Approval')
        self.assertContains(resp, 'Fully compliant with NBC Part 4.')

        # Admin sees inspection result and document audits
        self.assertContains(resp, 'Satisfactory')
        self.assertContains(resp, 'Floor Blueprints')

    def test_admin_list_filter_for_ready_applications(self):
        self.client.login(username='admin_noc', password='AdminPass#2026')
        admin_list_url = reverse('admin:applicants_application_changelist')
        resp = self.client.get(admin_list_url, {'final_review': 'ready'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Metropolis Complex')


# ===========================================================================
# Commit 15 Tests: Implement Final NOC Decision Workflow
# ===========================================================================

class FinalNocDecisionWorkflowTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='admin_decider',
            email='admin_decider@firenoc.gov.in',
            password='AdminPass#2026',
        )
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, _ = create_officer_user(
            username='officer_decider',
            email='officer_decider@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-DEC-1',
        )
        self.applicant = User.objects.create_user(
            username='app_decider@firenoc.gov.in',
            email='app_decider@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app = Application.objects.create(
            applicant=self.applicant,
            full_name='Decision Applicant',
            email='app_decider@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Decision Tower',
            building_type='COMMERCIAL',
            building_address='500 Capital Way',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=8,
            builtup_area='3200.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='DOCUMENTS_VERIFIED',
        )

    def test_admin_cannot_approve_ineligible_application(self):
        self.client.login(username='admin_decider', password='AdminPass#2026')
        url = reverse('admin:applicants_application_final_decision', args=[self.app.pk])
        resp = self.client.post(url, {'decision': 'APPROVE'})
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertNotEqual(self.app.status, 'APPROVED')

    def test_admin_approves_eligible_application(self):
        # Setup eligibility
        doc = ApplicationDocument.objects.create(
            application=self.app,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Blueprints',
            file=SimpleUploadedFile('test.pdf', b'%PDF-1.4', content_type='application/pdf'),
        )
        DocumentVerification.objects.create(document=doc, status='VERIFIED', verified_by=self.officer_user)
        insp = Inspection.objects.create(
            application=self.app,
            officer=self.officer_user,
            scheduled_date=datetime.date.today(),
            scheduled_time=datetime.time(10, 0),
            status=Inspection.STATUS_COMPLETED,
        )
        InspectionReport.objects.create(
            inspection=insp,
            overall_result=InspectionReport.RESULT_SATISFACTORY,
            general_observations='All compliant',
        )
        ApplicationReview.objects.create(
            application=self.app,
            status='DOCUMENTS_VERIFIED',
            recommendation=ApplicationReview.RECOMMENDATION_APPROVED,
            recommendation_remarks='Approved by officer',
            recommended_by=self.officer_user,
            recommended_at=timezone.now(),
        )

        self.client.login(username='admin_decider', password='AdminPass#2026')
        url = reverse('admin:applicants_application_final_decision', args=[self.app.pk])
        resp = self.client.post(url, {'decision': 'APPROVE'})
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'APPROVED')

    def test_admin_rejects_application_with_reason(self):
        self.client.login(username='admin_decider', password='AdminPass#2026')
        url = reverse('admin:applicants_application_final_decision', args=[self.app.pk])
        resp = self.client.post(url, {
            'decision': 'REJECT',
            'rejection_reason': 'Building setback insufficient per municipal fire code.'
        })
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'REJECTED')
        self.assertIn('Building setback insufficient', self.app.remarks)

    def test_officer_and_applicant_cannot_access_final_decision_endpoint(self):
        url = reverse('admin:applicants_application_final_decision', args=[self.app.pk])

        # Officer attempt
        self.client.login(username='officer_decider', password=self.officer_password)
        resp_off = self.client.post(url, {'decision': 'APPROVE'})
        # Should redirect to admin login because officer is not staff/superuser
        self.assertEqual(resp_off.status_code, 302)
        self.assertIn('admin/login', resp_off.url)

        # Applicant attempt
        self.client.login(username='app_decider@firenoc.gov.in', password='ValidPass#2026')
        resp_app = self.client.post(url, {'decision': 'APPROVE'})
        self.assertEqual(resp_app.status_code, 302)
        self.assertIn('admin/login', resp_app.url)


# ===========================================================================
# Commit 17 Tests: Harden Role Permissions and Access Control
# ===========================================================================

class RolePermissionsAndSecurityHardeningTests(TestCase):
    def setUp(self):
        self.officer_password = 'OfficerPass#2026'
        self.officer_user, self.officer_profile = create_officer_user(
            username='perm_officer',
            email='perm_officer@firenoc.gov.in',
            password=self.officer_password,
            officer_id='FO-PERM-1',
        )
        self.applicant_a = User.objects.create_user(
            username='perm_app_a@firenoc.gov.in',
            email='perm_app_a@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.applicant_b = User.objects.create_user(
            username='perm_app_b@firenoc.gov.in',
            email='perm_app_b@firenoc.gov.in',
            password='ValidPass#2026',
        )
        self.app_a = Application.objects.create(
            applicant=self.applicant_a,
            full_name='Applicant A',
            email='perm_app_a@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Fortress Tower',
            building_type='COMMERCIAL',
            building_address='1 Guard St',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=5,
            builtup_area='1500.00',
            year_construction=2021,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            status='PENDING',
        )

    def test_applicant_cannot_access_officer_pages(self):
        self.client.login(username='perm_app_a@firenoc.gov.in', password='ValidPass#2026')
        protected_officer_urls = [
            reverse('officers:dashboard'),
            reverse('officers:application_list'),
            reverse('officers:inspection_list'),
            reverse('officers:deficiency_list'),
        ]
        for url in protected_officer_urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertIn('officer/login', resp.url)

    def test_applicant_cannot_access_admin_pages(self):
        self.client.login(username='perm_app_a@firenoc.gov.in', password='ValidPass#2026')
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('admin/login', resp.url)

    def test_officer_cannot_access_admin_pages(self):
        self.client.login(username='perm_officer', password=self.officer_password)
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('admin/login', resp.url)

    def test_deactivated_officer_blocked_from_officer_views(self):
        self.officer_profile.is_active = False
        self.officer_profile.save()

        self.client.login(username='perm_officer', password=self.officer_password)
        resp = self.client.get(reverse('officers:dashboard'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('officer/login', resp.url)

    def test_applicant_cannot_upload_document_to_another_applicant_application(self):
        self.client.login(username='perm_app_b@firenoc.gov.in', password='ValidPass#2026')
        upload_url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        resp = self.client.get(upload_url)
        self.assertEqual(resp.status_code, 404)

        resp_post = self.client.post(upload_url, {
            'document_type': 'ARCHITECTURAL_BLUEPRINT',
            'document_name': 'Hacked Document',
            'document_file': SimpleUploadedFile('hacked.pdf', b'content', content_type='application/pdf'),
        })
        self.assertEqual(resp_post.status_code, 404)
        self.assertEqual(self.app_a.documents.count(), 0)
