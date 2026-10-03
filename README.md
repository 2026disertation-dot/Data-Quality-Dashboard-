# Data Quality Dashboard

Detecting inconsistencies in multi-project WBS cost/progress data.

Everything below is **measured**, not asserted. Regenerate every figure with:

```bash
python -m dqd.reporting.evaluation
```

## Dataset

Real data, downloaded from Kaggle - not generated.

| Tier | Shape | Fields | Description |
|---|---|---|---|
| Raw | 2,727 rows | 10 | One row per WBS code per month |
| Derived | 76 rows | 8 | One row per project per reporting period |

8 projects, 82 distinct WBS codes, 14 periods.

## Results

| Metric | Measured | Target |
|---|---|---|
| Detection completeness | **99.6%** (249/250) | >= 95% |
| False positives | **0.00%** (0/500) | <= 5% |
| Batch/incremental consistency | **100%** (500/500) | 100% |
| Batch validation, 2,727 rows | **3.92 s** | < 5 s |
| Mean API response | **~22 ms** | < 1000 ms |

On the *real* data:

| Tier | Valid | Invalid | Rule that fires |
|---|---|---|---|
| Raw | 2,705 | 22 | R9 only |
| Derived | 59 | 17 | R14 only |

### Why almost everything passes

This is a property of the source data, not a gap in the implementation. The
workbooks are **structurally consistent**: no missing fields, no duplicate keys,
no format errors, no out-of-range values, no naming conflicts, no unmapped WBS
codes, no missing descriptions. Rules R1-R5, R6, R7, R11 and R12 therefore return
**zero** findings, and R3 reports zero duplicates.

The only genuine defects are logical:

- **R9** - 22 cumulative totals that *decrease* across 21 series.
- **R14** - 17 derived records whose progress and spend have gone out of step.

Because the real data cannot exercise most rules, detection capability is
measured on **synthetic defects injected into the real records**. Each defect is a
controlled mutation of a genuine row, so the surrounding data - including the
`(project_id, wbs_code)` series context R9 depends on - stays intact. Injecting
into isolated frames instead would produce defects no implementation could detect.

One of the 250 injected defects is genuinely undetectable and is reported as a
miss rather than quietly excluded from the denominator.

## Architecture

```
src/dqd/
  contracts/     raw.py (10 fields), derived.py (8 fields)
  engine/        R1-R12 record + cross-record rules, Validator
  pipeline/      runner.py (batch + incremental), quality.py (scoring)
  api/           server.py - Flask, Table 4.3 status semantics
  fixtures/      builder.py - synthetic defect injection
  reporting/     evaluation.py - all measured figures
```

Both tiers share one `Validator`, so batch, incremental and API paths cannot
disagree - dual-mode consistency is structural rather than a convention.

### API

| Endpoint | Behaviour |
|---|---|
| `POST /validate` | 200 accepted / 202 quarantined / 422 rejected |
| `GET /status` | Counts only. Does not validate, so it cannot mutate state |
| `GET /flagged` | Filterable flagged-record table with remediation |
| `GET /health` | Liveness |

A *clean* record returns **200**; a *missing field or wrong type* returns
**422**; an *out-of-bounds or logical* anomaly returns **202**. A row can fail
several rules and still count as one invalid record - `invalid_records` is a
count of rows, not of findings.

## Bugs found by measuring

Each of these produced plausible-looking output while being wrong:

1. `invalid_records` was set to the finding count, so a row breaking four rules
   was subtracted four times and `valid_records` went negative.
2. The completeness numerator was inverted.
3. Unparseable dates were coerced to `NaT`, which then read as *missing* and was
   blamed on R1 instead of being reported as the R2 type error it was.
4. `wbs_code` read from CSV as `int64` made **all 2,727 rows** spurious R2 errors
   and silently dropped leading zeros, so WBS `011` and WBS `11` collided.
5. R9 read its baseline from an already-damaged frame, so a second defect in the
   same series was measured against the first defect rather than the truth.
6. `_readable_as_date` re-parsed 14 distinct dates 8,181 times.

## Tests

```bash
python -m pytest -q      # 206 passing
```

## Requirements

```
pandas, numpy, pandera, flask, streamlit, plotly, pytest
```
