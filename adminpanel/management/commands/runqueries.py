"""
Execute the sample SQL queries and show their results.

The queries live in docs/database/sample-queries.sql as plain SQL rather than
as Django ORM calls, because the point of them is to demonstrate the relational
schema directly: joins, aggregates, subqueries, window functions and set
operations as an examiner would expect to see them written.

Keeping them in a file that this command runs means they cannot quietly rot —
a query that stops matching the schema fails here.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from adminpanel import seeding

QUERY_FILE = Path(settings.BASE_DIR) / 'docs' / 'database' / 'sample-queries.sql'


def parse_queries(text):
    """
    Split the .sql file into (name, demonstrates, question, sql) blocks.

    Each block starts with a `-- name:` line. Comment lines are metadata and
    are stripped from the SQL that actually runs.
    """
    blocks, current = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('-- name:'):
            if current:
                blocks.append(current)
            current = {'name': stripped[len('-- name:'):].strip(),
                       'demonstrates': '', 'question': '', 'sql': []}
        elif current is None:
            continue
        elif stripped.startswith('-- demonstrates:'):
            current['demonstrates'] = stripped[len('-- demonstrates:'):].strip()
        elif stripped.startswith('-- question:'):
            current['question'] = stripped[len('-- question:'):].strip()
        elif stripped.startswith('--'):
            continue
        else:
            current['sql'].append(line)
    if current:
        blocks.append(current)

    for block in blocks:
        block['sql'] = '\n'.join(block['sql']).strip().rstrip(';')
    return [b for b in blocks if b['sql']]


class Command(BaseCommand):
    help = 'Run the sample SQL queries against the database.'

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=0,
                            help='Seed this many synthetic applications first, '
                                 'rolled back afterwards')
        parser.add_argument('--rows', type=int, default=5,
                            help='Rows of output to show per query')
        parser.add_argument('--check-only', action='store_true',
                            help='Execute every query but print only pass/fail')

    def handle(self, *args, **options):
        if not QUERY_FILE.exists():
            raise CommandError(f'Query file not found: {QUERY_FILE}')

        queries = parse_queries(QUERY_FILE.read_text())
        self.stdout.write(f'{len(queries)} queries in {QUERY_FILE.name}\n')

        if options['seed']:
            try:
                with transaction.atomic():
                    counts = seeding.seed(options['seed'])
                    self.stdout.write(
                        f"Seeded applications={counts['applications']} "
                        f"inspections={counts['inspections']} "
                        f"deficiencies={counts['deficiencies']}\n")
                    failures = self._run_all(queries, options)
                    raise seeding.Rollback()
            except seeding.Rollback:
                self.stdout.write(self.style.SUCCESS(
                    'Synthetic rows rolled back; the database is unchanged.'))
        else:
            failures = self._run_all(queries, options)

        if failures:
            raise CommandError(f'{failures} quer{"y" if failures == 1 else "ies"} failed')
        self.stdout.write(self.style.SUCCESS(
            f'\nAll {len(queries)} queries executed successfully.'))

    def _run_all(self, queries, options):
        failures = 0
        for number, query in enumerate(queries, start=1):
            try:
                columns, rows, total = self._execute(query['sql'])
            except Exception as exc:                      # noqa: BLE001
                failures += 1
                self.stdout.write(self.style.ERROR(
                    f'\n{number:2}. {query["name"]}  FAILED'))
                self.stdout.write(f'    {str(exc).strip().splitlines()[0]}')
                continue

            if options['check_only']:
                self.stdout.write(
                    f'{number:2}. {query["name"]:<52} ok, {total} row(s)')
                continue

            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'{number:2}. {query["name"]}'))
            self.stdout.write(f'    demonstrates: {query["demonstrates"]}')
            self.stdout.write(f'    {query["question"]}')
            self._print_table(columns, rows[:options['rows']], total)
        return failures

    def _execute(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [c[0] for c in cursor.description]
            rows = cursor.fetchall()
        return columns, rows, len(rows)

    def _print_table(self, columns, rows, total):
        if not rows:
            self.stdout.write('    (no rows)')
            return
        widths = [
            min(28, max(len(str(c)), *(len(str(r[i])) for r in rows)))
            for i, c in enumerate(columns)
        ]
        header = '  '.join(str(c)[:w].ljust(w) for c, w in zip(columns, widths))
        self.stdout.write('    ' + header)
        self.stdout.write('    ' + '  '.join('-' * w for w in widths))
        for row in rows:
            self.stdout.write(
                '    ' + '  '.join(str(v)[:w].ljust(w) for v, w in zip(row, widths)))
        if total > len(rows):
            self.stdout.write(f'    ... {total} rows in total')
