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
