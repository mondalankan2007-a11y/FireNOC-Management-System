"""
Refresh the materialized views that back the reporting layer.

An ordinary view is always current, so nothing here touches those. A
materialized view stores its result and only changes when refreshed, which is
the trade it makes for cheap reads. Something has to perform that refresh: this
command, run on a schedule or after a bulk change.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

MATERIALIZED_VIEWS = ['mv_department_statistics']


class Command(BaseCommand):
    help = 'Refresh the reporting layer materialized views.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--actor-id', type=int, default=None,
            help='User who asked for the refresh, recorded in the audit entry. '
                 'Omitted when the command is run from the command line, where '
                 'there is no user to attribute it to.')
        parser.add_argument(
            '--blocking', action='store_true',
            help='Refresh without CONCURRENTLY, taking an exclusive lock. '
                 'Needed the first time, when the view has never been populated.')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError(
                f'Materialized views require PostgreSQL; this database is '
                f'{connection.vendor}.')

        concurrently = '' if options['blocking'] else 'CONCURRENTLY '
        for view in MATERIALIZED_VIEWS:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(f'REFRESH MATERIALIZED VIEW {concurrently}{view}')
                except Exception as exc:                        # noqa: BLE001
                    # CONCURRENTLY cannot populate a view for the first time.
                    if 'has not been populated' not in str(exc):
                        raise
                    self.stdout.write(self.style.WARNING(
                        f'  {view} was never populated; refreshing with a lock'))
                    cursor.execute(f'REFRESH MATERIALIZED VIEW {view}')
            self.stdout.write(self.style.SUCCESS(f'  refreshed {view}'))

        # One entry per refresh, whichever route performed it, so the
        # dashboard can report how fresh its figures are. The actor is passed
        # in by the caller: run from a terminal there is nobody to attribute
        # it to, and a null actor says so honestly.
        from django.contrib.auth.models import User

        from adminpanel.models import AuditLog
        from adminpanel.statistics import REFRESH_SUMMARY

        actor = None
        if options['actor_id'] is not None:
            actor = User.objects.filter(pk=options['actor_id']).first()
        AuditLog.record(AuditLog.ACTION_UPDATE, AuditLog.ENTITY_SYSTEM,
                        actor=actor, summary=REFRESH_SUMMARY)
