"""
Guarantee that a deficiency names the same application as the inspection that
found it.

officers_deficiency carries a foreign key to both officers_inspection and
applicants_application, and officers_inspection already references the
application, so deficiency.application_id is derivable. The normalization
analysis records this as a knowingly retained redundancy
(docs/database/normalization.md, section 4.5) on the grounds that it removes a
join from the most frequent query in the officer module.

A redundancy is only defensible while it cannot become an inconsistency. A CHECK
constraint cannot express this rule, because it may not read another table.
A composite foreign key can: officers_inspection declares UNIQUE (id,
application_id), which lets officers_deficiency reference that pair. The
database then rejects any deficiency whose application does not match its
inspection's application.

The statements are PostgreSQL-specific, so they are skipped on other backends;
the SQLite development fallback keeps the application-level guarantee only.
"""

from django.db import migrations

ADD_COMPOSITE_FK = """
ALTER TABLE officers_deficiency
    ADD CONSTRAINT deficiency_matches_inspection_application
    FOREIGN KEY (inspection_id, application_id)
    REFERENCES officers_inspection (id, application_id)
    DEFERRABLE INITIALLY DEFERRED;
"""

DROP_COMPOSITE_FK = """
ALTER TABLE officers_deficiency
    DROP CONSTRAINT IF EXISTS deficiency_matches_inspection_application;
"""


def add_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(ADD_COMPOSITE_FK)


def drop_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(DROP_COMPOSITE_FK)


class Migration(migrations.Migration):

    dependencies = [
        ('officers', '0005_constraints_and_indexes'),
    ]

    operations = [
        migrations.RunPython(add_constraint, drop_constraint),
    ]
