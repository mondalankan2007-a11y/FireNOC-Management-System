from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password
from django.urls import reverse


class ApplicantAuthenticationTests(TestCase):
    """
    Comprehensive test suite for Applicant Authentication functionality:
    Registration, Login, Protected Routes, and Logout.
    """

    def setUp(self):
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.logout_url = reverse('logout')
        self.applicant_home_url = reverse('applicants:applicant_home')

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
    # Login, Protected Routes & Logout Tests
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

    def test_login_with_valid_credentials(self):
        """Scenario 1: Login with valid credentials establishes session and redirects to /applicant/."""
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
        self.assertRedirects(response, self.applicant_home_url)
        self.assertContains(response, 'Welcome back, Ankan!')
        # Verify session was created and user is authenticated
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].email, 'applicant@firenoc.gov.in')

    def test_login_with_incorrect_password(self):
        """Scenario 2: Login with incorrect password displays error and does not authenticate."""
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
        """Scenario 3: Login with an unregistered email displays invalid credentials error."""
        login_data = {
            'email': 'unknown@firenoc.gov.in',
            'password': 'SomePassword#123',
        }
        response = self.client.post(self.login_url, login_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid email address or password.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_login_with_empty_fields(self):
        """Scenario 4: Login with empty email or password displays required fields error."""
        response = self.client.post(self.login_url, {'email': '', 'password': ''}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Both email address and password are required.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_access_applicant_page_without_login(self):
        """Scenario 5: Unauthenticated access to /applicant/ redirects to /login/?next=/applicant/."""
        response = self.client.get(self.applicant_home_url)
        self.assertEqual(response.status_code, 302)
        expected_redirect = f"{self.login_url}?next={self.applicant_home_url}"
        self.assertRedirects(response, expected_redirect)

    def test_logout_successfully(self):
        """Scenario 6: Logout terminates session, redirects to /login/, and displays success message."""
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        # POST request for logout (recommended security practice)
        response = self.client.post(self.logout_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.login_url)
        self.assertContains(response, 'You have been successfully logged out.')
        self.assertFalse(response.context['user'].is_authenticated)

    def test_try_accessing_protected_page_after_logout(self):
        """Scenario 7: Accessing /applicant/ after logging out is blocked and redirects to login."""
        user = User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='ValidPassword#2026'
        )
        self.client.force_login(user)

        # Logout
        self.client.post(self.logout_url)

        # Try accessing protected page
        response = self.client.get(self.applicant_home_url)
        self.assertEqual(response.status_code, 302)
        expected_redirect = f"{self.login_url}?next={self.applicant_home_url}"
        self.assertRedirects(response, expected_redirect)
