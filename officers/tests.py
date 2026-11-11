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
