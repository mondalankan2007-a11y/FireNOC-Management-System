import hashlib
import hmac

from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

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


class NOC(models.Model):
    """
    A Fire No Objection Certificate that the department has issued.

    The class is named NOC and carries `application`, `noc_number` and
    `issued_at` deliberately: the applicant module already contains a runtime
    hook that searches the installed apps for a model with exactly those names
    (see applicants/views.py). Matching them makes the applicant dashboard
    counter and the timeline's final stage work with no change to that module.

    A certificate is a record in its own right, not a view over an approved
    application. Three things follow from that, and each corrects something
    the derived version could not do:

      - It has its own number series. A certificate number is not the
        application number: one application produces at most one certificate,
        but they are different things and the department refers to them
        separately.
      - Its dates are stored, not computed. Deriving the issue date from the
        application's last-modified timestamp means editing the application
        silently moves the certificate's issue date, and its expiry with it.
      - It can be revoked. A derived certificate exists for as long as the
        application is approved, which leaves no way to withdraw one.
    """

    STATUS_ACTIVE = 'ACTIVE'
    STATUS_EXPIRED = 'EXPIRED'
    STATUS_REVOKED = 'REVOKED'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_REVOKED, 'Revoked'),
    ]

    # Validity granted on issue, in years, by the building's occupancy type.
    # Residential buildings change least, so they are re-inspected least often.
    VALIDITY_YEARS = {
        'RESIDENTIAL': 3,
    }
    DEFAULT_VALIDITY_YEARS = 1

    NUMBER_PREFIX = 'FN'

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='nocs',
        help_text="The application this certificate was issued against"
    )
    noc_number = models.CharField(
        max_length=50,
        unique=True,
        help_text="Certificate number in its own series, e.g. FN/2026/00001"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    issued_at = models.DateTimeField(
        help_text="When the department issued this certificate")
    valid_from = models.DateField()
    valid_until = models.DateField(
        help_text="Stored at issuance rather than derived, so later edits to "
                  "the application cannot move it"
    )
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_nocs',
        help_text="Administrator who issued it; null if that account is removed"
    )
    issued_by_label = models.CharField(
        max_length=150,
        blank=True,
        default='',
        help_text="Who issued it, as text, so the record survives account deletion"
    )
    remarks = models.TextField(blank=True, default='')
    integrity_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text="Keyed digest of the certificate's own fields, written at "
                  "issuance; recomputing it detects later alteration"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-issued_at', '-pk']
        verbose_name = 'Fire NOC'
        verbose_name_plural = 'Fire NOCs'
        indexes = [
            models.Index(fields=['status', '-issued_at'], name='noc_status_issued_idx'),
            models.Index(fields=['valid_until'], name='noc_valid_until_idx'),
        ]
        constraints = [
            # One live certificate per application, while revoked ones are
            # kept. A plain unique constraint on application_id would make
            # revoking and reissuing impossible; dropping the revoked row
            # instead would destroy the record of the revocation.
            models.UniqueConstraint(
                fields=['application'],
                condition=~models.Q(status='REVOKED'),
                name='one_live_noc_per_application'),
            models.CheckConstraint(
                check=models.Q(status__in=['ACTIVE', 'EXPIRED', 'REVOKED']),
                name='noc_status_valid'),
            models.CheckConstraint(
                check=models.Q(valid_until__gt=models.F('valid_from')),
                name='noc_validity_period_positive'),
        ]

    def __str__(self):
        return f"{self.noc_number} ({self.get_status_display()})"

    # ------------------------------------------------------------------ dates

    @classmethod
    def validity_years_for(cls, occupancy_type):
        """How many years a certificate runs for a given occupancy type."""
        return cls.VALIDITY_YEARS.get(occupancy_type, cls.DEFAULT_VALIDITY_YEARS)

    @property
    def is_expired(self):
        """Whether the validity period has passed, regardless of stored status."""
        return self.valid_until < timezone.localdate()

    @property
    def is_currently_valid(self):
        """
        Whether this certificate can be relied on today.

        Status and dates are checked together on purpose. Status alone goes
        stale, because a certificate expires by the calendar passing rather
        than by anything happening in the system; dates alone would ignore a
        revocation.
        """
        return self.status == self.STATUS_ACTIVE and not self.is_expired

    @property
    def days_until_expiry(self):
        return (self.valid_until - timezone.localdate()).days

    # -------------------------------------------------------------- integrity

    def integrity_payload(self):
        """
        The exact bytes the digest is taken over.

        Each field is one that a forger would have to change to make a
        certificate say something it did not: which certificate it is, which
        application it belongs to, who it was issued to, which building it
        covers, when it was issued and how long it runs.

        The separator is a character that cannot appear in any of these
        values, so no combination of fields can be rearranged to produce the
        same payload as a different combination.
        """
        application = self.application
        return '\x1f'.join([
            self.noc_number,
            application.application_id or str(application.pk),
            application.full_name,
            application.building_name,
            application.building_address,
            application.pin_code,
            self.issued_at.isoformat(),
            self.valid_from.isoformat(),
            self.valid_until.isoformat(),
        ])

    def compute_integrity_hash(self):
        """
        A keyed digest of this certificate, using the project's secret key.

        HMAC rather than a plain hash, deliberately. A plain SHA-256 of the
        fields could be recomputed by anyone who could alter the row: change
        the expiry date, recompute the digest, store both, and the forgery
        verifies. An HMAC cannot be recomputed without the server's secret, so
        altering any field leaves a digest that no longer matches and cannot
        be repaired from outside the application.
        """
        return hmac.new(
            settings.SECRET_KEY.encode(),
            self.integrity_payload().encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_integrity(self):
        """
        Whether this certificate still matches the digest stored at issuance.

        Compared with compare_digest rather than ==, so the time taken does
        not depend on how much of the digest matched.
        """
        if not self.integrity_hash:
            return None  # issued before digests were recorded
        return hmac.compare_digest(
            self.integrity_hash, self.compute_integrity_hash())

    @property
    def short_verification_code(self):
        """The first twelve characters of the digest, for printing."""
        return self.integrity_hash[:12].upper() if self.integrity_hash else ''

    # ---------------------------------------------------------------- numbers

    @classmethod
    def next_number(cls, year=None):
        """
        The next certificate number in the series for a year.

        Numbers run FN/2026/00001 upward, restarting each year, so the series
        reads the way a departmental file reference does.

        This reads the current maximum and adds one, which two simultaneous
        callers can both do and arrive at the same answer. That race is not
        prevented here; it is caught by the unique constraint on noc_number
        and retried by issue(). Preventing it instead would mean locking the
        whole table for every issuance, which costs more than the rare retry.
        """
        year = year or timezone.localdate().year
        prefix = f'{cls.NUMBER_PREFIX}/{year}/'

        last = (cls.objects
                .filter(noc_number__startswith=prefix)
                .order_by('-noc_number')
                .values_list('noc_number', flat=True)
                .first())

        sequence = int(last.rsplit('/', 1)[1]) + 1 if last else 1
        return f'{prefix}{sequence:05d}'
