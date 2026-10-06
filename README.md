# Data Quality Dashboard

Detecting inconsistencies in multi-project WBS cost and progress data.

**Every number below is generated, never hand-typed.**
`python -m data_quality.reporting.report` rewrites this file and `results/RESULTS.md`
together from one live measurement, so they cannot disagree with each other or
with the code.

```bash
pip install -r requirements.txt
python -m pytest -q                      # test suite
python -m data_quality.reporting.report           # regenerate this file + RESULTS.md
python -m data_quality.preprocess.download        # fetch the Kaggle dataset
python -m data_quality.preprocess.clean           # build data/*.csv
python -m data_quality.reporting.run_pipeline     # full evidence chain
streamlit run app.py                     # dashboard
```

## Layout

One package, `data_quality/`, at the repository root so that `streamlit run app.py`
imports it without any path configuration:

```
data_quality/
  contracts/   the two data contracts (raw 10-field, derived 8-field)
  engine/      rules R1-R14 and the single shared Validator
  pipeline/    batch and incremental orchestration, dimension scoring
  api/         Flask service (200 accepted / 202 quarantined / 422 rejected)
  fixtures/    controlled defect injection into real records
  preprocess/  download and clean, producing data/*.csv
  reporting/   evaluation, document generation, figures, pipeline runner
  legacy/      the superseded single-tier implementation, kept as baseline
app.py         Streamlit dashboard, the only Python file at the repository root
```

`legacy/` is retained deliberately: the results chapter measures the old
single-tier engine against the new one, so it is evidence rather than dead code.
The dashboard, the cleaning stage's contract check and the report's figures and
descriptive statistics still consume it; the new engine, validator, pipeline and
API never import from it.

## 1. Original Kaggle data

Real data downloaded from Kaggle into `data/kaggle_original_data.csv`.
Nothing is synthesised.

| Property | Value |
|---|---|
| Raw records (WBS x month) | 2,727 |
| Fields (columns) | 10 |
| Projects | 8 |
| Distinct WBS codes | 82 |
| Periods | 14 |

### First 10 rows

| project_id | project_name | source_file | wbs_code | wbs_description | period_date | period_index | pv_cum | ac_cum | ev_cum |
|---|---|---|---|---|---|---|---|---|---|
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 103 | Water Sub-contractor | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 11 | Survey - Construction | 2011-04-01 | 1 | 2,519.15 | 1,400.00 | 1,232.66 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 111 | Install Conduits / pits... | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 112 | Electrical Conduit Sub-... | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 113 | Electrical Sub-contract... | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 121 | Landscaping Sub-contrac... | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 13 | QA Testing | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 131 | Fencing Sub-contractors | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 134 | Hire of Temporary Fencing | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |
| P01 | Airport Carpark | P018 - P01 Airport Carp... | 141 | Traffic Controllers | 2011-04-01 | 1 | 0.00 | 0.00 | 0.00 |

### Findings on the original data

| Tier | Valid | Invalid | Events | Rules fired |
|---|---|---|---|---|
| Raw | 2,705 | 22 | 22 | R9 |

The source workbooks are **structurally consistent**: no missing fields, no
duplicate keys, no format errors, no out-of-range values. Every structural rule
(R1-R5, R6, R7, R8, R10, R11, R12) returns nothing on this data. The only
defects that survive are logical: **22 cumulative totals that
decrease** across 21 series (R9).

## 2. Cleaned Kaggle data

The cleaning stage condenses the raw series into one record per project and
reporting period, written to `data/kaggle_cleaned_data.csv`.

| Property | Value |
|---|---|
| Derived records (project x period) | 76 |
| Fields (columns) | 8 |
| Projects | 8 |
| Periods | 14 |

### Findings on the cleaned data

| Tier | Valid | Invalid | Events | Rules fired |
|---|---|---|---|---|
| Derived | 59 | 17 | 17 | R14 |

Only the progress rule fires on this tier: **17 records whose cumulative spend
has outrun the progress they report** (R14).

### Why almost everything passes

This is a property of the source data, not a gap in the implementation: both
tiers run through one validator, and what it reports is genuinely what the
files contain.

### Results measured on the real data

| Metric | Measured | Target | Status |
|---|---|---|---|
| Detection completeness | **99.6%** (249/250) | >= 95% | Pass |
| False positives | **0.00%** (0/500) | <= 5% | Pass |
| Batch/incremental consistency | **100%** (500 records) | 100% | Pass |
| Batch validation, 2,727 rows | **7.12 s** | < 5 s | Not met |

> Timing is machine-dependent: the same code measures ~2 s idle and ~6 s under
> parallel test load. The figure above is whatever the run that generated this
> file actually observed.

#### Detection completeness by rule

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

Because the real data cannot exercise most rules, detection is measured on
**defects injected into the real records**. Each is a controlled mutation of a
genuine row, so the surrounding data - including the `(project_id, wbs_code)`
series context R9 depends on - stays intact.

### Quality dimensions

| Dimension | Target | Raw | Status | Derived |
|---|---|---|---|---|
| Completeness | 98% | 100.00% | Pass | 100.00% |
| Consistency | 99% | 100.00% | Pass | 100.00% |
| Accuracy | 97% | 100.00% | Pass | 100.00% |
| Integrity | 90% | 99.19% | Pass | 77.63% |

Overall: **99.84%** raw, **95.53%** derived. The tiers differ for a real reason: 17 of 76 derived rows are flagged while only 22 of 2,727 raw rows are.

## 3. Synthetic data

The real data is too clean to exercise most of the engine, so
`data/synthetic/` carries a hand-built set whose only job is to make every rule
fire: two CSVs plus `synthetic_ground_truth.csv`, the exact findings each
planted defect must produce.

| Property | Value |
|---|---|
| Raw records | 28 |
| Raw invalid | 15 |
| Raw findings | 20 |
| Derived records | 10 |
| Derived invalid | 5 |
| Derived findings | 7 |
| Rules fired | 14 of 14 |
| Coverage | 100.0% |
| Ground truth matched | 19/19 (100.0%) |

### Findings by rule

| Rule | Findings | Tier |
|---|---|---|
| R1 | 3 | raw |
| R10 | 1 | raw |
| R11 | 1 | raw |
| R12 | 1 | raw |
| R13 | 2 | derived |
| R14 | 4 | derived |
| R2 | 1 | raw |
| R3 | 1 | raw |
| R4 | 1 | raw |
| R5 | 2 | raw |
| R6 | 3 | raw |
| R7 | 3 | raw |
| R8 | 2 | raw + derived |
| R9 | 2 | raw |

**14/14 rules fire (100.0% coverage).** Ground truth: 19/19 labelled findings reproduced (100.0%). Nothing missed.

## Design

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
7. R10 compared a period's date against the maximum date of its own series -
   a bound that includes the date itself - so the condition could never hold
   and the rule never fired on any data.
8. `_validate_derived` evaluated R13 and R14 twice, so 17 flagged records were
   reported as 34 events and every derived finding was counted twice.
