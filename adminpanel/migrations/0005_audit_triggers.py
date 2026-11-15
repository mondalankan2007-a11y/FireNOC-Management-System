"""
Database triggers that record every status change in the audit log.

The audit log can be written from Python, and later work does exactly that for
actions the admin module performs. That only covers changes that go through the
application. A status altered by a data migration, a management command, a bulk
update or someone at a psql prompt leaves no trace at all.

A trigger closes that gap, because it fires inside the database regardless of
what issued the statement. The trade is attribution: the database does not know
which person is behind a connection, so trigger-written entries carry no actor
and are labelled as coming from the trigger. An entry written by the application
layer names the user; an entry written here proves a change happened and that
nothing in the application recorded it.

PostgreSQL only; skipped on the SQLite development fallback.
"""

from django.db import migrations

FUNCTION = """
-- NOTE: literal %% in this SQL is doubled; see the comment in create().
CREATE OR REPLACE FUNCTION fn_audit_status_change() RETURNS trigger AS $$
DECLARE
    v_label text := '';
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        -- TG_ARGV[0] is the audit entity type, TG_ARGV[1] the column on this
        -- table that identifies the row in a way a person would recognise.
        IF TG_ARGV[1] IS NOT NULL AND TG_ARGV[1] <> '' THEN
            EXECUTE format('SELECT ($1).%%I::text', TG_ARGV[1])
               INTO v_label USING NEW;
        END IF;

        INSERT INTO adminpanel_auditlog (
            actor_id, actor_label, action, entity_type, entity_id,
            entity_label, summary, changes, ip_address, created_at
        ) VALUES (
            NULL,
            'database trigger',
            'STATUS_CHANGE',
            TG_ARGV[0],
            NEW.id,
            COALESCE(LEFT(v_label, 150), ''),
            LEFT(format('%%s %%s changed from %%s to %%s',
                        TG_ARGV[0], COALESCE(v_label, NEW.id::text),
                        OLD.status, NEW.status), 255),
            jsonb_build_object('status',
                jsonb_build_object('from', OLD.status, 'to', NEW.status)),
            NULL,
            NOW()
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGERS = [
    ("""
     CREATE TRIGGER trg_audit_application_status
     AFTER UPDATE ON applicants_application
     FOR EACH ROW EXECUTE FUNCTION
         fn_audit_status_change('APPLICATION', 'application_id');
     """, 'trg_audit_application_status ON applicants_application'),
    ("""
     CREATE TRIGGER trg_audit_inspection_status
     AFTER UPDATE ON officers_inspection
     FOR EACH ROW EXECUTE FUNCTION
         fn_audit_status_change('INSPECTION', '');
     """, 'trg_audit_inspection_status ON officers_inspection'),
    ("""
     CREATE TRIGGER trg_audit_deficiency_status
     AFTER UPDATE ON officers_deficiency
     FOR EACH ROW EXECUTE FUNCTION
         fn_audit_status_change('DEFICIENCY', 'title');
     """, 'trg_audit_deficiency_status ON officers_deficiency'),
]


def create(apps, schema_editor):
    # schema_editor.execute passes the SQL through a DB-API cursor, which reads
    # % as a parameter marker. Every literal % in these statements is therefore
    # written doubled.
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(FUNCTION)
    for statement, _ in TRIGGERS:
        schema_editor.execute(statement)


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for _, target in TRIGGERS:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {target};')
    schema_editor.execute('DROP FUNCTION IF EXISTS fn_audit_status_change();')


class Migration(migrations.Migration):

    dependencies = [('adminpanel', '0004_reporting_views')]

    operations = [migrations.RunPython(create, drop)]
