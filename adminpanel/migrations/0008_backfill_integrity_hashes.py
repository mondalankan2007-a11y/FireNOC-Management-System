"""
Record an integrity digest for certificates issued before digests existed.

A digest written now proves only that the certificate has not changed since
this migration ran, not since it was issued. That is a weaker guarantee and
worth stating plainly rather than letting the presence of a digest imply more
than it can.

The alternative — leaving them blank — would mean verification reports
"unknown" for those certificates forever. Recording the digest at least
detects alteration from this point on, and verify_integrity() returns None for
anything still blank, so the two cases stay distinguishable.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    # The historical model has no methods, so the computation is repeated here
    # rather than imported. Keeping a migration independent of the current
    # model is the point: this must still run years from now, against whatever
    # the model has become.
    import hashlib
    import hmac

    from django.conf import settings

    NOC = apps.get_model('adminpanel', 'NOC')

    updated = []
    for noc in NOC.objects.select_related('application').filter(integrity_hash=''):
        application = noc.application
        payload = '\x1f'.join([
            noc.noc_number,
            application.application_id or str(application.pk),
            application.full_name,
            application.building_name,
            application.building_address,
            application.pin_code,
            noc.issued_at.isoformat(),
            noc.valid_from.isoformat(),
            noc.valid_until.isoformat(),
        ])
        noc.integrity_hash = hmac.new(
            settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        updated.append(noc)

    if updated:
        NOC.objects.bulk_update(updated, ['integrity_hash'], batch_size=500)
        print(f'\n  Recorded integrity digests for {len(updated)} existing '
              f'certificate(s).')


def clear(apps, schema_editor):
    apps.get_model('adminpanel', 'NOC').objects.update(integrity_hash='')


class Migration(migrations.Migration):

    dependencies = [('adminpanel', '0007_noc_integrity_hash')]

    operations = [migrations.RunPython(backfill, clear)]
