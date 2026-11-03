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

`data/kaggle_original_data.csv` as received, before any cleaning.
Shape: **2,727 rows x 10 columns**. The cleaning stage later condenses these WBS-level
series into one record per project and period, so this is the state every
downstream figure starts from. Nothing is synthesised.

### Columns (as read)

| Column | Dtype (as read) | Non-null |
|---|---|---|
| project_id | str | 2,727 |
| project_name | str | 2,727 |
| source_file | str | 2,727 |
| wbs_code | int64 | 2,727 |
| wbs_description | str | 2,727 |
| period_date | str | 2,727 |
| period_index | int64 | 2,727 |
| pv_cum | float64 | 2,727 |
| ac_cum | float64 | 2,727 |
| ev_cum | float64 | 2,727 |

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

| Tier | Valid | Invalid | Findings | Rules fired |
|---|---|---|---|---|
| Raw | 2,727 | 0 | 0 | - |

The source workbooks are **structurally consistent** at the WBS level: no
missing fields, no duplicate keys, no format errors, no out-of-range values,
no naming conflicts and no missing descriptions. Every rule on the WBS-level
view (R1-R7, R10-R12) returns nothing on this data. The only defects that
survive are logical, and they live on the project-period tier.

## 2. Cleaned Kaggle data

The cleaning stage condenses the raw series into one record per project and
reporting period, storing cumulative values so the project-period view can run
R8, R9, R13 and R14. The result is written to
`data/kaggle_cleaned_data.csv`.

| Property | Value |
|---|---|
| Derived records (project x period) | 76 |
| Fields (columns) | 8 |
| Projects | 8 |
| Periods | 14 |

### Findings on the cleaned data

| Tier | Valid | Invalid | Findings | Rules fired |
|---|---|---|---|---|
| Derived | 35 | 41 | 42 | R14, R9 |

On the real data only R9 and R14 fire: **1 cumulative decrease(s)**
(R9) and **41 records whose cumulative spend has outrun the progress
they report** (R14).

### Why almost everything passes

This is a property of the source data, not a gap in the implementation: both
tiers run through one validator, and what it reports is genuinely what the
files contain.

### Results measured on the real data

| Metric | Measured | Target | Status |
|---|---|---|---|
| Detection completeness | **100.0%** (280/280) | >= 95% | Pass |
| False positives | **0.00%** (0/200) | <= 5% | Pass |
| Batch/incremental consistency | **100%** (400 records) | 100% | Pass |
| Batch validation, 2,727 rows | **3.40 s** | < 10 s | Pass |

> Timing is machine-dependent: the same code measures ~2 s idle and ~6 s under
> parallel test load. The figure above is whatever the run that generated this
> file actually observed.

#### Detection completeness by rule

| Rule | Injected | Detected | Recall |
|---|---|---|---|
| R1 | 20 | 20 | 100.0% |
| R10 | 20 | 20 | 100.0% |
| R11 | 20 | 20 | 100.0% |
| R12 | 20 | 20 | 100.0% |
| R13 | 20 | 20 | 100.0% |
| R14 | 20 | 20 | 100.0% |
| R2 | 20 | 20 | 100.0% |
| R3 | 20 | 20 | 100.0% |
| R4 | 20 | 20 | 100.0% |
| R5 | 20 | 20 | 100.0% |
| R6 | 20 | 20 | 100.0% |
| R7 | 20 | 20 | 100.0% |
| R8 | 20 | 20 | 100.0% |
| R9 | 20 | 20 | 100.0% |

Because the real data cannot exercise most rules, detection is measured on
**defects injected into the real records**. Each is a controlled mutation of a
genuine row, injected into an isolated copy of that row's context - the row
itself, its WBS series, or its project - so the surrounding data a cross-record
rule reads (for example the `(project_id, time_period)` series R9 depends on)
stays intact and two defects cannot mask each other.

### Quality dimensions

| Dimension | Target | Raw | Status | Derived |
|---|---|---|---|---|
| Completeness | 98% | 100.00% | Pass | 100.00% |
| Consistency | 99% | 100.00% | Pass | 100.00% |
| Accuracy | 97% | 100.00% | Pass | 100.00% |
| Integrity | 99% | 100.00% | Pass | 46.05% |

Overall: **100.00%** raw, **89.21%** derived. The tiers differ for a real reason: 41 of 76 derived rows are flagged while only 0 of 2,727 raw rows are.

## Design

Both tiers share one `Validator`, so batch, incremental and API paths cannot
disagree. multi-mode consistency is structural, not a convention.

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
8. `_validate_derived` evaluated R13 and R14 twice, so 41 flagged records were
   reported as 82 events and every derived finding was counted twice.
