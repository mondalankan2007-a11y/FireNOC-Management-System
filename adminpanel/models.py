from django.db import models
from django.contrib.auth.models import User

from applicants.models import Application


class PinCode(models.Model):
    """
    Postal code and the city and state it belongs to.

    Resolves the transitive dependency pin_code -> city, state that would
    otherwise store the same city and state once per application.
    """
    pin_code = models.CharField(
        max_length=10,
        primary_key=True,
        help_text="Postal index number, used as the natural primary key"
    )
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)

    class Meta:
        ordering = ['pin_code']
        verbose_name = 'Pin Code'
        verbose_name_plural = 'Pin Codes'

    def __str__(self):
        return f"{self.pin_code} - {self.city}, {self.state}"


class ApplicantProfile(models.Model):
    """
    Contact details of an applicant, held once per person.

    Replaces the full_name and mobile_number columns repeated on every
    application. The email address is not duplicated here: User.email is
    already the single authoritative copy.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='applicant_profile'
    )
    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(
        max_length=15,
        blank=True,
        default='',
        help_text="Contact telephone number given on applications"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name']
        verbose_name = 'Applicant Profile'
        verbose_name_plural = 'Applicant Profiles'

    def __str__(self):
        return f"{self.full_name} ({self.user.username})"

    @property
    def email(self):
        """Authoritative email address, read from the user account."""
        return self.user.email


class Building(models.Model):
    """
    A physical building that applications are filed against.

    Replaces the nine building columns stored inline on every application, so
    that a renewal references the same building instead of duplicating its
    details. Buildings are identified by address and postal code.
    """
    name = models.CharField(max_length=150)
    address = models.TextField(max_length=500)
    pin_code = models.ForeignKey(
        PinCode,
        on_delete=models.PROTECT,
        related_name='buildings',
        help_text="City and state are reached through this reference"
    )
    building_type = models.CharField(
        max_length=50,
        choices=Application.BUILDING_TYPE_CHOICES
    )
    building_type_other = models.CharField(max_length=100, blank=True, default='')
    num_floors = models.PositiveIntegerField(
        help_text="Number of floors including basements"
    )
    builtup_area = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Built-up area in square meters"
    )
    year_construction = models.PositiveIntegerField(
        help_text="Original year of construction"
    )
    occupancy_type = models.CharField(
        max_length=50,
        choices=Application.OCCUPANCY_CHOICES
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Building'
        verbose_name_plural = 'Buildings'
        constraints = [
            # One row per physical building
            models.UniqueConstraint(
                fields=['address', 'pin_code'],
                name='unique_building_address_pin_code'
            ),
            models.CheckConstraint(
                check=models.Q(num_floors__gt=0),
                name='building_num_floors_positive'
            ),
            models.CheckConstraint(
                check=models.Q(builtup_area__gt=0),
                name='building_builtup_area_positive'
            ),
        ]

    def __str__(self):
        return f"{self.name}, {self.pin_code_id}"

    @property
    def city(self):
        """City of this building, read through its postal code."""
        return self.pin_code.city

    @property
    def state(self):
        """State of this building, read through its postal code."""
        return self.pin_code.state


class AuditLog(models.Model):
    """
    Append-only record of who changed what in the system.

    The problem statement requires the department to monitor the NOC workflow
    without manual support, which means every state change must leave a trace
    that outlives the row it describes.

    The subject of an entry is recorded as a type and an id rather than a
    foreign key, deliberately. A foreign key would either forbid deleting the
    subject or, with ON DELETE SET NULL, quietly empty the audit trail at the
    moment it matters most. Storing the identifier alongside a human-readable
    label keeps the entry meaningful after its subject is gone.
    """

    ACTION_CREATE = 'CREATE'
    ACTION_UPDATE = 'UPDATE'
    ACTION_DELETE = 'DELETE'
    ACTION_STATUS_CHANGE = 'STATUS_CHANGE'
    ACTION_ASSIGN = 'ASSIGN'
    ACTION_APPROVE = 'APPROVE'
    ACTION_REJECT = 'REJECT'
    ACTION_ISSUE = 'ISSUE'
    ACTION_REVOKE = 'REVOKE'
    ACTION_LOGIN = 'LOGIN'

    ACTION_CHOICES = [
        (ACTION_CREATE, 'Created'),
        (ACTION_UPDATE, 'Updated'),
        (ACTION_DELETE, 'Deleted'),
        (ACTION_STATUS_CHANGE, 'Status Changed'),
        (ACTION_ASSIGN, 'Assigned'),
        (ACTION_APPROVE, 'Approved'),
        (ACTION_REJECT, 'Rejected'),
        (ACTION_ISSUE, 'NOC Issued'),
        (ACTION_REVOKE, 'NOC Revoked'),
        (ACTION_LOGIN, 'Signed In'),
    ]

    ENTITY_APPLICATION = 'APPLICATION'
    ENTITY_DOCUMENT = 'DOCUMENT'
    ENTITY_INSPECTION = 'INSPECTION'
    ENTITY_DEFICIENCY = 'DEFICIENCY'
    ENTITY_NOC = 'NOC'
    ENTITY_OFFICER = 'OFFICER'
    ENTITY_APPLICANT = 'APPLICANT'
    ENTITY_BUILDING = 'BUILDING'
    ENTITY_SYSTEM = 'SYSTEM'

    ENTITY_CHOICES = [
        (ENTITY_APPLICATION, 'Application'),
        (ENTITY_DOCUMENT, 'Document'),
        (ENTITY_INSPECTION, 'Inspection'),
        (ENTITY_DEFICIENCY, 'Deficiency'),
        (ENTITY_NOC, 'Fire NOC'),
        (ENTITY_OFFICER, 'Officer'),
        (ENTITY_APPLICANT, 'Applicant'),
        (ENTITY_BUILDING, 'Building'),
        (ENTITY_SYSTEM, 'System'),
    ]

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_entries',
        help_text="Account that performed the action; null for automated actions"
    )
    actor_label = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text="Who acted, recorded as text so the entry survives account deletion"
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    entity_type = models.CharField(max_length=30, choices=ENTITY_CHOICES)
    entity_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Primary key of the subject, if it had one"
    )
    entity_label = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text="How the subject identifies itself, e.g. NOC-2026-0001"
    )
    summary = models.CharField(
        max_length=255,
        help_text="One line describing what happened"
    )
    changes = models.JSONField(
        default=dict,
        blank=True,
        help_text="Field-level detail, as {field: {'from': old, 'to': new}}"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'Audit Log Entry'
        verbose_name_plural = 'Audit Log'
        indexes = [
            # "What happened to this application?" - the entity timeline
            models.Index(fields=['entity_type', 'entity_id'],
                         name='audit_entity_idx'),
            # "What did this officer do?" - the actor timeline
            models.Index(fields=['actor', '-created_at'],
                         name='audit_actor_time_idx'),
            # "What happened today?" - the activity feed
            models.Index(fields=['action', '-created_at'],
                         name='audit_action_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(entity_id__isnull=True) | models.Q(entity_id__gt=0),
                name='audit_entity_id_positive_or_null'
            ),
        ]

    def __str__(self):
        who = self.actor_label or 'system'
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.entity_type}"

    def save(self, *args, **kwargs):
        """
        Permit inserts only.

        An audit trail that can be edited after the fact is not evidence. The
        table is append-only by design, so an attempt to modify an existing
        entry is a programming error rather than something to accommodate.
        """
        if self.pk is not None:
            raise ValueError(
                'Audit log entries are append-only and cannot be modified.'
            )
        super().save(*args, **kwargs)

    @classmethod
    def record(cls, action, entity_type, *, actor=None, entity=None,
               entity_id=None, entity_label='', summary='', changes=None,
               ip_address=None):
        """
        Write one audit entry.

        Passing `entity` fills the id and label from the object itself, which
        is what callers normally want. The label is taken from the object's own
        string form, so it reads the way the rest of the system names it.
        """
        if entity is not None:
            entity_id = entity_id if entity_id is not None else entity.pk
            entity_label = entity_label or str(entity)[:150]

        return cls.objects.create(
            actor=actor,
            actor_label=(
                (actor.get_full_name() or actor.get_username())[:150]
                if actor is not None else ''
            ),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label[:150],
            summary=summary[:255],
            changes=changes or {},
            ip_address=ip_address,
        )
