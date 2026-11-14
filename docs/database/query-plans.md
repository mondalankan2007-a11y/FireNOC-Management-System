# Query Plan Analysis

Measurement of whether the indexes declared in the constraints and indexes work
are actually used by the PostgreSQL planner, and what they save. The indexes
themselves are listed in section 9 of
[relational-schema.md](relational-schema.md).

Reproduce with:

```
python manage.py dbanalyze --applications 5000
```

The command seeds synthetic rows inside a transaction, runs `ANALYZE` so the
planner has fresh statistics, executes each query twice — once with index scans
available and once with `enable_indexscan`, `enable_indexonlyscan` and
`enable_bitmapscan` set to `off` — and then rolls the rows back. Nothing is left
in the database.

**Measured on:** PostgreSQL 18.6, 5,000 applications, 2,500 inspections,
1,250 deficiencies.

---

## 1. Results

| Query | Plan with indexes | Plan without | Speed-up | Index chosen |
|---|---|---|---:|---|
| Applicant status queue (`PENDING`) | Index Scan 0.051 ms | Seq Scan 0.895 ms | **17.5×** | `application_created_idx` |
| Applicant status queue (`NOC_ISSUED`) | Index Scan 0.021 ms | Seq Scan 0.659 ms | **31.4×** | `application_status_time_idx` |
| Dashboard counts by status | Seq Scan 1.174 ms | Seq Scan 1.216 ms | 1.0× | none |
| Recent applications, unfiltered | Index Scan 0.016 ms | Seq Scan 1.245 ms | **77.8×** | `application_created_idx` |
| Renewals only | Bitmap Heap Scan 0.277 ms | Seq Scan 0.616 ms | **2.2×** | `application_type_idx` |
| Officer inspection queue | Index Scan 0.075 ms | Seq Scan 0.371 ms | **4.9×** | `inspection_date_idx` |
| Open deficiencies, newest first | Index Scan 0.018 ms | Seq Scan 0.150 ms | **8.3×** | `deficiency_status_time_idx` |

Absolute times at this volume are small. What matters is the shape of the plan:
a sequential scan reads every row and gets linearly slower as the table grows,
while an index scan with a `LIMIT` touches only the rows it returns.

---

## 2. The finding: selectivity decides which index is used

Two composite indexes were declared on the assumption that a status-filtered,
date-ordered queue would use them. The planner disagreed — and it was right.

For the common case, `status = 'PENDING'` (about one row in seven):

```
Index Scan using application_created_idx on applicants_application
    Filter: ((status)::text = 'PENDING'::text)
    Rows Removed by Filter: 145
```

The planner walks `created_at` in order, discards non-matching rows, and stops
once it has 25. Because matches are common, it does not have to walk far. This
avoids a sort entirely, which the composite index would also avoid — but the
single-column index is narrower, so it wins.

For the rare case, `status = 'NOC_ISSUED'` (about one row in a hundred):

```
Index Scan using application_status_time_idx on applicants_application
    Index Cond: ((status)::text = 'NOC_ISSUED'::text)
```

Here the composite index *is* chosen, with the status as an `Index Cond` rather
than a filter, and the query is the fastest of the set. Walking `created_at` and
filtering would mean discarding roughly ninety-nine rows for every one kept.

**The same index is correct or useless depending on how selective the filter
is.** The planner makes that decision per query from the statistics `ANALYZE`
collects, which is why the command runs `ANALYZE` before measuring: without
fresh statistics, PostgreSQL guesses and the plans are not representative.

`officers_inspection` shows the same pattern. The queue filters on two of four
statuses, so half the table matches, and `inspection_date_idx` is preferred over
`inspection_status_date_idx`.

---

## 3. What this says about each index

| Index | Verdict |
|---|---|
| `application_created_idx` | **Earning its place.** Chosen by two queries, 77.8× on the unfiltered listing. |
| `application_status_time_idx` | **Justified, conditionally.** Unused for common statuses, decisive for rare ones. `APPROVED`, `REJECTED` and `NOC_ISSUED` become rare as a real dataset accumulates in `PENDING`. |
| `application_type_idx` | **Marginal.** 2.2× on a bitmap scan. Renewals are a quarter of all rows, so the index saves little; it would matter in a report filtering renewals within a date range. |
| `inspection_status_date_idx` | **Not currently used.** The queue matches half the table. Keep it for date-bounded status queries, where the leading column becomes selective. |
| `inspection_date_idx` | **Earning its place.** Chosen for the officer queue. |
| `deficiency_status_time_idx` | **Earning its place.** Used as an `Index Cond`, 8.3× faster. |

No index is dropped on the strength of this. Two are recorded as not yet paying
for themselves at this volume and distribution, which is a more honest position
than claiming every index was necessary. An index that is unused still costs
write time and storage, so this is the measurement that would justify removing
them later.

---

## 4. The query no index helps

The dashboard count is a sequential scan with and without indexes, and
identically fast either way:

```
HashAggregate  (actual time=1.157..1.158 rows=8 loops=1)
  Group Key: status
  ->  Seq Scan on applicants_application  (actual rows=5000 loops=1)
```

Counting every application grouped by status has to read every application. No
index changes that, and adding one would only slow writes. The honest answer for
this query is not an index but a different approach — a materialized summary, or
accepting the scan — which is what the reporting layer work addresses.
