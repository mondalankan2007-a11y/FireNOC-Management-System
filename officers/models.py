from django.db import models
from django.contrib.auth.models import User


class OfficerProfile(models.Model):
    """
    Officer Profile model extending Django's built-in User model.
    Stores officer-specific metadata while leveraging Django's secure
    authentication system for password hashing, session management,
    and user credentials.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='officer_profile'
    )
    officer_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique Fire Officer ID (e.g. FO-101, FO-2026-001)"
    )
    designation = models.CharField(
        max_length=100,
        default='Fire Safety Inspection Officer',
        help_text="Official departmental designation"
    )
    badge_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Official badge number"
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Contact telephone number"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Designates whether this officer profile is currently active"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Officer Profile'
        verbose_name_plural = 'Officer Profiles'
        ordering = ['officer_id']

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"{name} ({self.officer_id})"


class DocumentVerification(models.Model):
    """
    Officer verification record for an uploaded application document.
    Maintains approval/rejection state and audit remarks without altering the source file.
    """
    VERIFICATION_STATUS_CHOICES = [
        ('PENDING', 'Pending Verification'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
    ]

    document = models.OneToOneField(
        'applicants.ApplicationDocument',
        on_delete=models.CASCADE,
        related_name='verification'
    )
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='document_verifications'
    )
    status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='PENDING'
    )
    officer_remarks = models.TextField(
        blank=True,
        default='',
        help_text="Officer observations, deficiency notes, or verification rationale"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Document Verification'
        verbose_name_plural = 'Document Verifications'

    def __str__(self):
        return f"Verification for {self.document.document_name}: {self.get_status_display()}"


class ApplicationReview(models.Model):
    """
    Preliminary Officer review record for an Application.
    Tracks review status and officer notes prior to inspection scheduling.
    """
    REVIEW_STATUS_CHOICES = [
        ('UNDER_REVIEW', 'Under Review'),
        ('DOCUMENTS_VERIFIED', 'Documents Verified / Ready for Inspection'),
    ]

    application = models.OneToOneField(
        'applicants.Application',
        on_delete=models.CASCADE,
        related_name='officer_review'
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='application_reviews'
    )
    status = models.CharField(
        max_length=30,
        choices=REVIEW_STATUS_CHOICES,
        default='UNDER_REVIEW'
    )
    officer_remarks = models.TextField(
        blank=True,
        default='',
        help_text="Desk review observations or inspection readiness remarks"
    )
    reviewed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Application Review'
        verbose_name_plural = 'Application Reviews'

    def __str__(self):
        return f"Review for {self.application.application_id}: {self.get_status_display()}"


class Inspection(models.Model):
    """
    Site inspection record for a Fire NOC application.
    Uses ForeignKey (not OneToOne) to allow re-inspection after a failed or cancelled attempt.
    """
    STATUS_SCHEDULED = 'SCHEDULED'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    # Valid state transitions (from_state -> set of allowed to_states)
    VALID_TRANSITIONS = {
        STATUS_SCHEDULED: {STATUS_IN_PROGRESS, STATUS_CANCELLED},
        STATUS_IN_PROGRESS: {STATUS_COMPLETED, STATUS_CANCELLED},
        STATUS_COMPLETED: set(),
        STATUS_CANCELLED: set(),
    }

    application = models.ForeignKey(
        'applicants.Application',
        on_delete=models.CASCADE,
        related_name='inspections'
    )
    officer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conducted_inspections',
        help_text="Officer who scheduled / is conducting the inspection"
    )
    scheduled_date = models.DateField(help_text="Date on which the site inspection is scheduled")
    scheduled_time = models.TimeField(help_text="Time at which the site inspection is scheduled")
    location = models.CharField(
        max_length=300,
        blank=True,
        default='',
        help_text="Inspection site address / location if different from application address"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    officer_remarks = models.TextField(
        blank=True,
        default='',
        help_text="Scheduling notes or general inspection remarks"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Inspection'
        verbose_name_plural = 'Inspections'
        ordering = ['scheduled_date', 'scheduled_time']

    def __str__(self):
        return (
            f"Inspection #{self.pk} — {self.application.application_id} "
            f"on {self.scheduled_date} [{self.get_status_display()}]"
        )

    def can_transition_to(self, new_status):
        """Return True if moving from current status to new_status is a valid transition."""
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())

    @property
    def is_editable(self):
        """Checklist and report can only be edited when inspection is In Progress."""
        return self.status == self.STATUS_IN_PROGRESS


class InspectionChecklistItem(models.Model):
    """
    Individual checklist item assessed during a site inspection.
    Can only be edited while the parent Inspection is In Progress.
    """
    ITEM_TYPES = [
        ('EXTINGUISHER_AVAILABLE', 'Fire extinguishers available'),
        ('EXTINGUISHER_ACCESSIBLE', 'Fire extinguishers accessible'),
        ('EXITS_AVAILABLE', 'Emergency exits available'),
        ('EXITS_UNOBSTRUCTED', 'Emergency exits unobstructed'),
        ('ALARM_INSTALLED', 'Fire alarm system installed'),
        ('ALARM_FUNCTIONAL', 'Fire alarm system functional'),
        ('EMERGENCY_LIGHTING', 'Emergency lighting available'),
        ('SAFETY_SIGNAGE', 'Fire safety signage available'),
        ('ELECTRICAL_SAFETY', 'Electrical safety provisions'),
        ('STAIRWAY_ACCESS', 'Stairways / fire escape access clear'),
        ('HYDRANT_WATER', 'Fire hydrant / water supply available'),
        ('OVERALL_COMPLIANCE', 'Overall fire safety compliance'),
    ]

    STATUS_COMPLIANT = 'COMPLIANT'
    STATUS_NON_COMPLIANT = 'NON_COMPLIANT'
    STATUS_NOT_APPLICABLE = 'NOT_APPLICABLE'

    STATUS_CHOICES = [
        (STATUS_COMPLIANT, 'Compliant'),
        (STATUS_NON_COMPLIANT, 'Non-Compliant'),
        (STATUS_NOT_APPLICABLE, 'Not Applicable'),
    ]

    inspection = models.ForeignKey(
        Inspection,
        on_delete=models.CASCADE,
        related_name='checklist_items'
    )
    item_type = models.CharField(max_length=50, choices=ITEM_TYPES)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_APPLICABLE
    )
    remarks = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Inspection Checklist Item'
        verbose_name_plural = 'Inspection Checklist Items'
        unique_together = ('inspection', 'item_type')
        ordering = ['item_type']

    def __str__(self):
        return f"{self.get_item_type_display()}: {self.get_status_display()}"


class InspectionReport(models.Model):
    """
    Final inspection report submitted by the officer when completing the inspection.
    Associated one-to-one with an Inspection.
    """
    RESULT_SATISFACTORY = 'SATISFACTORY'
    RESULT_UNSATISFACTORY = 'UNSATISFACTORY'
    RESULT_REQUIRES_RECTIFICATION = 'REQUIRES_RECTIFICATION'

    RESULT_CHOICES = [
        (RESULT_SATISFACTORY, 'Satisfactory'),
        (RESULT_UNSATISFACTORY, 'Unsatisfactory'),
        (RESULT_REQUIRES_RECTIFICATION, 'Requires Rectification'),
    ]

    inspection = models.OneToOneField(
        Inspection,
        on_delete=models.CASCADE,
        related_name='report'
    )
    overall_result = models.CharField(max_length=30, choices=RESULT_CHOICES)
    general_observations = models.TextField(
        help_text="General on-site observations recorded by the officer"
    )
    officer_remarks = models.TextField(
        blank=True,
        default='',
        help_text="Additional officer remarks or recommendations"
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Inspection Report'
        verbose_name_plural = 'Inspection Reports'

    def __str__(self):
        return (
            f"Report for Inspection #{self.inspection.pk} — "
            f"{self.get_overall_result_display()}"
        )


def create_officer_user(
    username,
    email,
    password,
    officer_id,
    first_name='',
    last_name='',
    designation='Fire Safety Inspection Officer',
    badge_number='',
    phone='',
    is_active=True
):
    """
    Convenience helper function to create a User and associated OfficerProfile
    with secure password hashing using Django's built-in PBKDF2 hasher.
    """
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        is_active=is_active
    )
    profile = OfficerProfile.objects.create(
        user=user,
        officer_id=officer_id,
        designation=designation,
        badge_number=badge_number,
        phone=phone,
        is_active=is_active
    )
    return user, profile
