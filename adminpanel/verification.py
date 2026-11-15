"""
Checking a certificate from outside the system.

Everything else in this project answers the question "what does the department
know about this application". This answers a different one, asked by someone
standing in front of a building with a printed certificate in their hand: is
this certificate real, is it still in force, and does it say what the
department recorded?

Two decisions shape the rest of this module.

The lookup needs the certificate number *and* the verification code printed on
it. The number alone would be enough to find the record, but certificate
numbers run in sequence, so anyone could walk FN/2026/00001 upwards and read
out the name, building and address of every certificate the department has
ever issued. The code is twelve characters of the keyed digest — forty-eight
bits that cannot be derived from the number — so only someone actually holding
the certificate can look it up.

A failed lookup gives one answer whether the number does not exist or the code
does not match it. Saying "that number exists but your code is wrong" would
hand back exactly the enumeration this is designed to prevent.
"""

import hmac

from django.conf import settings
from django.utils import timezone

from .models import NOC

# A certificate that is real, unexpired and unrevoked, and whose stored fields
# still match the digest recorded when it was issued.
VALID = 'VALID'
# Real, but its validity period has passed.
EXPIRED = 'EXPIRED'
# Real, but the department has withdrawn it.
REVOKED = 'REVOKED'
# Found, and the printed code matches, but the record no longer matches its
# own digest. Either the certificate or the row behind it has been changed
# since issuance.
ALTERED = 'ALTERED'
# No certificate matches what was entered.
UNKNOWN = 'UNKNOWN'


class Result:
    """
    The answer to one verification attempt.

    Carries the certificate only when the lookup succeeded, so a template
    cannot accidentally display details for a certificate the visitor did not
    prove they hold.
    """

    def __init__(self, outcome, noc=None, number='', code=''):
        self.outcome = outcome
        self.noc = noc
        self.number = number
        self.code = code

    @property
    def found(self):
        return self.noc is not None

    # Named rather than compared against strings in the template, so the
    # outcome constants stay in one place.
    @property
    def is_valid(self):
        return self.outcome == VALID

    @property
    def is_expired(self):
        return self.outcome == EXPIRED

    @property
    def is_revoked(self):
        return self.outcome == REVOKED

    @property
    def is_altered(self):
        return self.outcome == ALTERED

    @property
    def is_unknown(self):
        return self.outcome == UNKNOWN

    def __repr__(self):
        return f'<Result {self.outcome} {self.number or "-"}>'


def normalise_number(raw):
    """
    Accept a certificate number however it was typed or scanned.

    Certificate numbers contain slashes, which cannot be put in a URL path
    segment, so the scanned form uses hyphens instead: FN-2026-00001 for
    FN/2026/00001. The same function handles both, along with spaces and lower
    case from someone typing it by hand.
    """
    cleaned = (raw or '').strip().upper().replace(' ', '')
    return cleaned.replace('-', '/')


def slug_number(number):
    """The certificate number in the form that can go in a URL path."""
    return number.replace('/', '-')


def normalise_code(raw):
    """The verification code, however it was typed."""
    return (raw or '').strip().upper().replace(' ', '').replace('-', '')


def verification_path(noc):
    """The site-relative address that verifies this certificate directly."""
    return f'/verify/{slug_number(noc.noc_number)}/{noc.short_verification_code}/'


def verification_url(noc):
    """
    The full address to put in the QR code on the printed certificate.

    A printed certificate outlives the session that produced it and will be
    read by someone who was never on this site, so the address has to be
    absolute. Where the site lives is deployment information rather than
    something the code can know, which is why it comes from a setting.
    """
    return settings.SITE_BASE_URL.rstrip('/') + verification_path(noc)


def verification_form_url():
    """The address of the page where a code can be entered by hand."""
    return settings.SITE_BASE_URL.rstrip('/') + '/verify/'


def check(number, code, *, today=None):
    """
    Verify one certificate, given its number and the code printed on it.

    Expiry is judged by the dates rather than by the stored status. The status
    is maintained by a sweep that runs periodically, so between the day a
    certificate lapses and the next sweep the row still says ACTIVE; a public
    answer that called such a certificate valid would be wrong on exactly the
    day it matters.
    """
    today = today or timezone.localdate()
    number = normalise_number(number)
    code = normalise_code(code)

    if not number or not code:
        return Result(UNKNOWN, number=number, code=code)

    noc = (NOC.objects
           .select_related('application')
           .filter(noc_number=number)
           .first())

    if noc is None or not noc.short_verification_code:
        return Result(UNKNOWN, number=number, code=code)

    # compare_digest rather than ==, so a wrong code takes the same time to
    # reject however much of it was right.
    if not hmac.compare_digest(code, noc.short_verification_code):
        return Result(UNKNOWN, number=number, code=code)

    if noc.verify_integrity() is False:
        return Result(ALTERED, noc=noc, number=number, code=code)

    if noc.status == NOC.STATUS_REVOKED:
        return Result(REVOKED, noc=noc, number=number, code=code)

    if noc.valid_until < today or noc.status == NOC.STATUS_EXPIRED:
        return Result(EXPIRED, noc=noc, number=number, code=code)

    return Result(VALID, noc=noc, number=number, code=code)
