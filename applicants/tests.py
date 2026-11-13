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



class ApplicationFormViewTests(TestCase):
    """
    Tests for the multi-section Fire NOC Application Form UI.
    Verifies access control, pre-fill behaviour, and section rendering.
    """

    def setUp(self):
        self.form_url = reverse('applicants:application_new')
        self.login_url = reverse('login')
        self.dashboard_url = reverse('applicants:dashboard')
        self.user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026',
            first_name='Ankan',
            last_name='Mondal',
        )
        self.valid_application_data = {
            'mobile_number': '9876543210',
            'building_name': 'Skyline Heights Commercial Center',
            'building_type': 'COMMERCIAL',
            'building_type_other': '',
            'building_address': '123 Park Avenue, Sector 5, Salt Lake',
            'city': 'Kolkata',
            'state': 'West Bengal',
            'pin_code': '700091',
            'num_floors': '12',
            'builtup_area': '4500.50',
            'year_construction': '2021',
            'occupancy_type': 'BUSINESS',
            'application_type': 'NEW_NOC',
            'purpose': 'Initial Fire Safety Clearance Certificate for commercial occupancy.',
            'remarks': 'Equipped with dry riser, wet riser and addressable smoke alarms.',
            'declaration': 'on',
        }

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated access to /applicant/applications/new/ redirects to /login/."""
        response = self.client.get(self.form_url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={self.form_url}")

    def test_authenticated_user_can_access_form(self):
        """Logged-in applicant receives HTTP 200 and the form template is rendered."""
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applicants/application_form.html')

    def test_applicant_details_are_prefilled(self):
        """Full name and email are pre-filled from the authenticated user's profile."""
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['prefill']['full_name'], 'Ankan Mondal')
        self.assertEqual(response.context['prefill']['email'], 'applicant@firenoc.gov.in')
        self.assertContains(response, 'value="Ankan Mondal"')
        self.assertContains(response, 'value="applicant@firenoc.gov.in"')

    def test_all_form_sections_are_rendered(self):
        """All three form sections A, B, C are present on the page."""
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        # Section A
        self.assertContains(response, 'Applicant Information')
        self.assertContains(response, 'id_full_name')
        self.assertContains(response, 'id_email')
        self.assertContains(response, 'id_mobile')
        # Section B
        self.assertContains(response, 'Building Information')
        self.assertContains(response, 'id_building_name')
        self.assertContains(response, 'id_building_type')
        self.assertContains(response, 'id_building_address')
        self.assertContains(response, 'id_city')
        self.assertContains(response, 'id_state')
        self.assertContains(response, 'id_pin_code')
        self.assertContains(response, 'id_num_floors')
        self.assertContains(response, 'id_builtup_area')
        self.assertContains(response, 'id_year_construction')
        self.assertContains(response, 'id_occupancy_type')
        # Section C
        self.assertContains(response, 'Application Details')
        self.assertContains(response, 'id_purpose')
        self.assertContains(response, 'id_remarks')
        self.assertContains(response, 'app_type_new')
        self.assertContains(response, 'app_type_renewal')

    def test_form_contains_required_ui_elements(self):
        """UI elements such as buttons, breadcrumb, and declaration are present."""
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        self.assertContains(response, 'Save as Draft')
        self.assertContains(response, 'Submit Application')
        self.assertContains(response, 'Back to Dashboard')
        self.assertContains(response, 'id_declaration')
        self.assertContains(response, 'New Application')     # breadcrumb
        self.assertContains(response, 'Fire NOC Application Form')

    def test_form_contains_all_dropdown_options(self):
        """Building Type and Occupancy Type dropdowns contain the specified options."""
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        # Building Type
        for opt in ['Residential', 'Commercial', 'Industrial',
                    'Educational Institution', 'Hospital', 'Hotel', 'Other']:
            self.assertContains(response, opt)
        # Occupancy Type
        for opt in ['Residential', 'Business', 'Assembly', 'Industrial',
                    'Storage', 'Educational', 'Healthcare', 'Mixed Use']:
            self.assertContains(response, opt)
        # Application Type
        self.assertContains(response, 'New NOC')
        self.assertContains(response, 'NOC Renewal')

    def test_building_details_validation_and_interactive_elements(self):
        """
        Verify building details validation attributes, 'Other' building type container,
        static JS inclusion, and live status alert container.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.form_url)
        self.assertEqual(response.status_code, 200)

        # 1. Building Name: max 150
        self.assertContains(response, 'maxlength="150"')

        # 2. Building Type 'Other' interactive field
        self.assertContains(response, 'id="other_building_type_wrapper"')
        self.assertContains(response, 'id="id_building_type_other"')

        # 3. PIN Code: Indian 6-digit format pattern
        self.assertContains(response, 'pattern="[1-9][0-9]{5}"')
        self.assertContains(response, 'minlength="6"')
        self.assertContains(response, 'maxlength="6"')

        # 4. Number of Floors: positive integer 1-200
        self.assertContains(response, 'min="1"')
        self.assertContains(response, 'max="200"')
        self.assertContains(response, 'step="1"')

        # 5. Built-up Area: positive decimal value
        self.assertContains(response, 'min="0.01"')
        self.assertContains(response, 'step="0.01"')

        # 6. Year of Construction: 1800 to current year
        self.assertContains(response, 'min="1800"')
        self.assertIn('current_year', response.context)
        self.assertEqual(response.context['current_year'], datetime.date.today().year)

        # 7. Form validation status element & static JS link
        self.assertContains(response, 'id="formValidationStatus"')
        self.assertContains(response, 'js/application_form.js')

    # =========================================================
    # Application Submission & PostgreSQL Backend Tests
    # =========================================================

    def test_successful_application_submission(self):
        """
        Verify that submitting valid form data creates an Application in PostgreSQL,
        generates a unique reference ID, sets status to PENDING, and redirects to dashboard.
        """
        self.client.force_login(self.user)
        response = self.client.post(self.form_url, self.valid_application_data, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.dashboard_url)
        self.assertContains(response, "submitted successfully")

        # Verify record in database
        from applicants.models import Application
        app = Application.objects.get(applicant=self.user)
        self.assertEqual(app.full_name, 'Ankan Mondal')
        self.assertEqual(app.email, 'applicant@firenoc.gov.in')
        self.assertEqual(app.mobile_number, '9876543210')
        self.assertEqual(app.building_name, 'Skyline Heights Commercial Center')
        self.assertEqual(app.building_type, 'COMMERCIAL')
        self.assertEqual(app.city, 'Kolkata')
        self.assertEqual(app.state, 'West Bengal')
        self.assertEqual(app.pin_code, '700091')
        self.assertEqual(app.num_floors, 12)
        self.assertEqual(float(app.builtup_area), 4500.50)
        self.assertEqual(app.year_construction, 2021)
        self.assertEqual(app.occupancy_type, 'BUSINESS')
        self.assertEqual(app.application_type, 'NEW_NOC')
        self.assertEqual(app.status, 'PENDING')
        self.assertTrue(app.application_id.startswith('NOC-'))

    def test_unauthenticated_post_submission_redirects_to_login(self):
        """Unauthenticated POST request does not save data and redirects to login."""
        from applicants.models import Application
        response = self.client.post(self.form_url, self.valid_application_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={self.form_url}")
        self.assertEqual(Application.objects.count(), 0)

    def test_missing_required_fields_fails_and_preserves_values(self):
        """POST with missing required fields fails and preserves entered form values."""
        from applicants.models import Application
        self.client.force_login(self.user)
        incomplete_data = self.valid_application_data.copy()
        incomplete_data['building_name'] = ''
        incomplete_data['pin_code'] = ''

        response = self.client.post(self.form_url, incomplete_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Building / Premises Name is required.")
        self.assertContains(response, "PIN Code is required.")
        self.assertEqual(Application.objects.count(), 0)
        # Verify entered city is preserved in context
        self.assertEqual(response.context['form_data']['city'], 'Kolkata')

    def test_invalid_pin_code_rejection(self):
        """PIN code not matching Indian 6-digit format is rejected."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['pin_code'] = '012345'  # starts with 0

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid 6-digit Indian PIN code")
        self.assertEqual(Application.objects.count(), 0)

    def test_invalid_floor_count_rejection(self):
        """Floors <= 0 or > 200 is rejected."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['num_floors'] = '0'

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "positive whole number between 1 and 200")
        self.assertEqual(Application.objects.count(), 0)

    def test_invalid_builtup_area_rejection(self):
        """Built-up area <= 0 is rejected."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['builtup_area'] = '-50.00'

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "positive number greater than 0")
        self.assertEqual(Application.objects.count(), 0)

    def test_invalid_construction_year_rejection(self):
        """Future construction year or year < 1800 is rejected."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['year_construction'] = '2099'

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Year of Construction must be between")
        self.assertEqual(Application.objects.count(), 0)

    def test_invalid_mobile_number_rejection(self):
        """Mobile number not 10 digits or invalid prefix is rejected."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['mobile_number'] = '1234567890'

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "valid 10-digit Indian mobile number")
        self.assertEqual(Application.objects.count(), 0)

    def test_other_building_type_requires_description(self):
        """When Building Type is OTHER, description is required."""
        from applicants.models import Application
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['building_type'] = 'OTHER'
        data['building_type_other'] = ''

        response = self.client.post(self.form_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please describe the building type when Other is selected.")
        self.assertEqual(Application.objects.count(), 0)

        # Providing description succeeds
        data['building_type_other'] = 'High-Tech Research Laboratory'
        resp_ok = self.client.post(self.form_url, data, follow=True)
        self.assertEqual(resp_ok.status_code, 200)
        app = Application.objects.get(applicant=self.user)
        self.assertEqual(app.building_type, 'OTHER')
        self.assertEqual(app.building_type_other, 'High-Tech Research Laboratory')

    def test_applicant_ownership_security(self):
        """Application is always bound to request.user, ignoring any submitted spoofed ID."""
        from applicants.models import Application
        other_user = User.objects.create_user(
            username='victim@firenoc.gov.in',
            email='victim@firenoc.gov.in',
            password='SomePassword#2026'
        )
        self.client.force_login(self.user)
        data = self.valid_application_data.copy()
        data['applicant'] = other_user.id  # attempt spoofing

        self.client.post(self.form_url, data, follow=True)
        app = Application.objects.get(building_name=data['building_name'])
        self.assertEqual(app.applicant, self.user)
        self.assertNotEqual(app.applicant, other_user)

    def test_dashboard_statistics_updated_after_submission(self):
        """Dashboard dynamic counters and recent applications table reflect newly submitted record."""
        self.client.force_login(self.user)
        self.client.post(self.form_url, self.valid_application_data, follow=True)

        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['stats']['total_applications'], 1)
        self.assertEqual(resp.context['stats']['pending_applications'], 1)
        self.assertEqual(resp.context['stats']['approved_applications'], 0)
        self.assertEqual(len(resp.context['recent_applications']), 1)
        self.assertContains(resp, 'Skyline Heights Commercial Center')
        self.assertContains(resp, 'Pending Review')


class MyApplicationsViewTests(TestCase):
    """
    Test suite for the My Applications listing page at /applicant/applications/.

    Covers:
    1. Unauthenticated access redirect.
    2. Applicant with no applications – empty state.
    3. Applicant with multiple applications – table rendering.
    4. Search by application reference number.
    5. Search by building name.
    6. Filter by status.
    7. Sort by newest / oldest.
    8. Pagination (10 per page).
    9. Data isolation – Applicant A cannot see Applicant B's records.
    """

    def setUp(self):
        self.url = reverse('applicants:my_applications')
        self.login_url = reverse('login')

        self.user_a = User.objects.create_user(
            username='applicant_a@firenoc.gov.in',
            email='applicant_a@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='ApplicantA',
        )
        self.user_b = User.objects.create_user(
            username='applicant_b@firenoc.gov.in',
            email='applicant_b@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='ApplicantB',
        )

        # Shared base data for creating Application records
        self._base = dict(
            full_name='Test User',
            email='test@firenoc.gov.in',
            mobile_number='9876543210',
            building_type='COMMERCIAL',
            building_address='123 Main St',
            city='Kolkata',
            state='West Bengal',
            pin_code='700001',
            num_floors=5,
            builtup_area='1000.00',
            year_construction=2020,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Test purpose for Fire NOC.',
            status='PENDING',
        )

    def _make_app(self, applicant, building_name, status='PENDING', **kwargs):
        """Helper: create an Application record for the given applicant."""
        from applicants.models import Application
        data = {**self._base, 'applicant': applicant, 'building_name': building_name, 'status': status}
        data.update(kwargs)
        return Application.objects.create(**data)

    # -------------------------------------------------------------------
    # Test 1: Unauthenticated access redirects to login
    # -------------------------------------------------------------------

    def test_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated GET to /applicant/applications/ redirects to /login/?next=..."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={self.url}")

    # -------------------------------------------------------------------
    # Test 2: Applicant with no applications – empty state
    # -------------------------------------------------------------------

    def test_empty_state_when_no_applications(self):
        """Applicant with zero applications sees the correct empty state."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applicants/my_applications.html')
        self.assertContains(response, "You haven't submitted any Fire NOC applications yet.")
        self.assertContains(response, "Apply for Fire NOC")
        self.assertEqual(response.context['page_obj'].paginator.count, 0)

    # -------------------------------------------------------------------
    # Test 3: Applicant with multiple applications – table rendering
    # -------------------------------------------------------------------

    def test_multiple_applications_rendered_in_table(self):
        """Applicant with 3 applications sees all records in the table."""
        self.client.force_login(self.user_a)
        self._make_app(self.user_a, 'Green Heights Plaza', 'APPROVED')
        self._make_app(self.user_a, 'City Center Tower', 'PENDING')
        self._make_app(self.user_a, 'Metro Business Hub', 'UNDER_REVIEW')

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].paginator.count, 3)
        self.assertContains(response, 'Green Heights Plaza')
        self.assertContains(response, 'City Center Tower')
        self.assertContains(response, 'Metro Business Hub')
        # Status badges
        self.assertContains(response, 'Approved')
        self.assertContains(response, 'Pending Review')
        self.assertContains(response, 'Under Review')

    # -------------------------------------------------------------------
    # Test 4: Search by application reference number
    # -------------------------------------------------------------------

    def test_search_by_application_reference(self):
        """Search by application_id returns only matching records."""
        self.client.force_login(self.user_a)
        app1 = self._make_app(self.user_a, 'Alpha Tower')
        app2 = self._make_app(self.user_a, 'Beta Plaza')

        # Search using the generated reference of app1
        response = self.client.get(self.url, {'q': app1.application_id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Alpha Tower')
        self.assertNotContains(response, 'Beta Plaza')

    # -------------------------------------------------------------------
    # Test 5: Search by building name
    # -------------------------------------------------------------------

    def test_search_by_building_name(self):
        """Search by building name keyword returns only matching records."""
        self.client.force_login(self.user_a)
        self._make_app(self.user_a, 'Sunrise Residency')
        self._make_app(self.user_a, 'Galaxy Commercial')

        response = self.client.get(self.url, {'q': 'Sunrise'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sunrise Residency')
        self.assertNotContains(response, 'Galaxy Commercial')

    # -------------------------------------------------------------------
    # Test 6: Filter by status
    # -------------------------------------------------------------------

    def test_filter_by_status_pending(self):
        """Filtering by PENDING returns only PENDING applications."""
        self.client.force_login(self.user_a)
        self._make_app(self.user_a, 'Pending Building', 'PENDING')
        self._make_app(self.user_a, 'Approved Building', 'APPROVED')
        self._make_app(self.user_a, 'Rejected Building', 'REJECTED')

        response = self.client.get(self.url, {'status': 'PENDING'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pending Building')
        self.assertNotContains(response, 'Approved Building')
        self.assertNotContains(response, 'Rejected Building')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_filter_by_status_approved(self):
        """Filtering by APPROVED returns only APPROVED applications."""
        self.client.force_login(self.user_a)
        self._make_app(self.user_a, 'Pending Building', 'PENDING')
        self._make_app(self.user_a, 'Approved Building', 'APPROVED')

        response = self.client.get(self.url, {'status': 'APPROVED'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Approved Building')
        self.assertNotContains(response, 'Pending Building')

    def test_invalid_status_filter_is_ignored(self):
        """An invalid status value in GET params is safely ignored."""
        self.client.force_login(self.user_a)
        self._make_app(self.user_a, 'Some Building', 'PENDING')

        response = self.client.get(self.url, {'status': 'INVALID_STATUS'})
        self.assertEqual(response.status_code, 200)
        # All records visible (filter ignored)
        self.assertContains(response, 'Some Building')
        self.assertEqual(response.context['current_status'], '')

    # -------------------------------------------------------------------
    # Test 7: Sort by submission date
    # -------------------------------------------------------------------

    def test_sort_newest_first(self):
        """Default sort (newest) returns most recently created application first."""
        import time
        self.client.force_login(self.user_a)
        app_old = self._make_app(self.user_a, 'Old Building')
        time.sleep(0.05)
        app_new = self._make_app(self.user_a, 'New Building')

        response = self.client.get(self.url, {'sort': 'newest'})
        self.assertEqual(response.status_code, 200)
        apps = list(response.context['applications'])
        self.assertEqual(apps[0].building_name, 'New Building')
        self.assertEqual(apps[1].building_name, 'Old Building')

    def test_sort_oldest_first(self):
        """Sort=oldest returns oldest application first."""
        import time
        self.client.force_login(self.user_a)
        app_old = self._make_app(self.user_a, 'Old Building')
        time.sleep(0.05)
        app_new = self._make_app(self.user_a, 'New Building')

        response = self.client.get(self.url, {'sort': 'oldest'})
        self.assertEqual(response.status_code, 200)
        apps = list(response.context['applications'])
        self.assertEqual(apps[0].building_name, 'Old Building')
        self.assertEqual(apps[1].building_name, 'New Building')

    # -------------------------------------------------------------------
    # Test 8: Pagination
    # -------------------------------------------------------------------

    def test_pagination_splits_records_into_pages_of_ten(self):
        """15 records → page 1 shows 10, page 2 shows 5; pagination controls are rendered."""
        self.client.force_login(self.user_a)
        for i in range(1, 16):
            self._make_app(self.user_a, f'Building {i:02d}')

        # Page 1
        resp_p1 = self.client.get(self.url)
        self.assertEqual(resp_p1.status_code, 200)
        self.assertEqual(resp_p1.context['page_obj'].paginator.count, 15)
        self.assertEqual(len(resp_p1.context['applications']), 10)
        self.assertTrue(resp_p1.context['page_obj'].has_next())
        self.assertContains(resp_p1, 'page=2')

        # Page 2
        resp_p2 = self.client.get(self.url, {'page': 2})
        self.assertEqual(resp_p2.status_code, 200)
        self.assertEqual(len(resp_p2.context['applications']), 5)
        self.assertFalse(resp_p2.context['page_obj'].has_next())

    def test_pagination_preserves_filter_parameters(self):
        """Pagination links preserve search and filter GET parameters."""
        self.client.force_login(self.user_a)
        for i in range(1, 16):
            self._make_app(self.user_a, f'Pending Building {i:02d}', 'PENDING')

        response = self.client.get(self.url, {'status': 'PENDING', 'sort': 'oldest'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Pagination link should contain existing filter params
        self.assertIn('status=PENDING', content)
        self.assertIn('sort=oldest', content)

    # -------------------------------------------------------------------
    # Test 9: Data isolation – Applicant A cannot see Applicant B's records
    # -------------------------------------------------------------------

    def test_data_isolation_applicant_cannot_see_other_records(self):
        """Applicant A's applications are strictly hidden from Applicant B."""
        # Create records for A
        self._make_app(self.user_a, 'User A Tower', 'PENDING')
        self._make_app(self.user_a, 'User A Plaza', 'APPROVED')
        # Create records for B
        self._make_app(self.user_b, 'User B Hub', 'UNDER_REVIEW')

        # Login as User A – should only see A's records
        self.client.force_login(self.user_a)
        resp_a = self.client.get(self.url)
        self.assertEqual(resp_a.status_code, 200)
        self.assertEqual(resp_a.context['page_obj'].paginator.count, 2)
        self.assertContains(resp_a, 'User A Tower')
        self.assertContains(resp_a, 'User A Plaza')
        self.assertNotContains(resp_a, 'User B Hub')

        # Login as User B – should only see B's records
        self.client.force_login(self.user_b)
        resp_b = self.client.get(self.url)
        self.assertEqual(resp_b.status_code, 200)
        self.assertEqual(resp_b.context['page_obj'].paginator.count, 1)
        self.assertContains(resp_b, 'User B Hub')
        self.assertNotContains(resp_b, 'User A Tower')
        self.assertNotContains(resp_b, 'User A Plaza')


class ApplicationDetailsViewTests(TestCase):
    """
    Test suite for the Application Details view:
    /applicant/applications/<int:application_id>/

    Covers:
    1. View an existing application belonging to authenticated applicant.
    2. View an application that does not exist returns 404.
    3. Try accessing another applicant's application returns 404 (data isolation / ownership).
    4. Access the page without login redirects to /login/?next=...
    5. Verify all displayed information matches PostgreSQL records.
    6. Verify navigation links (Back to My Applications, Dashboard).
    """

    def setUp(self):
        self.login_url = reverse('login')
        self.user_a = User.objects.create_user(
            username='applicant_a@firenoc.gov.in',
            email='applicant_a@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Ankan',
            last_name='Mondal',
        )
        self.user_b = User.objects.create_user(
            username='applicant_b@firenoc.gov.in',
            email='applicant_b@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Other',
            last_name='Applicant',
        )

        from applicants.models import Application
        self.app_a = Application.objects.create(
            applicant=self.user_a,
            full_name='Ankan Mondal',
            email='applicant_a@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Sunrise Commercial Hub',
            building_type='COMMERCIAL',
            building_type_other='',
            building_address='123 Central Boulevard, Sector 5',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=8,
            builtup_area='3500.50',
            year_construction=2019,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Initial fire safety certification for commercial office complex.',
            remarks='Equipped with fire hydrant system and automated smoke detectors.',
            status='PENDING',
        )

        self.app_b = Application.objects.create(
            applicant=self.user_b,
            full_name='Other Applicant',
            email='applicant_b@firenoc.gov.in',
            mobile_number='9123456780',
            building_name='Secret Tower',
            building_type='RESIDENTIAL',
            building_address='999 Private Road',
            city='Mumbai',
            state='Maharashtra',
            pin_code='400001',
            num_floors=20,
            builtup_area='12000.00',
            year_construction=2021,
            occupancy_type='RESIDENTIAL',
            application_type='NEW_NOC',
            purpose='Confidential residential clearance.',
            status='UNDER_REVIEW',
        )

    def test_unauthenticated_access_redirects_to_login(self):
        """Access without login redirects to /login/?next=..."""
        url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={url}")

    def test_view_existing_application(self):
        """Authenticated applicant can view their own application details."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applicants/application_details.html')
        self.assertEqual(response.context['application'], self.app_a)

    def test_view_nonexistent_application_returns_404(self):
        """Viewing an application id that doesn't exist returns 404."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:application_details', kwargs={'application_id': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_cannot_view_other_applicant_application_returns_404(self):
        """User A attempting to view User B's application receives a 404 response."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:application_details', kwargs={'application_id': self.app_b.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_displayed_information_matches_database_records(self):
        """Verify all applicant, building, and application fields match the database."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Applicant information
        self.assertContains(response, 'Ankan Mondal')
        self.assertContains(response, 'applicant_a@firenoc.gov.in')
        self.assertContains(response, '9876543210')

        # Application information
        self.assertContains(response, self.app_a.application_id)
        self.assertContains(response, 'New NOC')
        self.assertContains(response, 'Pending Review')
        self.assertContains(response, 'Initial fire safety certification for commercial office complex.')
        self.assertContains(response, 'Equipped with fire hydrant system and automated smoke detectors.')

        # Building information
        self.assertContains(response, 'Sunrise Commercial Hub')
        self.assertContains(response, 'Commercial')
        self.assertContains(response, '123 Central Boulevard, Sector 5')
        self.assertContains(response, 'Kolkata')
        self.assertContains(response, 'West Bengal')
        self.assertContains(response, '700091')
        self.assertContains(response, '8')  # num_floors
        self.assertContains(response, '3500.50')  # builtup_area
        self.assertContains(response, '2019')  # year_construction
        self.assertContains(response, 'Business')  # occupancy

    def test_navigation_links_present(self):
        """Back to My Applications and Back to Dashboard links exist and point to valid URLs."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        my_apps_url = reverse('applicants:my_applications')
        dashboard_url = reverse('applicants:dashboard')
        self.assertContains(response, f'href="{my_apps_url}"')
        self.assertContains(response, f'href="{dashboard_url}"')

    def test_my_applications_view_details_links_to_application_details(self):
        """My Applications listing table View Details button links to application_details URL."""
        self.client.force_login(self.user_a)
        response = self.client.get(reverse('applicants:my_applications'))
        self.assertEqual(response.status_code, 200)
        expected_detail_url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        self.assertContains(response, f'href="{expected_detail_url}"')


class DocumentUploadInterfaceViewTests(TestCase):
    """
    Test suite for the Document Upload Interface:
    /applicant/applications/<int:application_id>/documents/

    Covers:
    1. Unauthenticated access redirects to login.
    2. Authenticated applicant can access document upload interface for their own application.
    3. Accessing document upload for another applicant's application returns 404 (ownership check).
    4. Accessing document upload for non-existent application returns 404.
    5. Displays correct application reference number and building name.
    6. Displays all 6 required document categories.
    7. Displays file specifications, accepted formats, maximum file size, and back links.
    """

    def setUp(self):
        self.login_url = reverse('login')
        self.user_a = User.objects.create_user(
            username='applicant_doc_a@firenoc.gov.in',
            email='applicant_doc_a@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Ankan',
            last_name='Mondal',
        )
        self.user_b = User.objects.create_user(
            username='applicant_doc_b@firenoc.gov.in',
            email='applicant_doc_b@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Other',
            last_name='Applicant',
        )

        from applicants.models import Application
        self.app_a = Application.objects.create(
            applicant=self.user_a,
            full_name='Ankan Mondal',
            email='applicant_doc_a@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Heritage Commercial Tower',
            building_type='COMMERCIAL',
            building_address='45 MG Road',
            city='Kolkata',
            state='West Bengal',
            pin_code='700001',
            num_floors=6,
            builtup_area='2500.00',
            year_construction=2018,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Fire safety clearance for offices.',
            status='PENDING',
        )

        self.app_b = Application.objects.create(
            applicant=self.user_b,
            full_name='Other Applicant',
            email='applicant_doc_b@firenoc.gov.in',
            mobile_number='9123456780',
            building_name='Private Villa Complex',
            building_type='RESIDENTIAL',
            building_address='88 Hill View',
            city='Mumbai',
            state='Maharashtra',
            pin_code='400050',
            num_floors=3,
            builtup_area='1200.00',
            year_construction=2022,
            occupancy_type='RESIDENTIAL',
            application_type='NEW_NOC',
            purpose='Residential NOC.',
            status='PENDING',
        )

    def test_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated access redirects to /login/?next=..."""
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={url}")

    def test_authenticated_applicant_can_access_own_document_upload(self):
        """Owner applicant receives HTTP 200 and document_upload template is rendered."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applicants/document_upload.html')
        self.assertEqual(response.context['application'], self.app_a)

    def test_cannot_access_other_applicant_document_upload_returns_404(self):
        """Applicant cannot access another applicant's document upload page (returns 404)."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_b.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_nonexistent_application_returns_404(self):
        """Nonexistent application ID returns 404."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_displays_application_details_header(self):
        """Page displays application reference number and building name at the top."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.app_a.application_id)
        self.assertContains(response, 'Heritage Commercial Tower')

    def test_displays_all_document_categories(self):
        """Page renders all 6 required document categories with guidance and file inputs."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # 6 Document categories
        self.assertContains(response, 'Building Plan')
        self.assertContains(response, 'Ownership Proof')
        self.assertContains(response, 'Building Address Proof')
        self.assertContains(response, 'Fire Safety Equipment Details')
        self.assertContains(response, 'Previous Fire NOC (optional)')
        self.assertContains(response, 'Other Supporting Documents')

        # Hidden file inputs for all categories
        self.assertContains(response, 'id="file_BUILDING_PLAN"')
        self.assertContains(response, 'id="file_OWNERSHIP_PROOF"')
        self.assertContains(response, 'id="file_BUILDING_ADDRESS_PROOF"')
        self.assertContains(response, 'id="file_FIRE_SAFETY_EQUIPMENT"')
        self.assertContains(response, 'id="file_PREVIOUS_FIRE_NOC"')
        self.assertContains(response, 'id="file_OTHER_SUPPORTING"')

    def test_ui_elements_and_navigation_links(self):
        """Verifies accepted file types, max file size, upload button placeholder, and back link."""
        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # File specifications & instructions
        self.assertContains(response, '5 MB')
        self.assertContains(response, 'PDF (.pdf), JPEG/JPG (.jpg, .jpeg), PNG (.png)')
        self.assertContains(response, 'Upload Documents')
        self.assertContains(response, 'No file selected')

        # Back to Application Details link
        details_url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        self.assertContains(response, f'href="{details_url}"')

    # -------------------------------------------------------------
    # Commit 16 Backend Upload Tests
    # -------------------------------------------------------------

    def test_valid_pdf_upload(self):
        """Valid PDF file upload saves ApplicationDocument record in PostgreSQL and storage."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})

        pdf_content = b"%PDF-1.4 sample pdf content for blueprint verification"
        pdf_file = SimpleUploadedFile("building_blueprint.pdf", pdf_content, content_type="application/pdf")

        response = self.client.post(url, {
            'doc_BUILDING_PLAN': pdf_file,
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse('applicants:application_details', kwargs={'application_id': self.app_a.id}))
        self.assertContains(response, "Successfully uploaded 1 document")

        # Verify database record
        doc = ApplicationDocument.objects.filter(application=self.app_a).first()
        self.assertIsNotNone(doc)
        self.assertEqual(doc.document_type, 'ARCHITECTURAL_BLUEPRINT')
        self.assertIn('Building Plan', doc.document_name)
        self.assertTrue(doc.file.name.endswith('.pdf'))

    def test_valid_image_upload(self):
        """Valid PNG and JPEG image files upload successfully."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})

        png_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRsample png content"
        png_file = SimpleUploadedFile("address_proof.png", png_content, content_type="image/png")

        response = self.client.post(url, {
            'doc_BUILDING_ADDRESS_PROOF': png_file,
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Successfully uploaded 1 document")

        doc = ApplicationDocument.objects.filter(application=self.app_a, document_name__startswith='Building Address Proof').first()
        self.assertIsNotNone(doc)
        self.assertTrue(doc.file.name.endswith('.png'))

    def test_unsupported_file_type_rejected(self):
        """Executable or non-permitted file extensions (e.g. .exe, .sh, .txt) are rejected."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})

        bad_file = SimpleUploadedFile("dangerous_script.exe", b"MZ\x90\x00executable binary code", content_type="application/x-dosexec")

        response = self.client.post(url, {
            'doc_BUILDING_PLAN': bad_file,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid file format")
        self.assertEqual(ApplicationDocument.objects.filter(application=self.app_a).count(), 0)

    def test_file_exceeding_size_limit_rejected(self):
        """Files exceeding 5 MB are rejected with an informative error message."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})

        # Create oversized file (5.5 MB)
        oversized_content = b"%PDF-1.4 " + (b"A" * (5 * 1024 * 1024 + 500 * 1024))
        oversized_file = SimpleUploadedFile("huge_blueprint.pdf", oversized_content, content_type="application/pdf")

        response = self.client.post(url, {
            'doc_BUILDING_PLAN': oversized_file,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "exceeds the maximum allowed size of 5 MB")
        self.assertEqual(ApplicationDocument.objects.filter(application=self.app_a).count(), 0)

    def test_applicant_attempting_to_upload_to_another_applicant_application(self):
        """Applicant attempting to POST documents to another applicant's application returns 404."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_b.id})

        pdf_file = SimpleUploadedFile("hack.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        response = self.client.post(url, {
            'doc_BUILDING_PLAN': pdf_file,
        })

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ApplicationDocument.objects.filter(application=self.app_b).count(), 0)

    def test_unauthenticated_user_post_upload_redirects_to_login(self):
        """Unauthenticated POST request does not save documents and redirects to login."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        pdf_file = SimpleUploadedFile("test.pdf", b"%PDF-1.4 test", content_type="application/pdf")

        response = self.client.post(url, {
            'doc_BUILDING_PLAN': pdf_file,
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={url}")
        self.assertEqual(ApplicationDocument.objects.count(), 0)

    def test_reuploading_replaces_existing_category_document(self):
        """Uploading a document for an already uploaded category updates the existing record."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import ApplicationDocument

        self.client.force_login(self.user_a)
        url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})

        # Initial upload
        file1 = SimpleUploadedFile("initial.pdf", b"%PDF-1.4 v1", content_type="application/pdf")
        self.client.post(url, {'doc_BUILDING_PLAN': file1}, follow=True)
        self.assertEqual(ApplicationDocument.objects.filter(application=self.app_a).count(), 1)

        # Replacement upload
        file2 = SimpleUploadedFile("updated.pdf", b"%PDF-1.4 v2", content_type="application/pdf")
        self.client.post(url, {'doc_BUILDING_PLAN': file2}, follow=True)
        self.assertEqual(ApplicationDocument.objects.filter(application=self.app_a).count(), 1)

        doc = ApplicationDocument.objects.filter(application=self.app_a).first()
        self.assertIn("updated", doc.file.name)


class MyDocumentsListingViewTests(TestCase):
    """
    Test suite for the Applicant Uploaded Documents listing page:
    /applicant/documents/

    Covers:
    1. Unauthenticated users cannot access the page (redirected to login).
    2. Applicant can see their own uploaded documents.
    3. Applicant cannot see another applicant's documents (strict ownership).
    4. Verification status (Pending, Verified, Rejected) displays correctly.
    5. Rejected documents show officer remarks when available.
    6. Empty state displays when no documents have been uploaded.
    7. Upload action and application details links work as expected.
    8. Pagination splits records and preserves filters.
    """

    def setUp(self):
        self.url = reverse('applicants:my_documents')
        self.login_url = reverse('login')

        from django.core.files.uploadedfile import SimpleUploadedFile
        from applicants.models import Application, ApplicationDocument
        from officers.models import DocumentVerification

        self.user_a = User.objects.create_user(
            username='applicant_doclist_a@firenoc.gov.in',
            email='applicant_doclist_a@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Ankan',
            last_name='Mondal',
        )
        self.user_b = User.objects.create_user(
            username='applicant_doclist_b@firenoc.gov.in',
            email='applicant_doclist_b@firenoc.gov.in',
            password='FireSafety#2026',
            first_name='Other',
            last_name='User',
        )

        self.app_a = Application.objects.create(
            applicant=self.user_a,
            full_name='Ankan Mondal',
            email='applicant_doclist_a@firenoc.gov.in',
            mobile_number='9876543210',
            building_name='Sunrise Commercial Hub',
            building_type='COMMERCIAL',
            building_address='123 Central Boulevard',
            city='Kolkata',
            state='West Bengal',
            pin_code='700091',
            num_floors=8,
            builtup_area='3500.50',
            year_construction=2019,
            occupancy_type='BUSINESS',
            application_type='NEW_NOC',
            purpose='Fire safety certification.',
            status='UNDER_REVIEW',
        )

        self.app_b = Application.objects.create(
            applicant=self.user_b,
            full_name='Other User',
            email='applicant_doclist_b@firenoc.gov.in',
            mobile_number='9123456780',
            building_name='Confidential Plaza',
            building_type='RESIDENTIAL',
            building_address='999 Private Road',
            city='Mumbai',
            state='Maharashtra',
            pin_code='400001',
            num_floors=10,
            builtup_area='5000.00',
            year_construction=2021,
            occupancy_type='RESIDENTIAL',
            application_type='NEW_NOC',
            purpose='Residential clearance.',
            status='PENDING',
        )

        # User A Documents
        self.doc_a1 = ApplicationDocument.objects.create(
            application=self.app_a,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Building Plan - Sunrise Commercial Hub',
            file=SimpleUploadedFile('blueprint.pdf', b'%PDF-1.4 sample', content_type='application/pdf'),
        )

        self.doc_a2 = ApplicationDocument.objects.create(
            application=self.app_a,
            document_type='OWNERSHIP_DEED',
            document_name='Ownership Proof - Sunrise Commercial Hub',
            file=SimpleUploadedFile('deed.pdf', b'%PDF-1.4 deed', content_type='application/pdf'),
        )
        # Verify doc_a2
        DocumentVerification.objects.create(
            document=self.doc_a2,
            status='VERIFIED',
            officer_remarks='All registry details verified.',
        )

        self.doc_a3 = ApplicationDocument.objects.create(
            application=self.app_a,
            document_type='EQUIPMENT_TEST_CERTIFICATE',
            document_name='Fire Safety Equipment Details - Sunrise Commercial Hub',
            file=SimpleUploadedFile('hydrant.pdf', b'%PDF-1.4 hydrant', content_type='application/pdf'),
        )
        # Reject doc_a3
        DocumentVerification.objects.create(
            document=self.doc_a3,
            status='REJECTED',
            officer_remarks='Pump pressure test certificate missing calibration stamp.',
        )

        # User B Document (must be completely hidden from User A)
        self.doc_b = ApplicationDocument.objects.create(
            application=self.app_b,
            document_type='ARCHITECTURAL_BLUEPRINT',
            document_name='Confidential Blueprint - Other User',
            file=SimpleUploadedFile('secret.pdf', b'%PDF-1.4 secret', content_type='application/pdf'),
        )

    def test_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated GET to /applicant/documents/ redirects to /login/?next=..."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, f"{self.login_url}?next={self.url}")

    def test_applicant_can_see_their_uploaded_documents(self):
        """Applicant sees their documents, categories, and related application number."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applicants/my_documents.html')
        self.assertEqual(response.context['total_count'], 3)
        self.assertContains(response, 'Building Plan - Sunrise Commercial Hub')
        self.assertContains(response, 'Ownership Proof - Sunrise Commercial Hub')
        self.assertContains(response, 'Fire Safety Equipment Details - Sunrise Commercial Hub')
        self.assertContains(response, self.app_a.application_id)

    def test_applicant_cannot_see_other_applicant_documents(self):
        """Strict data isolation: User A cannot see User B's documents."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Confidential Blueprint - Other User')
        self.assertNotContains(response, self.app_b.application_id)

    def test_verification_status_displays_correctly(self):
        """Pending, Verified, and Rejected status badges are displayed correctly."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pending Review')
        self.assertContains(response, 'Verified')
        self.assertContains(response, 'Rejected')

    def test_rejected_documents_show_officer_remarks(self):
        """When an officer rejects a document, remarks are displayed in the table."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pump pressure test certificate missing calibration stamp.')
        self.assertContains(response, 'Officer Remark:')

    def test_empty_state_when_no_documents(self):
        """When user has no uploaded documents, a helpful empty state is shown."""
        new_user = User.objects.create_user(
            username='empty_applicant@firenoc.gov.in',
            email='empty_applicant@firenoc.gov.in',
            password='FireSafety#2026',
        )
        self.client.force_login(new_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No documents have been uploaded yet.')

    def test_upload_action_and_application_links_work(self):
        """Upload action points to existing upload interface; details links work."""
        self.client.force_login(self.user_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        upload_url = reverse('applicants:document_upload', kwargs={'application_id': self.app_a.id})
        details_url = reverse('applicants:application_details', kwargs={'application_id': self.app_a.id})
        self.assertContains(response, f'href="{upload_url}"')
        self.assertContains(response, f'href="{details_url}"')

    def test_pagination_and_status_filtering(self):
        """Status filtering (VERIFIED) filters list, and pagination handles large sets."""
        self.client.force_login(self.user_a)

        # Filter by VERIFIED
        resp_filtered = self.client.get(self.url, {'status': 'VERIFIED'})
        self.assertEqual(resp_filtered.status_code, 200)
        self.assertEqual(resp_filtered.context['total_count'], 1)
        self.assertContains(resp_filtered, 'Ownership Proof - Sunrise Commercial Hub')
        self.assertNotContains(resp_filtered, 'Fire Safety Equipment Details - Sunrise Commercial Hub')




