"""
Mark certificates whose validity period has passed as expired.

Intended to run daily. A certificate lapses because a date passes, which no
request triggers, so without a scheduled sweep the stored status would stay
ACTIVE indefinitely and every report would overstate how many certificates are
in force.
"""

from django.core.management.base import BaseCommand

from adminpanel import services


class Command(BaseCommand):
    help = 'Mark certificates past their validity date as expired.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would be expired without changing anything')
        parser.add_argument(
            '--renewals', action='store_true',
            help='Also list certificates approaching expiry')

    def handle(self, *args, **options):
        if options['dry_run']:
            from django.utils import timezone

            from adminpanel.models import NOC

            due = NOC.objects.filter(
                status=NOC.STATUS_ACTIVE,
                valid_until__lt=timezone.localdate()).select_related('application')
            for noc in due:
                self.stdout.write(
                    f'  would expire {noc.noc_number} '
                    f'(lapsed {noc.valid_until:%d %b %Y})')
            self.stdout.write(f'{due.count()} certificate(s) would be expired.')
        else:
            expired = services.expire_due_certificates()
            for noc in expired:
                self.stdout.write(
                    f'  expired {noc.noc_number} '
                    f'(lapsed {noc.valid_until:%d %b %Y})')
            self.stdout.write(self.style.SUCCESS(
                f'{len(expired)} certificate(s) expired.'))

        if options['renewals']:
            due = services.certificates_due_for_renewal()
            self.stdout.write('')
            self.stdout.write(
                f'Due for renewal within {services.RENEWAL_WINDOW_DAYS} days:')
            for noc in due:
                filed = ('renewal filed'
                         if services.has_renewal_application(noc)
                         else self.style.WARNING('no renewal filed'))
                self.stdout.write(
                    f'  {noc.noc_number} expires {noc.valid_until:%d %b %Y} '
                    f'({noc.days_until_expiry} days) — {filed}')
            if not due:
                self.stdout.write('  none')
