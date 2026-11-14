import datetime
from django.db import models
from django.contrib.auth.models import User


class Application(models.Model):
    """
    Fire NOC Application submitted by an applicant.
    Captures applicant contact, building parameters, occupancy classification,
    and lifecycle status for departmental inspection and verification.
    """
    BUILDING_TYPE_CHOICES = [
        ('RESIDENTIAL', 'Residential'),
        ('COMMERCIAL', 'Commercial'),
        ('INDUSTRIAL', 'Industrial'),
        ('EDUCATIONAL', 'Educational Institution'),
        ('HOSPITAL', 'Hospital'),
        ('HOTEL', 'Hotel'),
        ('OTHER', 'Other'),
    ]

    OCCUPANCY_CHOICES = [
        ('RESIDENTIAL', 'Residential'),
        ('BUSINESS', 'Business'),
        ('ASSEMBLY', 'Assembly'),
        ('INDUSTRIAL', 'Industrial'),
        ('STORAGE', 'Storage'),
        ('EDUCATIONAL', 'Educational'),
        ('HEALTHCARE', 'Healthcare'),
        ('MIXED_USE', 'Mixed Use'),
    ]

    APPLICATION_TYPE_CHOICES = [
        ('NEW_NOC', 'New NOC'),
        ('RENEWAL', 'NOC Renewal'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('UNDER_REVIEW', 'Under Review'),
        ('DOCUMENTS_VERIFIED', 'Documents Verified / Ready for Inspection'),
        ('UNDER_INSPECTION', 'Under Inspection'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('DEFICIENT', 'Deficient'),
    ]

    # Section A: Applicant Information
    applicant = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='fire_noc_applications'
    )
    full_name = models.CharField(max_length=150)
    email = models.EmailField()
    mobile_number = models.CharField(max_length=15)

    # Section B: Building Information
    building_name = models.CharField(max_length=150)
    building_type = models.CharField(max_length=50, choices=BUILDING_TYPE_CHOICES)
    building_type_other = models.CharField(max_length=100, blank=True, default='')
    building_address = models.TextField(max_length=500)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=10)
    num_floors = models.PositiveIntegerField(help_text="Number of floors including basements")
    builtup_area = models.DecimalField(max_digits=10, decimal_places=2, help_text="Built-up area in square meters")
    year_construction = models.PositiveIntegerField(help_text="Original year of construction")
    occupancy_type = models.CharField(max_length=50, choices=OCCUPANCY_CHOICES)

    # Section C: Application Details
    application_id = models.CharField(max_length=50, unique=True, blank=True)
    application_type = models.CharField(max_length=20, choices=APPLICATION_TYPE_CHOICES, default='NEW_NOC')
    purpose = models.TextField(max_length=1000)
    remarks = models.TextField(max_length=2000, blank=True, default='')

    # Lifecycle Status
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Fire NOC Application'
        verbose_name_plural = 'Fire NOC Applications'

    def __str__(self):
        return f"{self.application_id or self.pk} - {self.building_name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if not self.application_id:
            year = datetime.date.today().year
            self.application_id = f"NOC-{year}-{self.pk:04d}"
            super().save(update_fields=['application_id'])

    @property
    def submission_date(self):
        return self.created_at.date()

    def is_ready_for_officer_recommendation(self):
        """
        Evaluate whether this application has fulfilled all prerequisites
        to be eligible for officer recommendation for approval.
        """
        from officers.models import get_recommendation_eligibility
        return get_recommendation_eligibility(self)['is_eligible']


class ApplicationDocument(models.Model):
    """
    Supporting fire safety and architectural document uploaded for an application.
    """
    DOCUMENT_TYPES = [
        ('ARCHITECTURAL_BLUEPRINT', 'Architectural Layout / Blueprint'),
        ('FIRE_SAFETY_PLAN', 'Fire Safety & Evacuation Plan'),
        ('HYDRANT_LAYOUT', 'Hydrant & Sprinkler Scheme'),
        ('EQUIPMENT_TEST_CERTIFICATE', 'Equipment Test Certificate'),
        ('OWNERSHIP_DEED', 'Building Ownership / Lease Deed'),
        ('OTHER', 'Other Supporting Document'),
    ]

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(max_length=50, choices=DOCUMENT_TYPES)
    document_name = models.CharField(max_length=255)
    file = models.FileField(upload_to='application_documents/%Y/%m/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
        verbose_name = 'Application Document'
        verbose_name_plural = 'Application Documents'

    def __str__(self):
        return f"{self.document_name} ({self.get_document_type_display()})"
