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
