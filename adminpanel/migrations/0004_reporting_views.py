"""
Database views for the reporting layer.

The admin dashboard, the monitoring queue and the reports page all need the
same few shapes of aggregated data. Defining those shapes once in the database
keeps the SQL in one place and gives every consumer the same definition of, say,
"an application that is overdue", rather than letting each view function invent
its own.

Three ordinary views and one materialized view are created. The distinction
matters and is the point of the materialized one:

  - An ordinary view is a stored query. It is re-evaluated on every read, so it
    is always current and costs whatever its query costs.
  - A materialized view stores the result. Reads are a cheap scan of a small
    table, but the data is only as fresh as the last REFRESH.

The query plan analysis found that counting applications grouped by status is a
sequential scan that no index can help, because the answer depends on every row.
That is exactly the case a materialized view exists for: the dashboard reads a
precomputed row instead of scanning the table on every page load.

These statements are PostgreSQL-specific and are skipped on other backends, so
the SQLite development fallback keeps working without them.
"""

from django.db import migrations

APPLICATION_OVERVIEW = """
CREATE OR REPLACE VIEW v_application_overview AS
SELECT a.id                                   AS application_id,
       a.application_id                       AS reference,
       a.status,
       a.application_type,
       a.building_name,
       a.city,
       a.pin_code,
       a.builtup_area,
       a.created_at,
       u.username                             AS applicant_username,
       u.email                                AS applicant_email,
       latest.scheduled_date                  AS last_inspection_date,
       latest.status                          AS last_inspection_status,
       report.overall_result                  AS last_inspection_result,
       COALESCE(def.total, 0)                 AS deficiency_count,
       COALESCE(def.open_count, 0)            AS open_deficiency_count,
       EXTRACT(DAY FROM (NOW() - a.created_at))::int AS age_in_days
  FROM applicants_application a
  JOIN auth_user u ON u.id = a.applicant_id
  LEFT JOIN LATERAL (
       SELECT i.id, i.scheduled_date, i.status
         FROM officers_inspection i
        WHERE i.application_id = a.id
        ORDER BY i.scheduled_date DESC, i.id DESC
        LIMIT 1
  ) latest ON TRUE
  LEFT JOIN officers_inspectionreport report ON report.inspection_id = latest.id
  LEFT JOIN LATERAL (
       SELECT COUNT(*) AS total,
              COUNT(*) FILTER (WHERE d.status = 'OPEN') AS open_count
         FROM officers_deficiency d
        WHERE d.application_id = a.id
  ) def ON TRUE;
"""

OFFICER_WORKLOAD = """
CREATE OR REPLACE VIEW v_officer_workload AS
SELECT u.id                                             AS officer_user_id,
       u.username,
       COALESCE(p.officer_id, u.username)               AS officer_reference,
       p.designation,
       p.is_active,
       COUNT(DISTINCT i.id)                             AS inspections_total,
       COUNT(DISTINCT i.id) FILTER (
            WHERE i.status = 'SCHEDULED')               AS inspections_scheduled,
       COUNT(DISTINCT i.id) FILTER (
            WHERE i.status = 'COMPLETED')               AS inspections_completed,
       COUNT(DISTINCT d.id)                             AS deficiencies_raised,
       MAX(i.scheduled_date)                            AS last_inspection_date
  FROM auth_user u
  JOIN officers_officerprofile p ON p.user_id = u.id
  LEFT JOIN officers_inspection i ON i.officer_id = u.id
  LEFT JOIN officers_deficiency d ON d.reported_by_id = u.id
 GROUP BY u.id, u.username, p.officer_id, p.designation, p.is_active;
"""

DEFICIENCY_SUMMARY = """
CREATE OR REPLACE VIEW v_deficiency_summary AS
SELECT d.severity,
       d.status,
       COUNT(*)                                         AS deficiencies,
       COUNT(DISTINCT d.application_id)                 AS applications_affected,
       ROUND(AVG(EXTRACT(DAY FROM (
            COALESCE(d.resolved_at, NOW()) - d.created_at)))::numeric, 1)
                                                        AS average_days_open
  FROM officers_deficiency d
 GROUP BY d.severity, d.status;
"""

DEPARTMENT_STATISTICS = """
CREATE MATERIALIZED VIEW mv_department_statistics AS
SELECT a.status,
       COUNT(*)                                         AS applications,
       COUNT(*) FILTER (WHERE a.application_type = 'RENEWAL') AS renewals,
       ROUND(AVG(a.builtup_area), 2)                    AS average_builtup_area,
       MIN(a.created_at)                                AS oldest_submission,
       MAX(a.created_at)                                AS newest_submission
  FROM applicants_application a
 GROUP BY a.status;
"""

# A unique index is what allows REFRESH MATERIALIZED VIEW CONCURRENTLY, which
# refreshes without taking an exclusive lock on the view.
DEPARTMENT_STATISTICS_INDEX = """
CREATE UNIQUE INDEX mv_department_statistics_status_idx
    ON mv_department_statistics (status);
"""

FORWARD = [APPLICATION_OVERVIEW, OFFICER_WORKLOAD, DEFICIENCY_SUMMARY,
           DEPARTMENT_STATISTICS, DEPARTMENT_STATISTICS_INDEX]

REVERSE = [
    'DROP MATERIALIZED VIEW IF EXISTS mv_department_statistics;',
    'DROP VIEW IF EXISTS v_deficiency_summary;',
    'DROP VIEW IF EXISTS v_officer_workload;',
    'DROP VIEW IF EXISTS v_application_overview;',
]


def create_views(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for statement in FORWARD:
        schema_editor.execute(statement)


def drop_views(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for statement in REVERSE:
        schema_editor.execute(statement)


class Migration(migrations.Migration):

    dependencies = [
        # A view pins the types of the columns it selects, so auth_user must
        # have finished being altered before v_application_overview selects
        # from it. Without this, creating the test database fails with
        # "cannot alter type of a column used by a view".
        ('auth', '0012_alter_user_first_name_max_length'),
        ('adminpanel', '0003_audit_log'),
        ('applicants', '0004_add_noc_issued_status'),
        ('officers', '0006_deficiency_application_consistency'),
    ]

    operations = [
        migrations.RunPython(create_views, drop_views),
    ]
