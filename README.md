# Data Quality Dashboard

Detecting inconsistencies in multi-project WBS cost and progress data.

**Every number below is generated, never hand-typed.**
`python -m dqd.reporting.report` rewrites this file and `results/RESULTS.md`
together from the real data, so they cannot disagree with each other or with the
code.

```bash
pip install -r requirements.txt
python -m pytest -q                      # test suite
python -m dqd.reporting.report           # regenerate this file + RESULTS.md
streamlit run app.py                     # dashboard
```

## Dataset

Real data downloaded from Kaggle. Nothing is synthesised.

| Property | Value |
|---|---|
| Raw records (WBS x month) | 2,727 |
| Derived records (project x period) | 76 |
| Projects | 8 |
| Distinct WBS codes | 82 |
| Periods | 14 |

## Results

| Metric | Measured | Target | Status |
|---|---|---|---|
| Detection completeness | **99.6%** (249/250) | >= 95% | Pass |
| False positives | **0.00%** (0/500) | <= 5% | Pass |
| Batch/incremental consistency | **100%** (500 records) | 100% | Pass |
| Batch validation, 2,727 rows | **4.09 s** | < 5 s | Pass |

> Timing is machine-dependent: the same code measures ~2 s idle and ~6 s under
> parallel test load. The figure above is whatever the run that generated this
> file actually observed.

### Detection completeness by rule

| Rule | Injected | Detected | Recall |
|---|---|---|---|
| R1 | 25 | 25 | 100.0% |
| R11 | 25 | 25 | 100.0% |
| R12 | 25 | 25 | 100.0% |
| R2 | 25 | 25 | 100.0% |
| R3 | 25 | 25 | 100.0% |
| R4 | 50 | 50 | 100.0% |
| R6 | 25 | 25 | 100.0% |
| R9 | 50 | 49 | 98.0% |

## Findings on the real data

| Tier | Valid | Invalid | Events | Rules fired |
|---|---|---|---|---|
| Raw | 2,705 | 22 | 22 | R9 |
| Derived | 59 | 17 | 34 | R14 |

### Why almost everything passes

This is a property of the source data, not a gap in the implementation. The
workbooks are **structurally consistent**: no missing fields, no duplicate keys,
no format errors, no out-of-range values. R1-R5, R6, R7, R11 and R12 therefore
return nothing.

The only genuine defects are logical: **22 cumulative totals that
decrease** across 21 series (R9), and **17 derived records whose spend has
outrun their progress** (R14).

Because the real data cannot exercise most rules, detection is measured on
**defects injected into the real records**. Each is a controlled mutation of a
genuine row, so the surrounding data - including the `(project_id, wbs_code)`
series context R9 depends on - stays intact.

## Quality dimensions

| Dimension | Target | Raw | Status | Derived |
|---|---|---|---|---|
| Completeness | 98% | 100.00% | Pass | 100.00% |
| Consistency | 99% | 100.00% | Pass | 100.00% |
| Accuracy | 97% | 100.00% | Pass | 100.00% |
| Integrity | 90% | 99.19% | Pass | 77.63% |

Overall: **99.84%** raw, **95.53%** derived. The tiers differ for a real reason: the same 17 defects weigh far heavier across 76 derived rows than across 2,727 raw rows.

## Architecture

```
src/dqd/
  contracts/    raw.py (10 fields), derived.py (8 fields)
  engine/       R1-R14 record and cross-record rules, one Validator
  pipeline/     runner.py (batch + incremental), quality.py (scoring)
  api/          server.py - Flask, Table 4.3 status semantics
  fixtures/     builder.py - defect injection into real records
  reporting/    evaluation.py + report.py - all measured figures
```

Both tiers share one `Validator`, so batch, incremental and API paths cannot
disagree. Dual-mode consistency is structural, not a convention.

### API

| Endpoint | Behaviour |
|---|---|
| `POST /validate` | 200 accepted / 202 quarantined / 422 rejected |
| `GET /status` | Counts only. Does not validate, so it cannot mutate state |
| `GET /flagged` | Filterable flagged-record table with remediation |
| `GET /health` | Liveness |

A *clean* record returns **200**; a *missing field or wrong type* returns
**422**; an *out-of-bounds or logical* anomaly returns **202**.

A row failing several rules still counts as **one** invalid record.
`invalid_records` counts rows, not findings.

## Bugs found by measuring

Each produced plausible output while being wrong:

1. `invalid_records` was set to the finding count, so a row breaking four rules
   was subtracted four times and `valid_records` went negative.
2. The completeness numerator was inverted.
3. Unparseable dates were coerced to `NaT`, which read as *missing* and was
   blamed on R1 instead of the R2 type error it was.
4. `wbs_code` read from CSV as `int64` made **all 2,727 rows**
   spurious R2 errors and dropped leading zeros, so WBS `011` and WBS `11`
   collided.
5. R9 read its baseline from an already-damaged frame, measuring a second defect
   against the first defect rather than the truth.
6. `_readable_as_date` re-parsed 14 distinct dates 8,181 times.
