-- =====================================================================
-- Sample SQL queries for the FireNOC Management System
--
-- Each query answers a question the Fire Department would actually ask,
-- and each one exercises a different part of the relational toolkit.
-- Run them all with:
--
--     python manage.py runqueries --seed 2000
--
-- which seeds synthetic rows inside a transaction, executes every query
-- below, and rolls the rows back afterwards.
--
-- Schema: docs/database/relational-schema.md
-- =====================================================================


-- name: Applications per status
-- demonstrates: GROUP BY with an aggregate, ordered by the aggregate
-- question: How is the department's workload distributed right now?
SELECT status,
       COUNT(*) AS applications
  FROM applicants_application
 GROUP BY status
 ORDER BY applications DESC;


-- name: Busy postal codes
-- demonstrates: GROUP BY with HAVING, filtering on the aggregate itself
-- question: Which areas generate enough applications to justify a local team?
SELECT pin_code,
       city,
       COUNT(*) AS applications
  FROM applicants_application
 GROUP BY pin_code, city
HAVING COUNT(*) >= 20
 ORDER BY applications DESC
 LIMIT 15;


-- name: Applications with their applicant account
-- demonstrates: INNER JOIN across a foreign key
-- question: Who filed each application?
SELECT a.application_id,
       a.building_name,
       a.status,
       u.username,
       u.email
  FROM applicants_application a
  JOIN auth_user u ON u.id = a.applicant_id
 ORDER BY a.created_at DESC
 LIMIT 15;


-- name: Applications still awaiting a first inspection
-- demonstrates: LEFT JOIN with an IS NULL test, the anti-join idiom
-- question: Which applications have been accepted but never visited?
SELECT a.application_id,
       a.building_name,
       a.status,
       a.created_at::date AS submitted_on
  FROM applicants_application a
  LEFT JOIN officers_inspection i ON i.application_id = a.id
 WHERE i.id IS NULL
   AND a.status NOT IN ('REJECTED', 'NOC_ISSUED')
 ORDER BY a.created_at
 LIMIT 15;


-- name: Buildings larger than average
-- demonstrates: a scalar subquery in the WHERE clause
-- question: Which applications cover an above-average built-up area?
SELECT application_id,
       building_name,
       builtup_area
  FROM applicants_application
 WHERE builtup_area > (SELECT AVG(builtup_area) FROM applicants_application)
 ORDER BY builtup_area DESC
 LIMIT 15;


-- name: Applications carrying open deficiencies
-- demonstrates: EXISTS with a correlated subquery
-- question: Which applications are blocked on the applicant fixing something?
SELECT a.application_id,
       a.building_name,
       a.status
  FROM applicants_application a
 WHERE EXISTS (
           SELECT 1
             FROM officers_deficiency d
            WHERE d.application_id = a.id
              AND d.status = 'OPEN'
       )
 ORDER BY a.created_at
 LIMIT 15;


-- name: Applications that have never had a deficiency raised
-- demonstrates: NOT EXISTS, the complement of the query above
-- question: Which buildings passed inspection without a single finding?
SELECT a.application_id,
       a.building_name
  FROM applicants_application a
 WHERE NOT EXISTS (
           SELECT 1 FROM officers_deficiency d WHERE d.application_id = a.id
       )
 LIMIT 15;


-- name: Deficiency counts by severity and status
-- demonstrates: conditional aggregation with FILTER, a pivot in one pass
-- question: How many deficiencies of each severity are still open?
SELECT severity,
       COUNT(*)                                        AS total,
       COUNT(*) FILTER (WHERE status = 'OPEN')         AS still_open,
       COUNT(*) FILTER (WHERE status = 'CLOSED')       AS closed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'CLOSED')
             / NULLIF(COUNT(*), 0), 1)                 AS percent_closed
  FROM officers_deficiency
 GROUP BY severity
 ORDER BY CASE severity
              WHEN 'CRITICAL' THEN 1
              WHEN 'MAJOR'    THEN 2
              ELSE 3
          END;


-- name: The full inspection workflow in one row per application
-- demonstrates: a four-table join mixing INNER and LEFT
-- question: What is the complete picture for each inspected application?
SELECT a.application_id,
       a.building_name,
       i.scheduled_date,
       i.status                AS inspection_status,
       r.overall_result,
       COUNT(d.id)             AS deficiencies
  FROM applicants_application a
  JOIN officers_inspection i      ON i.application_id = a.id
  LEFT JOIN officers_inspectionreport r ON r.inspection_id = i.id
  LEFT JOIN officers_deficiency d       ON d.inspection_id = i.id
 GROUP BY a.application_id, a.building_name, i.scheduled_date,
          i.status, r.overall_result
 ORDER BY i.scheduled_date DESC
 LIMIT 15;


-- name: Largest building per building type
-- demonstrates: a window function with PARTITION BY, ranking within groups
-- question: What is the biggest site the department handles in each category?
SELECT building_type,
       application_id,
       building_name,
       builtup_area
  FROM (
         SELECT building_type,
                application_id,
                building_name,
                builtup_area,
                ROW_NUMBER() OVER (PARTITION BY building_type
                                   ORDER BY builtup_area DESC) AS rank_in_type
           FROM applicants_application
       ) ranked
 WHERE rank_in_type = 1
 ORDER BY builtup_area DESC;


-- name: Monthly submissions with a running total
-- demonstrates: a CTE feeding a window function with a cumulative frame
-- question: How is the application backlog growing over time?
WITH monthly AS (
    SELECT DATE_TRUNC('month', created_at)::date AS month,
           COUNT(*)                              AS submitted
      FROM applicants_application
     GROUP BY DATE_TRUNC('month', created_at)
)
SELECT month,
       submitted,
       SUM(submitted) OVER (ORDER BY month
                            ROWS BETWEEN UNBOUNDED PRECEDING
                                     AND CURRENT ROW) AS cumulative
  FROM monthly
 ORDER BY month;


-- name: Each application's most recent inspection
-- demonstrates: DISTINCT ON, PostgreSQL's answer to "latest row per group"
-- question: What is the current inspection state of every application?
SELECT DISTINCT ON (i.application_id)
       a.application_id,
       i.scheduled_date,
       i.status
  FROM officers_inspection i
  JOIN applicants_application a ON a.id = i.application_id
 ORDER BY i.application_id, i.scheduled_date DESC
 LIMIT 15;


-- name: Application ageing buckets
-- demonstrates: CASE inside an aggregate, turning a continuous value into bands
-- question: How long have pending applications been waiting?
SELECT CASE
           WHEN AGE(NOW(), created_at) < INTERVAL '7 days'  THEN '0-6 days'
           WHEN AGE(NOW(), created_at) < INTERVAL '30 days' THEN '7-29 days'
           WHEN AGE(NOW(), created_at) < INTERVAL '90 days' THEN '30-89 days'
           ELSE '90+ days'
       END                AS age_band,
       COUNT(*)           AS applications
  FROM applicants_application
 WHERE status NOT IN ('NOC_ISSUED', 'REJECTED')
 GROUP BY age_band
 ORDER BY MIN(created_at) DESC;


-- name: Everyone involved in the workflow
-- demonstrates: UNION across dissimilar sources, with a discriminator column
-- question: Which accounts take part, and in what role?
  SELECT 'Applicant' AS role, u.username, COUNT(a.id) AS items
    FROM auth_user u
    JOIN applicants_application a ON a.applicant_id = u.id
   GROUP BY u.username
UNION
  SELECT 'Officer' AS role, u.username, COUNT(i.id) AS items
    FROM auth_user u
    JOIN officers_inspection i ON i.officer_id = u.id
   GROUP BY u.username
   ORDER BY items DESC
   LIMIT 15;


-- name: Normalization payoff: buildings reused across applications
-- demonstrates: a join to the normalized tables with a HAVING filter
-- question: How much duplication did the Building table remove?
SELECT b.name,
       b.address,
       p.city,
       COUNT(a.id) AS applications_for_this_building
  FROM adminpanel_building b
  JOIN adminpanel_pincode p ON p.pin_code = b.pin_code_id
  LEFT JOIN applicants_application a ON a.building_id = b.id
 GROUP BY b.id, b.name, b.address, p.city
HAVING COUNT(a.id) > 1
 ORDER BY applications_for_this_building DESC
 LIMIT 15;
