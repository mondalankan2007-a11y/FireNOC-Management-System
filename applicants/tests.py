import datetime
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password
from django.urls import reverse
from applicants.views import get_applicant_dashboard_data


class ApplicantAuthenticationTests(TestCase):
    """
    Comprehensive test suite for Applicant Authentication and Dashboard functionality:
    Registration, Login, Protected Routes, Logout, and Dashboard Metrics.
    """

    def setUp(self):
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.logout_url = reverse('logout')
        self.applicant_home_url = reverse('applicants:applicant_home')
        self.dashboard_url = reverse('applicants:dashboard')

        self.valid_reg_data = {
            'full_name': 'Ankan Mondal',
            'email': 'applicant@firenoc.gov.in',
            'mobile_number': '9876543210',
            'password': 'FireSafety#2026',
            'confirm_password': 'FireSafety#2026',
        }

    # ==========================================
    # Registration Tests
    # ==========================================

    def test_registration_page_loads(self):
        """Verify the registration page renders with HTTP 200."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Applicant Registration')
        self.assertContains(response, 'Fire Safety Compliance Portal')

    def test_successful_registration(self):
        """Verify registration still works, creates user, hashes password, and redirects to login."""
        response = self.client.post(self.register_url, self.valid_reg_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.login_url)
        self.assertContains(response, 'Registration successful!')

        user = User.objects.get(email='applicant@firenoc.gov.in')
        self.assertEqual(user.first_name, 'Ankan')
        self.assertEqual(user.last_name, 'Mondal')
        self.assertEqual(user.username, 'applicant@firenoc.gov.in')
        self.assertTrue(check_password('FireSafety#2026', user.password))
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))

    def test_missing_required_fields_registration(self):
        """Verify registration fails when fields are missing."""
        data = {
            'full_name': '',
            'email': '',
            'mobile_number': '',
            'password': '',
            'confirm_password': '',
        }
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Full Name is required.')
        self.assertContains(response, 'Email Address is required.')
        self.assertContains(response, 'Mobile Number is required.')
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_email_registration(self):
        """Verify invalid email format is rejected."""
        data = self.valid_reg_data.copy()
        data['email'] = 'not-an-email'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a valid email address.')
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_email_registration(self):
        """Verify registering with an already existing email is prevented."""
        User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='InitialPassword123#'
        )
        response = self.client.post(self.register_url, self.valid_reg_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(User.objects.filter(email='applicant@firenoc.gov.in').count(), 1)

    def test_password_mismatch_registration(self):
        """Verify mismatched password confirmation is rejected."""
        data = self.valid_reg_data.copy()
        data['confirm_password'] = 'MismatchPassword#2026'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match.')
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password_registration(self):
        """Verify weak passwords fail Django's built-in password validators."""
        data = self.valid_reg_data.copy()
        data['password'] = '123'
        data['confirm_password'] = '123'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at least 8 characters')
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_mobile_number_registration(self):
        """Verify non-10-digit mobile number is rejected."""
        data = self.valid_reg_data.copy()
        data['mobile_number'] = '12345'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a valid 10-digit mobile number.')
        self.assertEqual(User.objects.count(), 0)

    def test_form_values_preserved_except_password(self):
        """Verify safe submitted values are preserved on error, while passwords are never leaked."""
        data = self.valid_reg_data.copy()
        data['confirm_password'] = 'MismatchPassword#2026'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Ankan Mondal"')
        self.assertContains(response, 'value="applicant@firenoc.gov.in"')
        self.assertContains(response, 'value="9876543210"')
        self.assertNotContains(response, 'FireSafety#2026')
        self.assertNotContains(response, 'MismatchPassword#2026')

    # ==========================================
    # Login & Logout Tests
    # ==========================================

    def test_login_page_renders_with_all_ui_elements(self):
        """Verify the login page renders with all required form controls."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Applicant Login')
        self.assertContains(response, 'id="id_email"')
        self.assertContains(response, 'id="id_password"')
        self.assertContains(response, 'id="togglePasswordBtn"')
        self.assertContains(response, 'id="id_remember_me"')
        self.assertContains(response, 'Forgot Password?')
        self.assertContains(response, 'Login')
        self.assertContains(response, reverse('register'))

    def test_login_with_valid_credentials_redirects_to_dashboard(self):
        """Test 1: Login with valid credentials establishes session and opens dashboard."""
        User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026',
            first_name='Ankan',
            last_name='Mondal'
        )

        login_data = {
            'email': 'applicant@firenoc.gov.in',
            'password': 'ValidPassword#2026',
        }
        response = self.client.post(self.login_url, login_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.dashboard_url)
        self.assertContains(response, 'Welcome back, Ankan!')
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].email, 'applicant@firenoc.gov.in')

    def test_login_with_incorrect_password(self):
        """Test 2: Login with incorrect password displays error and does not authenticate."""
        User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )

        login_data = {
            'email': 'applicant@firenoc.gov.in',
            'password': 'WrongPassword#999',
        }
        response = self.client.post(self.login_url, login_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email address or password.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_login_with_unregistered_email(self):
        """Test 3: Login with an unregistered email displays invalid credentials error."""
        login_data = {
            'email': 'unknown@firenoc.gov.in',
            'password': 'SomePassword#123',
        }
        response = self.client.post(self.login_url, login_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email address or password.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_login_with_empty_fields(self):
        """Test 4: Login with empty email or password displays required fields error."""
        response = self.client.post(self.login_url, {'email': '', 'password': ''}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Both email address and password are required.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_access_applicant_page_without_login(self):
        """Test 5: Unauthenticated access to /applicant/ redirects to login."""
        response = self.client.get(self.applicant_home_url)
        self.assertEqual(response.status_code, 302)
        expected_redirect = f"{self.login_url}?next={self.applicant_home_url}"
        self.assertRedirects(response, expected_redirect)

    def test_logout_successfully(self):
        """Test 6: Logout terminates session, redirects to /login/, and displays success message."""
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        response = self.client.post(self.logout_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.login_url)
        self.assertContains(response, 'You have been successfully logged out.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_try_accessing_protected_page_after_logout(self):
        """Test 7: Accessing /applicant/dashboard/ after logout is blocked and redirects to login."""
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        # Logout
        self.client.post(self.logout_url)

        # Try accessing protected dashboard
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        expected_redirect = f"{self.login_url}?next={self.dashboard_url}"
        self.assertRedirects(response, expected_redirect)

    # ==========================================
    # Dashboard & Statistics Tests
    # ==========================================

    def test_dashboard_redirects_unauthenticated_user(self):
        """Verify unauthenticated access to /applicant/dashboard/ redirects to /login/."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        expected_redirect = f"{self.login_url}?next={self.dashboard_url}"
        self.assertRedirects(response, expected_redirect)

    def test_dashboard_displays_zero_when_applicant_has_no_applications(self):
        """
        Test 1: Dashboard displays zero when applicant has no applications.
        Verifies all 4 cards display '0' and the clean empty state is rendered.
        """
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026',
            first_name='Ankan',
            last_name='Mondal'
        )
        self.client.force_login(user)

        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)

        # 1. Welcome section displays name & description
        self.assertContains(response, 'Welcome back, Ankan!')
        self.assertContains(response, 'Manage your Fire NOC applications and track their progress from one place.')
        self.assertContains(response, 'Apply for Fire NOC')

        # 2. Sidebar contains all specified items
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'New Application')
        self.assertContains(response, 'My Applications')
        self.assertContains(response, 'Documents')
        self.assertContains(response, 'Inspection Details')
        self.assertContains(response, 'Corrections')
        self.assertContains(response, 'My NOCs')
        self.assertContains(response, 'Profile')
        self.assertContains(response, 'Logout')

        # 3. Four statistics cards with exact titles and 0 values
        self.assertContains(response, 'Total Applications')
        self.assertContains(response, 'Pending Applications')
        self.assertContains(response, 'Approved Applications')
        self.assertContains(response, 'NOCs Issued')
        self.assertEqual(response.context['stats']['total_applications'], 0)
        self.assertEqual(response.context['stats']['pending_applications'], 0)
        self.assertEqual(response.context['stats']['approved_applications'], 0)
        self.assertEqual(response.context['stats']['nocs_issued'], 0)

        # 4. Recent Applications table headers and empty state message
        self.assertContains(response, 'Application ID')
        self.assertContains(response, 'Building Name')
        self.assertContains(response, 'Submission Date')
        self.assertContains(response, 'Current Status')
        self.assertContains(response, 'Action')
        self.assertContains(response, "You haven't submitted any applications yet.")
        self.assertContains(response, 'Start New Application')

    def test_total_applications_statistic_accurately_reflects_records(self):
        """
        Test 2: Total applications statistic accurately reflects the applicant's records.
        """
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        mock_stats = {
            'total_applications': 7,
            'pending_applications': 0,
            'approved_applications': 0,
            'nocs_issued': 0,
        }
        with patch('applicants.views.get_applicant_dashboard_data', return_value=(mock_stats, [])):
            response = self.client.get(self.dashboard_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['stats']['total_applications'], 7)
            self.assertContains(response, '<div class="dashboard-stat-number">7</div>')

    def test_pending_applications_statistic_counts_only_pending(self):
        """
        Test 3: Pending applications statistic counts only pending records.
        """
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        mock_stats = {
            'total_applications': 5,
            'pending_applications': 3,
            'approved_applications': 1,
            'nocs_issued': 1,
        }
        with patch('applicants.views.get_applicant_dashboard_data', return_value=(mock_stats, [])):
            response = self.client.get(self.dashboard_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['stats']['pending_applications'], 3)
            self.assertContains(response, '<div class="dashboard-stat-number text-warning-emphasis">3</div>')

    def test_approved_applications_statistic_counts_only_approved(self):
        """
        Test 4: Approved applications statistic counts only approved records.
        """
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        mock_stats = {
            'total_applications': 6,
            'pending_applications': 2,
            'approved_applications': 4,
            'nocs_issued': 2,
        }
        with patch('applicants.views.get_applicant_dashboard_data', return_value=(mock_stats, [])):
            response = self.client.get(self.dashboard_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['stats']['approved_applications'], 4)
            self.assertContains(response, '<div class="dashboard-stat-number text-success">4</div>')

    def test_nocs_issued_statistic_counts_only_issued_certificates(self):
        """
        Test 5: NOCs Issued statistic counts only issued certificates.
        """
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        mock_stats = {
            'total_applications': 4,
            'pending_applications': 1,
            'approved_applications': 1,
            'nocs_issued': 2,
        }
        with patch('applicants.views.get_applicant_dashboard_data', return_value=(mock_stats, [])):
            response = self.client.get(self.dashboard_url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['stats']['nocs_issued'], 2)
            self.assertContains(response, '<div class="dashboard-stat-number text-danger">2</div>')

    def test_statistics_do_not_include_records_from_other_applicants(self):
        """
        Test 6: Statistics do not include records from other applicants (strict data isolation).
        Verifies that get_applicant_dashboard_data receives strictly the authenticated user
        and that User A cannot see User B's dashboard metrics.
        """
        user_a = User.objects.create_user(
            username='applicant_a@firenoc.gov.in',
            email='applicant_a@firenoc.gov.in',
            password='ValidPassword#2026',
            first_name='ApplicantA'
        )
        user_b = User.objects.create_user(
            username='applicant_b@firenoc.gov.in',
            email='applicant_b@firenoc.gov.in',
            password='ValidPassword#2026',
            first_name='ApplicantB'
        )

        def mock_get_dashboard_data(user):
            if user == user_a:
                return ({'total_applications': 5, 'pending_applications': 2, 'approved_applications': 2, 'nocs_issued': 1}, [])
            elif user == user_b:
                return ({'total_applications': 1, 'pending_applications': 1, 'approved_applications': 0, 'nocs_issued': 0}, [])
            return ({'total_applications': 0, 'pending_applications': 0, 'approved_applications': 0, 'nocs_issued': 0}, [])

        with patch('applicants.views.get_applicant_dashboard_data', side_effect=mock_get_dashboard_data):
            # Login User A
            self.client.force_login(user_a)
            resp_a = self.client.get(self.dashboard_url)
            self.assertEqual(resp_a.status_code, 200)
            self.assertEqual(resp_a.context['stats']['total_applications'], 5)
            self.assertContains(resp_a, '<div class="dashboard-stat-number">5</div>')
            self.assertContains(resp_a, 'Welcome back, ApplicantA!')

            # Login User B
            self.client.force_login(user_b)
            resp_b = self.client.get(self.dashboard_url)
            self.assertEqual(resp_b.status_code, 200)
            self.assertEqual(resp_b.context['stats']['total_applications'], 1)
            self.assertContains(resp_b, '<div class="dashboard-stat-number">1</div>')
            self.assertNotContains(resp_b, '<div class="dashboard-stat-number">5</div>')
            self.assertContains(resp_b, 'Welcome back, ApplicantB!')

    def test_get_applicant_dashboard_data_function_fallback(self):
        """
        Test helper function get_applicant_dashboard_data returns zeros and empty list
        when Application/NOC models are not registered in the project yet.
        """
        user = User.objects.create_user(
            username='applicant_test@firenoc.gov.in',
            email='applicant_test@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        stats, recent_apps = get_applicant_dashboard_data(user)
        self.assertEqual(stats['total_applications'], 0)
        self.assertEqual(stats['pending_applications'], 0)
        self.assertEqual(stats['approved_applications'], 0)
        self.assertEqual(stats['nocs_issued'], 0)
        self.assertEqual(recent_apps, [])

    def test_recent_applications_table_rendering_with_applications(self):
        """
        Test that when applications are present in context, they render correctly with status badges.
        """
        user = User.objects.create_user(
            username='applicant_with_apps@firenoc.gov.in',
            email='applicant_with_apps@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        class MockApplication:
            def __init__(self, application_id, building_name, status, status_display, submission_date, pk=1):
                self.id = pk
                self.pk = pk
                self.application_id = application_id
                self.building_name = building_name
                self.status = status
                self._status_display = status_display
                self.submission_date = submission_date
                self.created_at = submission_date

            def get_status_display(self):
                return self._status_display

        mock_apps = [
            MockApplication(
                application_id='NOC-2026-001',
                building_name='Green Heights Plaza',
                status='APPROVED',
                status_display='Approved',
                submission_date=datetime.date(2026, 11, 1),
                pk=1,
            ),
            MockApplication(
                application_id='NOC-2026-002',
                building_name='City Center Tower',
                status='PENDING',
                status_display='Pending Review',
                submission_date=datetime.date(2026, 11, 2),
                pk=2,
            )
        ]
        mock_stats = {
            'total_applications': 2,
            'pending_applications': 1,
            'approved_applications': 1,
            'nocs_issued': 0,
        }
        with patch('applicants.views.get_applicant_dashboard_data', return_value=(mock_stats, mock_apps)):
            response = self.client.get(self.dashboard_url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'NOC-2026-001')
            self.assertContains(response, 'Green Heights Plaza')
            self.assertContains(response, 'Approved')
            self.assertContains(response, 'NOC-2026-002')
            self.assertContains(response, 'City Center Tower')
            self.assertContains(response, 'Pending Review')
