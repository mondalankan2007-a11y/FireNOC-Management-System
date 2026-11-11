from django.test import TestCase
from django.urls import reverse, resolve
from officers.views import officer_home


class OfficerModuleInitializationTests(TestCase):
    """
    Test suite for Commit 1 of the Fire Officer Module.
    Verifies URL routing, view rendering, template inheritance,
    and landing page content.
    """

    def setUp(self):
        self.officer_home_url = reverse('officers:officer_home')

    def test_officer_home_url_resolves(self):
        """Verify /officer/ resolves to the officer_home view function."""
        match = resolve('/officer/')
        self.assertEqual(match.func, officer_home)
        self.assertEqual(match.app_name, 'officers')
        self.assertEqual(match.url_name, 'officer_home')

    def test_officer_home_page_loads_successfully(self):
        """Verify GET /officer/ returns HTTP 200 OK."""
        response = self.client.get(self.officer_home_url)
        self.assertEqual(response.status_code, 200)

    def test_officer_home_uses_correct_templates(self):
        """Verify the view renders officer_home.html extending base.html."""
        response = self.client.get(self.officer_home_url)
        self.assertTemplateUsed(response, 'officers/officer_home.html')
        self.assertTemplateUsed(response, 'base.html')

    def test_officer_home_contains_required_content(self):
        """Verify the page contains the title, description, and status notice."""
        response = self.client.get(self.officer_home_url)
        content = response.content.decode('utf-8')

        # Heading requirement
        self.assertIn('Fire Officer Module', content)

        # Description requirement: application review, document verification, inspection, deficiency management and approval workflow
        self.assertIn(
            'application review, document verification, inspection, deficiency management and approval workflow',
            content
        )

        # Module status / coming soon requirement
        self.assertIn('Coming Soon', content)
        self.assertIn('Foundation Initialized', content)

    def test_navigation_integration(self):
        """Verify the Officer Portal is linked in navbar and home page."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.officer_home_url)
