"""
Measure whether the declared indexes are actually used, and what they save.

Runs EXPLAIN (ANALYZE, BUFFERS) over the queries the application issues most
often, once with index scans available and once with them disabled, and reports
the plan and execution time for each. Comparing the two is what shows whether an
index earns its place: an index the planner never chooses, or one that saves
nothing, is cost without benefit.

Synthetic rows are inserted inside a transaction that is always rolled back, so
the command measures realistic volumes without leaving anything behind. Run it
with --keep-data to inspect the rows afterwards instead.
"""

import time as _time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from adminpanel import seeding

# (label, SQL, the index this query is expected to use)
QUERIES = [
    (
        'Applicant status queue',
        """select id, application_id, building_name, status, created_at
             from applicants_application
            where status = 'PENDING'
            order by created_at desc
            limit 25""",
        'application_status_time_idx',
    ),
    (
        'Applicant status queue, selective status',
        """select id, application_id, building_name, status, created_at
             from applicants_application
            where status = 'NOC_ISSUED'
            order by created_at desc
            limit 25""",
        'application_status_time_idx',
    ),
    (
        'Dashboard counts by status',
        """select status, count(*) from applicants_application group by status""",
        'none expected: reads every row by design',
    ),
    (
        'Recent applications, unfiltered',
        """select id, application_id from applicants_application
            order by created_at desc limit 25""",
        'application_created_idx',
    ),
    (
        'Renewals only',
        """select count(*) from applicants_application
            where application_type = 'RENEWAL'""",
        'application_type_idx',
    ),
    (
        'Officer inspection queue',
        """select id, scheduled_date, status from officers_inspection
            where status in ('SCHEDULED', 'IN_PROGRESS')
            order by scheduled_date
            limit 25""",
        'inspection_status_date_idx',
    ),
    (
        'Open deficiencies, newest first',
        """select id, title, severity from officers_deficiency
            where status = 'OPEN'
            order by created_at desc
            limit 25""",
        'deficiency_status_time_idx',
    ),
]


class Command(BaseCommand):
    help = 'Compare query plans with and without the declared indexes.'

    def add_arguments(self, parser):
        parser.add_argument('--applications', type=int, default=5000)
        parser.add_argument('--keep-data', action='store_true',
                            help='Commit the synthetic rows instead of rolling back')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError(
                'Query plan analysis requires PostgreSQL; this database is '
                f'{connection.vendor}.')

        count = options['applications']
        keep = options['keep_data']

        if keep:
            self._run(count)
            return

        try:
            with transaction.atomic():
                self._run(count)
                raise seeding.Rollback()
        except seeding.Rollback:
            self.stdout.write(self.style.SUCCESS(
                '\nSynthetic rows rolled back; the database is unchanged.'))

    # ------------------------------------------------------------------ setup

    def _run(self, count):
        self.stdout.write(f'Seeding {count} applications...')
        started = _time.perf_counter()
        counts = seeding.seed(count)
        self.stdout.write(
            f"  applications={counts['applications']} "
            f"inspections={counts['inspections']} "
            f"deficiencies={counts['deficiencies']} "
            f'in {_time.perf_counter() - started:.1f}s')

        self.stdout.write('Running ANALYZE so the planner has fresh statistics...')
        with connection.cursor() as cursor:
            cursor.execute('ANALYZE applicants_application, officers_inspection, '
                           'officers_deficiency')

        self._report()

    # ----------------------------------------------------------------- report

    def _report(self):
        for label, sql, expected in QUERIES:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(label))
            self.stdout.write(f'  expected index: {expected}')

            with_idx = self._explain(sql, indexes=True)
            without_idx = self._explain(sql, indexes=False)

            self.stdout.write(f'  with indexes    : {with_idx["scan"]:<28} '
                              f'{with_idx["ms"]:.3f} ms')
            self.stdout.write(f'  without indexes : {without_idx["scan"]:<28} '
                              f'{without_idx["ms"]:.3f} ms')

            if without_idx['ms'] > 0 and with_idx['ms'] > 0:
                factor = without_idx['ms'] / with_idx['ms']
                verdict = (self.style.SUCCESS(f'  {factor:.1f}x faster with the index')
                           if factor >= 1.5 else
                           self.style.WARNING(f'  {factor:.1f}x — the index earns little here'))
                self.stdout.write(verdict)

            for line in with_idx['plan']:
                self.stdout.write(f'      {line}')

    def _explain(self, sql, *, indexes):
        with connection.cursor() as cursor:
            setting = 'on' if indexes else 'off'
            cursor.execute(f'SET LOCAL enable_indexscan = {setting}')
            cursor.execute(f'SET LOCAL enable_indexonlyscan = {setting}')
            cursor.execute(f'SET LOCAL enable_bitmapscan = {setting}')
            cursor.execute(f'EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}')
            plan = [row[0] for row in cursor.fetchall()]
            cursor.execute('SET LOCAL enable_indexscan = on')
            cursor.execute('SET LOCAL enable_indexonlyscan = on')
            cursor.execute('SET LOCAL enable_bitmapscan = on')

        ms = 0.0
        for line in plan:
            if 'Execution Time:' in line:
                ms = float(line.split('Execution Time:')[1].strip().split(' ')[0])
        scan = next(
            (s for s in ('Index Only Scan', 'Index Scan', 'Bitmap Heap Scan', 'Seq Scan')
             if any(s in line for line in plan)),
            'unknown')
        return {'plan': plan, 'ms': ms, 'scan': scan}

