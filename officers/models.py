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
