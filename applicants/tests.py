from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password
from django.urls import reverse


class ApplicantRegistrationTests(TestCase):
    """
    Comprehensive test suite for Applicant Registration functionality.
    Validates form constraints, user creation, password hashing, and error flows.
    """

    def setUp(self):
        self.register_url = reverse('register')
        self.login_url = reverse('login')
        self.valid_data = {
            'full_name': 'Ankan Mondal',
            'email': 'applicant@firenoc.gov.in',
            'mobile_number': '9876543210',
            'password': 'FireSafety#2026',
            'confirm_password': 'FireSafety#2026',
        }

    def test_registration_page_loads(self):
        """Verify the registration page renders with HTTP 200."""
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Applicant Registration')
        self.assertContains(response, 'Fire Safety Compliance Portal')

    def test_successful_registration(self):
        """Case 1: Successful registration creates user, hashes password, and redirects to login."""
        response = self.client.post(self.register_url, self.valid_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, self.login_url)
        self.assertContains(response, 'Registration successful!')

        # Verify user in database
        user = User.objects.get(email='applicant@firenoc.gov.in')
        self.assertEqual(user.first_name, 'Ankan')
        self.assertEqual(user.last_name, 'Mondal')
        self.assertEqual(user.username, 'applicant@firenoc.gov.in')
        self.assertTrue(check_password('FireSafety#2026', user.password))
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))

    def test_missing_required_fields(self):
        """Case 2: Missing required fields displays error messages."""
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

    def test_invalid_email(self):
        """Case 3: Invalid email format is rejected."""
        data = self.valid_data.copy()
        data['email'] = 'not-an-email'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a valid email address.')
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_email(self):
        """Case 4: Registering with an existing email is rejected."""
        # Create initial user
        User.objects.create_user(
            username='applicant@firenoc.gov.in',
            email='applicant@firenoc.gov.in',
            password='InitialPassword123#'
        )

        response = self.client.post(self.register_url, self.valid_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(User.objects.filter(email='applicant@firenoc.gov.in').count(), 1)

    def test_password_mismatch(self):
        """Case 5: Passwords that do not match are rejected."""
        data = self.valid_data.copy()
        data['confirm_password'] = 'DifferentPassword#2026'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match.')
        self.assertEqual(User.objects.count(), 0)

    def test_weak_password(self):
        """Case 6: Weak password fails Django built-in password validators."""
        data = self.valid_data.copy()
        data['password'] = '123'
        data['confirm_password'] = '123'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'at least 8 characters')
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_mobile_number(self):
        """Case 7: Non-10-digit mobile number is rejected."""
        data = self.valid_data.copy()
        data['mobile_number'] = '12345'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a valid 10-digit mobile number.')
        self.assertEqual(User.objects.count(), 0)

    def test_form_values_preserved_except_password(self):
        """Verify safe submitted values are preserved on error, while passwords are never leaked."""
        data = self.valid_data.copy()
        data['confirm_password'] = 'MismatchPassword#2026'
        response = self.client.post(self.register_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Ankan Mondal"')
        self.assertContains(response, 'value="applicant@firenoc.gov.in"')
        self.assertContains(response, 'value="9876543210"')
        # Passwords must NEVER appear in HTML
        self.assertNotContains(response, 'FireSafety#2026')
        self.assertNotContains(response, 'MismatchPassword#2026')
