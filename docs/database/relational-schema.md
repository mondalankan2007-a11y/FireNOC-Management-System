# Relational Schema

Physical table definitions for the FireNOC Management System as currently
implemented. The conceptual model behind these tables, including cardinalities
and participation, is in [er-model.md](er-model.md).

Types are given as PostgreSQL types. The schema is created and maintained by
Django migrations, not by hand-written DDL, so this document describes what the
migrations produce rather than a separate script to run.

---

## 1. Table inventory

| Table | Rows represent | Parent tables |
|---|---|---|
| `auth_user` | Accounts | — |
| `officers_officerprofile` | Officer details | `auth_user` |
| `applicants_application` | NOC applications | `auth_user` |
| `applicants_applicationdocument` | Uploaded files | `applicants_application` |
| `officers_documentverification` | Document decisions | `applicants_applicationdocument`, `auth_user` |
| `officers_applicationreview` | Desk reviews | `applicants_application`, `auth_user` |
| `officers_inspection` | Site visits | `applicants_application`, `auth_user` |
| `officers_inspectionchecklistitem` | Checklist rows | `officers_inspection` |
| `officers_inspectionreport` | Visit outcomes | `officers_inspection` |
| `officers_deficiency` | Safety shortcomings | `applicants_application`, `officers_inspection`, `auth_user` |
| `officers_deficiencyrectification` | Fix evidence | `officers_deficiency`, `auth_user` |

Django's own framework tables (`django_migrations`, `django_session`,
`django_content_type`, `auth_permission`, `auth_group`, and the two user
join tables) are created by the framework and are not described here.

---

## 2. Table definitions

### `auth_user`

Every account that can sign in, in any role.

| Column | Type | Constraints |
|---|---|---|
| `id` | serial | PRIMARY KEY, NOT NULL |
| `password` | varchar(128) | NOT NULL |
| `last_login` | timestamptz | NULL |
| `is_superuser` | boolean | NOT NULL |
| `username` | varchar(150) | UNIQUE, NOT NULL |
| `first_name` | varchar(150) | NOT NULL |
| `last_name` | varchar(150) | NOT NULL |
| `email` | varchar(254) | NOT NULL |
| `is_staff` | boolean | NOT NULL |
| `is_active` | boolean | NOT NULL |
| `date_joined` | timestamptz | NOT NULL |

### `officers_officerprofile`

Fire department staff details for a user account.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `user_id` | integer | REFERENCES `auth_user` ON DELETE CASCADE, UNIQUE, NOT NULL |
| `officer_id` | varchar(50) | UNIQUE, NOT NULL |
| `designation` | varchar(100) | NOT NULL |
| `badge_number` | varchar(50) | NOT NULL |
| `phone` | varchar(20) | NOT NULL |
| `is_active` | boolean | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

- Default ordering: `officer_id`

### `applicants_application`

One request for a Fire NOC, covering one building.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `applicant_id` | integer | REFERENCES `auth_user` ON DELETE CASCADE, NOT NULL |
| `full_name` | varchar(150) | NOT NULL |
| `email` | varchar(254) | NOT NULL |
| `mobile_number` | varchar(15) | NOT NULL |
| `building_name` | varchar(150) | NOT NULL |
| `building_type` | varchar(50) | NOT NULL, 7 allowed values |
| `building_type_other` | varchar(100) | NOT NULL |
| `building_address` | text | NOT NULL |
| `city` | varchar(100) | NOT NULL |
| `state` | varchar(100) | NOT NULL |
| `pin_code` | varchar(10) | NOT NULL |
| `num_floors` | integer | NOT NULL, CHECK >= 0 |
| `builtup_area` | numeric(10,2) | NOT NULL |
| `year_construction` | integer | NOT NULL, CHECK >= 0 |
| `occupancy_type` | varchar(50) | NOT NULL, 8 allowed values |
| `application_id` | varchar(50) | UNIQUE, NOT NULL |
| `application_type` | varchar(20) | NOT NULL, 2 allowed values |
| `purpose` | text | NOT NULL |
| `remarks` | text | NOT NULL |
| `status` | varchar(30) | NOT NULL, 7 allowed values |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

- Default ordering: `-created_at`

### `applicants_applicationdocument`

A file uploaded in support of an application.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `application_id` | bigint | REFERENCES `applicants_application` ON DELETE CASCADE, NOT NULL |
| `document_type` | varchar(50) | NOT NULL, 6 allowed values |
| `document_name` | varchar(255) | NOT NULL |
| `file` | varchar(100) | NOT NULL |
| `uploaded_at` | timestamptz | NOT NULL |

- Default ordering: `uploaded_at`

### `officers_documentverification`

An officer's decision on one uploaded document.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `document_id` | bigint | REFERENCES `applicants_applicationdocument` ON DELETE CASCADE, UNIQUE, NOT NULL |
| `verified_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `status` | varchar(20) | NOT NULL, 3 allowed values |
| `officer_remarks` | text | NOT NULL |
| `verified_at` | timestamptz | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

### `officers_applicationreview`

The desk review and recommendation for an application.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `application_id` | bigint | REFERENCES `applicants_application` ON DELETE CASCADE, UNIQUE, NOT NULL |
| `reviewed_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `status` | varchar(30) | NOT NULL, 2 allowed values |
| `officer_remarks` | text | NOT NULL |
| `recommendation` | varchar(30) | NOT NULL, 4 allowed values |
| `recommendation_remarks` | text | NOT NULL |
| `recommended_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `recommended_at` | timestamptz | NULL |
| `reviewed_at` | timestamptz | NOT NULL |
| `created_at` | timestamptz | NOT NULL |

### `officers_inspection`

A scheduled or completed site visit.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `application_id` | bigint | REFERENCES `applicants_application` ON DELETE CASCADE, NOT NULL |
| `officer_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `scheduled_date` | date | NOT NULL |
| `scheduled_time` | time | NOT NULL |
| `location` | varchar(300) | NOT NULL |
| `status` | varchar(20) | NOT NULL, 4 allowed values |
| `officer_remarks` | text | NOT NULL |
| `started_at` | timestamptz | NULL |
| `completed_at` | timestamptz | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

- Default ordering: `scheduled_date`, `scheduled_time`

### `officers_inspectionchecklistitem`

One fire-safety item assessed during a visit.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `inspection_id` | bigint | REFERENCES `officers_inspection` ON DELETE CASCADE, NOT NULL |
| `item_type` | varchar(50) | NOT NULL, 12 allowed values |
| `status` | varchar(20) | NOT NULL, 3 allowed values |
| `remarks` | text | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

- UNIQUE (`inspection_id`, `item_type`)
- Default ordering: `item_type`

### `officers_inspectionreport`

The outcome summary of a completed inspection.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `inspection_id` | bigint | REFERENCES `officers_inspection` ON DELETE CASCADE, UNIQUE, NOT NULL |
| `overall_result` | varchar(30) | NOT NULL, 3 allowed values |
| `general_observations` | text | NOT NULL |
| `officer_remarks` | text | NOT NULL |
| `completed_at` | timestamptz | NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |

### `officers_deficiency`

A safety shortcoming found during an inspection.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `application_id` | bigint | REFERENCES `applicants_application` ON DELETE CASCADE, NOT NULL |
| `inspection_id` | bigint | REFERENCES `officers_inspection` ON DELETE CASCADE, NOT NULL |
| `reported_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `closed_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `title` | varchar(200) | NOT NULL |
| `description` | text | NOT NULL |
| `severity` | varchar(20) | NOT NULL, 3 allowed values |
| `status` | varchar(30) | NOT NULL, 5 allowed values |
| `officer_remarks` | text | NOT NULL |
| `created_at` | timestamptz | NOT NULL |
| `updated_at` | timestamptz | NOT NULL |
| `resolved_at` | timestamptz | NULL |

- Default ordering: `-created_at`

### `officers_deficiencyrectification`

Applicant evidence that a deficiency was fixed.

| Column | Type | Constraints |
|---|---|---|
| `id` | bigserial | PRIMARY KEY, NOT NULL |
| `deficiency_id` | bigint | REFERENCES `officers_deficiency` ON DELETE CASCADE, NOT NULL |
| `submitted_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `description` | text | NOT NULL |
| `evidence_file` | varchar(100) | NULL |
| `submitted_at` | timestamptz | NOT NULL |
| `reviewed_by_id` | integer | REFERENCES `auth_user` ON DELETE SET NULL, NULL |
| `reviewed_at` | timestamptz | NULL |
| `review_remarks` | text | NOT NULL |
| `status` | varchar(20) | NOT NULL, 4 allowed values |

- Default ordering: `-submitted_at`

---

## 3. Referential integrity

| Child table | Column | Parent table | On delete |
|---|---|---|---|
| `officers_officerprofile` | `user_id` | `auth_user` | CASCADE |
| `applicants_application` | `applicant_id` | `auth_user` | CASCADE |
| `applicants_applicationdocument` | `application_id` | `applicants_application` | CASCADE |
| `officers_documentverification` | `document_id` | `applicants_applicationdocument` | CASCADE |
| `officers_documentverification` | `verified_by_id` | `auth_user` | SET NULL |
| `officers_applicationreview` | `application_id` | `applicants_application` | CASCADE |
| `officers_applicationreview` | `reviewed_by_id` | `auth_user` | SET NULL |
| `officers_applicationreview` | `recommended_by_id` | `auth_user` | SET NULL |
| `officers_inspection` | `application_id` | `applicants_application` | CASCADE |
| `officers_inspection` | `officer_id` | `auth_user` | SET NULL |
| `officers_inspectionchecklistitem` | `inspection_id` | `officers_inspection` | CASCADE |
| `officers_inspectionreport` | `inspection_id` | `officers_inspection` | CASCADE |
| `officers_deficiency` | `application_id` | `applicants_application` | CASCADE |
| `officers_deficiency` | `inspection_id` | `officers_inspection` | CASCADE |
| `officers_deficiency` | `reported_by_id` | `auth_user` | SET NULL |
| `officers_deficiency` | `closed_by_id` | `auth_user` | SET NULL |
| `officers_deficiencyrectification` | `deficiency_id` | `officers_deficiency` | CASCADE |
| `officers_deficiencyrectification` | `submitted_by_id` | `auth_user` | SET NULL |
| `officers_deficiencyrectification` | `reviewed_by_id` | `auth_user` | SET NULL |

Two deletion policies are in use, and the split is deliberate. Rows that cannot
mean anything without their parent cascade. Rows that reference the *staff
member who acted* are set null instead, so that removing an employee account
does not erase the inspection record that justified a certificate decision.

---

## 4. Index inventory

| Table | Indexed column | Why it exists |
|---|---|---|
| `officers_officerprofile` | `user_id` | Automatic: unique foreign key |
| `officers_officerprofile` | `officer_id` | Automatic: UNIQUE constraint |
| `applicants_application` | `applicant_id` | Automatic: foreign key |
| `applicants_application` | `application_id` | Automatic: UNIQUE constraint |
| `applicants_applicationdocument` | `application_id` | Automatic: foreign key |
| `officers_documentverification` | `document_id` | Automatic: unique foreign key |
| `officers_documentverification` | `verified_by_id` | Automatic: foreign key |
| `officers_applicationreview` | `application_id` | Automatic: unique foreign key |
| `officers_applicationreview` | `reviewed_by_id` | Automatic: foreign key |
| `officers_applicationreview` | `recommended_by_id` | Automatic: foreign key |
| `officers_inspection` | `application_id` | Automatic: foreign key |
| `officers_inspection` | `officer_id` | Automatic: foreign key |
| `officers_inspectionchecklistitem` | `inspection_id` | Automatic: foreign key |
| `officers_inspectionchecklistitem` | `inspection_id`, `item_type` | Automatic: composite UNIQUE |
| `officers_inspectionreport` | `inspection_id` | Automatic: unique foreign key |
| `officers_deficiency` | `application_id` | Automatic: foreign key |
| `officers_deficiency` | `inspection_id` | Automatic: foreign key |
| `officers_deficiency` | `reported_by_id` | Automatic: foreign key |
| `officers_deficiency` | `closed_by_id` | Automatic: foreign key |
| `officers_deficiencyrectification` | `deficiency_id` | Automatic: foreign key |
| `officers_deficiencyrectification` | `submitted_by_id` | Automatic: foreign key |
| `officers_deficiencyrectification` | `reviewed_by_id` | Automatic: foreign key |

Every index above is created automatically by PostgreSQL or Django as a side
effect of a `PRIMARY KEY`, `UNIQUE` or `FOREIGN KEY` declaration. **No index has
been declared deliberately for a query pattern.** Columns the application
filters and sorts on constantly — `applicants_application.status`,
`applicants_application.created_at`, `officers_inspection.scheduled_date`,
`officers_deficiency.status` — are not indexed, so every dashboard count and
every queue listing is a sequential scan.

This is recorded here as the measured starting point for the index tuning work
later in this module, not as a criticism of the existing code: with a small
development dataset the difference is invisible.

---

## 5. Declarative constraints

| Constraint kind | Count in schema |
|---|---|
| `PRIMARY KEY` | 11 (one per table) |
| `FOREIGN KEY` | 19 |
| `UNIQUE` (single column) | 5 |
| `UNIQUE` (composite) | 1 — `(inspection_id, item_type)` |
| `NOT NULL` | widely used |
| `CHECK` | **0** |
| Database-level `UniqueConstraint` | **0** |

The schema currently has no `CHECK` constraints. Every rule beyond "this column
must not be null" is enforced only in Python: status values are validated by
Django `choices`, which generates no database constraint, and numeric fields
such as `num_floors` and `builtup_area` accept any value the application layer
allows through. A row inserted by a SQL client, a data migration or a bulk load
can therefore violate rules the application believes are guaranteed.

Closing that gap is the subject of the database constraints work later in this
module.

---

## 6. Status domains

The values below are enforced in the application layer only. They are listed
here because they define the state machine the monitoring and reporting work
depends on.

| Table | Column | Allowed values |
|---|---|---|
| `applicants_application` | `building_type` | `RESIDENTIAL`, `COMMERCIAL`, `INDUSTRIAL`, `EDUCATIONAL`, `HOSPITAL`, `HOTEL`, `OTHER` |
| `applicants_application` | `occupancy_type` | `RESIDENTIAL`, `BUSINESS`, `ASSEMBLY`, `INDUSTRIAL`, `STORAGE`, `EDUCATIONAL`, `HEALTHCARE`, `MIXED_USE` |
| `applicants_application` | `application_type` | `NEW_NOC`, `RENEWAL` |
| `applicants_application` | `status` | `PENDING`, `UNDER_REVIEW`, `DOCUMENTS_VERIFIED`, `UNDER_INSPECTION`, `APPROVED`, `REJECTED`, `DEFICIENT` |
| `applicants_applicationdocument` | `document_type` | `ARCHITECTURAL_BLUEPRINT`, `FIRE_SAFETY_PLAN`, `HYDRANT_LAYOUT`, `EQUIPMENT_TEST_CERTIFICATE`, `OWNERSHIP_DEED`, `OTHER` |
| `officers_documentverification` | `status` | `PENDING`, `VERIFIED`, `REJECTED` |
| `officers_applicationreview` | `status` | `UNDER_REVIEW`, `DOCUMENTS_VERIFIED` |
| `officers_applicationreview` | `recommendation` | `PENDING`, `REQUIRES_RECTIFICATION`, `RECOMMENDED_FOR_APPROVAL`, `NOT_RECOMMENDED` |
| `officers_inspection` | `status` | `SCHEDULED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED` |
| `officers_inspectionchecklistitem` | `item_type` | `EXTINGUISHER_AVAILABLE`, `EXTINGUISHER_ACCESSIBLE`, `EXITS_AVAILABLE`, `EXITS_UNOBSTRUCTED`, `ALARM_INSTALLED`, `ALARM_FUNCTIONAL`, `EMERGENCY_LIGHTING`, `SAFETY_SIGNAGE`, `ELECTRICAL_SAFETY`, `STAIRWAY_ACCESS`, `HYDRANT_WATER`, `OVERALL_COMPLIANCE` |
| `officers_inspectionchecklistitem` | `status` | `COMPLIANT`, `NON_COMPLIANT`, `NOT_APPLICABLE` |
| `officers_inspectionreport` | `overall_result` | `SATISFACTORY`, `UNSATISFACTORY`, `REQUIRES_RECTIFICATION` |
| `officers_deficiency` | `severity` | `MINOR`, `MAJOR`, `CRITICAL` |
| `officers_deficiency` | `status` | `OPEN`, `SUBMITTED_FOR_VERIFICATION`, `VERIFIED`, `REJECTED`, `CLOSED` |
| `officers_deficiencyrectification` | `status` | `SUBMITTED`, `UNDER_REVIEW`, `ACCEPTED`, `REJECTED` |

`applicants_application.status` has no terminal value for a certificate having
been issued. The applicant-facing timeline already looks for `NOC_ISSUED`, but
that value is not in the column's allowed set and no table records an issued
certificate. Both are addressed by the NOC issuance work in this module.
