"""
Figures for the admin dashboard.

Where a number comes from is a deliberate choice, not an implementation
detail, so each function below says which source it reads and why:

  - mv_department_statistics, a materialized view, for the status breakdown.
    Counting every application grouped by status is a sequential scan that no
    index improves (see docs/database/query-plans.md), so the dashboard reads
    a precomputed result and shows how fresh it is.
  - v_officer_workload and v_deficiency_summary, ordinary views, for figures
    that are cheap to compute and should always be current.
  - the ORM, for simple indexed counts.

On a database without the views — the SQLite development fallback — each
function degrades to an ORM aggregate rather than failing.
"""

from datetime import timedelta

from django.db import connection
from django.db.models import Count
from django.utils import timezone

from applicants.models import Application
from officers.models import Deficiency, Inspection, OfficerProfile

from .models import AuditLog

REFRESH_SUMMARY = 'Reporting statistics refreshed'


def _has_views():
    return connection.vendor == 'postgresql'


def _rows(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def status_breakdown():
    """
    Applications per status, from the materialized view where available.

    Returns (rows, is_precomputed) so the template can tell the reader whether
    the figures are live or as of the last refresh.
    """
    if not _has_views():
        rows = (Application.objects
                .values('status')
                .annotate(total=Count('id'))
                .order_by('-total'))
        return [(r['status'], r['total'], 0) for r in rows], False

    rows = _rows("""
        select status, applications, renewals
          from mv_department_statistics
         order by applications desc
    """)
    return rows, True


def last_refreshed_at():
    """When the materialized view was last refreshed, from the audit log."""
    entry = (AuditLog.objects
             .filter(action=AuditLog.ACTION_UPDATE, summary=REFRESH_SUMMARY)
             .order_by('-created_at')
             .first())
    return entry.created_at if entry else None


def headline_counts():
    """Totals that are cheap to count directly."""
    return {
        'applications': Application.objects.count(),
        'inspections': Inspection.objects.count(),
        'officers': OfficerProfile.objects.filter(is_active=True).count(),
        'open_deficiencies': Deficiency.objects.filter(status='OPEN').count(),
        'nocs_issued': Application.objects.filter(status='NOC_ISSUED').count(),
        'awaiting_action': Application.objects.filter(
            status__in=['PENDING', 'UNDER_REVIEW', 'DOCUMENTS_VERIFIED',
                        'UNDER_INSPECTION', 'DEFICIENT']).count(),
    }


def deficiency_summary():
    """Open deficiencies by severity, from v_deficiency_summary."""
    if not _has_views():
        rows = (Deficiency.objects
                .filter(status='OPEN')
                .values('severity')
                .annotate(total=Count('id')))
        return [(r['severity'], r['total'], None) for r in rows]

    return _rows("""
        select severity, deficiencies, average_days_open
          from v_deficiency_summary
         where status = 'OPEN'
         order by case severity
                      when 'CRITICAL' then 1
                      when 'MAJOR' then 2
                      else 3
                  end
    """)


def officer_workload(limit=5):
    """Busiest officers, from v_officer_workload."""
    if not _has_views():
        return []
    return _rows(f"""
        select username, officer_reference, inspections_total,
               inspections_scheduled, deficiencies_raised
          from v_officer_workload
         order by inspections_total desc, username
         limit {int(limit)}
    """)


def oldest_waiting(limit=5):
    """
    The applications that have waited longest without a decision.

    Read from v_application_overview, which already computes age in days and
    the open deficiency count.
    """
    if not _has_views():
        return []
    return _rows(f"""
        select reference, building_name, status, age_in_days,
               open_deficiency_count
          from v_application_overview
         where status not in ('NOC_ISSUED', 'REJECTED')
         order by age_in_days desc
         limit {int(limit)}
    """)


def recent_activity(limit=12, entity_type=None, action=None):
    """
    Latest audit entries for the dashboard feed.

    Read through the ORM rather than a view, because this is a plain indexed
    lookup on (action, created_at) or a filtered scan of a small ordered table
    — the kind of query an index already answers well.

    Entries come from two sources and read differently: the application layer
    names the user responsible, while a database trigger records that a change
    happened without being able to attribute it. The feed shows both, labelled.
    """
    entries = AuditLog.objects.select_related('actor')
    if entity_type:
        entries = entries.filter(entity_type=entity_type)
    if action:
        entries = entries.filter(action=action)
    return list(entries[:limit])


def activity_counts(days=7):
    """How many actions were recorded per action type over a recent window."""
    since = timezone.now() - timedelta(days=days)
    rows = (AuditLog.objects
            .filter(created_at__gte=since)
            .values('action')
            .annotate(total=Count('id'))
            .order_by('-total'))
    return [(r['action'], r['total']) for r in rows]
