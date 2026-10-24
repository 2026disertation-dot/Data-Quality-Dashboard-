# Data Quality Dashboard

**Design Science Research Project — Interactive Data Quality Validation with Live API Endpoints**

A multi-project portfolio data quality system that detects, visualises, and prioritises inconsistencies in budget and actual cost records. Enforces a unified data contract across batch, incremental, and live API modes through a shared validation engine, achieving **100% dual-mode consistency** and **99.6% detection completeness** against controlled defect sets.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture — How It All Fits Together](#architecture---how-it-all-fits-together)
3. [Data Contract — The Two Tiers](#data-contract---the-two-tiers)
4. [Validation Rules R1–R14](#validation-rules-r1-r14)
5. [Installation](#installation)
6. [Running the Project](#running-the-project)
   - [Option A: End-to-End Evidence Pipeline](#option-a-end-to-end-evidence-pipeline)
   - [Option B: Streamlit Dashboard Only](#option-b-streamlit-dashboard-only)
   - [Option C: Live Flask API Only](#option-c-live-flask-api-only)
7. [Using the Dashboard UI](#using-the-dashboard-ui)
8. [Project Structure](#project-structure)
9. [Testing](#testing)
10. [Results and Figures](#results-and-figures)
11. [Research Contributions](#research-contributions)
12. [License](#license)
13. [Team](#team)

## Project Overview

The Data Quality Dashboard is a dissertation project implementing an interactive data quality validation system for multi-project cost and progress data. It addresses three persistent problems in project controls: **accuracy, completeness, and timeliness** of cost data.

### What it does

- **Validates** budget and actual cost records across two data contract tiers (raw WBS-level and derived project-level)
- **Detects** 14 classes of data quality defects (R1–R14) — missing fields, type errors, out-of-bounds values, duplicates, inconsistent descriptions, date ordering violations, cumulative restatements, budget overruns, and progress mismatches
- **Visualises** quality dimension scores, cost distributions, planned-vs-actual trends, anomaly breakdowns, and project summaries
- **Serves** a live REST API (Flask) that validates incoming records synchronously with sub-second response times
- **Guarantees** dual-mode consistency: batch, incremental, and API modes all use the same `Validator` instance, so no record can be accepted in one mode and rejected in another

### Key results

| Measure | Result |
|---------|--------|
| Detection completeness | 100% (13/13 injected defects detected) |
| False positive rate | 0.00% |
| Dual-mode consistency | 100% (batch vs incremental agreement) |
| Batch performance | < 1 s on 2,727 raw records |
| Incremental performance | < 1 s on new records |
| API response time | < 2 s per submission |

## Architecture — How It All Fits Together

```
Data Ingestion  →  Validation Engine  →  Live Flask API
                            ↓
                    Diagnostics Layer  →  Streamlit Dashboard
                            ↑
                    Live API shares same Validator
```

Five components with strict separation of concerns:

| Component | Responsibility |
|-----------|---------------|
| **Data Ingestion Layer** | Downloads Kaggle project portfolio data, extracts EVM time-phase, cleans into contract-ready CSV |
| **Validation Engine** | Single shared `Validator` enforcing R1–R14 across both contract tiers |
| **Live Flask API** | `POST /validate`, `GET /status`, `GET /flagged` — returns `200` accepted / `202` quarantined / `422` rejected |
| **Diagnostics Layer** | Computes four data quality dimension scores (completeness, consistency, accuracy, integrity) |
| **Streamlit Dashboard** | Six-tab UI: Data Preview, Quality Metrics, Distribution, Validation Results, Cost Analysis, Summary Statistics |

### The key design decision

The **data contract is the single source of truth**. Validation rules are defined once and consumed identically by batch mode, incremental mode, and the live API. This is what makes dual-mode consistency possible — no mode can drift from another because they all call the same `Validator.validate()`.

## Data Contract — The Two Tiers

The system validates two related but distinct record shapes:

### Tier 1: Raw WBS-Level Contract (`data_quality/contracts/raw.py`)

One row per `(project_id, wbs_code, period_index)`. Ten fields:

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | string (P##) | Project identifier |
| `project_name` | string | Human-readable project label (R6) |
| `source_file` | string | Originating workbook (R11) |
| `wbs_code` | string | Work package code, kept as string (leading zeros preserved) |
| `wbs_description` | string | Work package label (R7, R12) |
| `period_date` | datetime | Calendar date of reporting period (R8) |
| `period_index` | integer (≥1) | Sequential period number (R3) |
| `pv_cum` | float (≥0) | Cumulative planned value (R4, R9) |
| `ac_cum` | float (≥0) | Cumulative actual cost (R4, R9) |
| `ev_cum` | float (≥0) | Cumulative earned value (R4, R9) |

**Granularity**: 2,727 rows across 8 projects, 82 WBS codes.

### Tier 2: Derived Project-Level Contract (`data_quality/contracts/derived.py`)

One row per `(project_id, time_period)`. Eight fields:

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | string (P##) | Project identifier |
| `time_period` | string | Reporting period (e.g., `Month-3`) |
| `pmb_budget` | float (≥0) | Period planned budget, de-cumulativised |
| `actual_cost` | float (≥0) | Period actual cost, de-cumulativised |
| `progress_pct` | float (0–100) | Cumulative completion reported |
| `revenue_claimed` | float (≥0) | Period revenue claimed |
| `actual_date` | datetime | Calendar date of reporting period |
| `baseline_start_date` | datetime | Project baseline start date (R8) |

**Granularity**: 76 rows across 8 projects, 14 reporting periods.

### Data flow

```
Kaggle Excel workbooks
       ↓  download.py  (extract EVM time-phase)
data/kaggle_original_data.csv  (cumulative, raw tier)
       ↓  clean.py    (aggregate, de-cumulativise, derive)
data/kaggle_cleaned_data.csv  (contract-ready, derived tier)
       ↓  streamlit run app.py  OR  python -m data_quality.reporting.run_pipeline
```

## Validation Rules R1–R14

| Rule | Check | Tier | Severity | Dimension |
|------|-------|------|----------|-----------|
| **R1** | Missing required field | Raw / Derived | High | Completeness |
| **R2** | Unexpected data type | Raw / Derived | High | Completeness |
| **R3** | `period_index` must be sequential | Raw | Medium | Consistency |
| **R4** | Negative values in money columns | Raw / Derived | Medium | Accuracy |
| **R5** | Duplicate composite key | Raw / Derived | Medium | Consistency |
| **R6** | Inconsistent project name | Raw | Medium | Consistency |
| **R7** | Inconsistent WBS description | Raw | Medium | Consistency |
| **R8** | Date ordering violation (`period_date` / `actual_date` vs baseline) | Raw / Derived | Medium | Integrity |
| **R9** | Cumulative values must not decrease | Raw | High | Integrity |
| **R10** | Date outside reporting window | Raw | Medium | Integrity |
| **R11** | Source file mismatch | Raw | Medium | Consistency |
| **R12** | Missing WBS description | Raw | High | Completeness |
| **R13** | Budget overrun (`actual_cost > budget × tolerance`) | Derived | Medium | Integrity |
| **R14** | Progress mismatch (`actual_cost` outruns `progress_pct`) | Derived | Medium | Integrity |

API response mapping:
- **200 Accepted** — clean record, no findings
- **202 Quarantined** — out-of-bounds or logical anomaly (R3, R4, R8–R14)
- **422 Rejected** — missing field or type error (R1, R2, R12)

## Installation

### Prerequisites

- Python 3.10 or higher
- pip (or uv / poetry)

### Step 1 — Open the project folder

```powershell
cd c:\Users\okipa\Desktop\projects\project\Data-Quality-Dashboard-
```

### Step 2 — Create a virtual environment (recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3 — Install dependencies

```powershell
pip install -r requirements.txt
```

Or install with dev dependencies (for testing):

```powershell
pip install -e ".[dev]"
```

### Step 4 — Verify installation

```powershell
python -c "import data_quality; print('OK')"
```

You should see `OK` with no errors.

## Running the Project

There are three ways to run the project, depending on what you need.

---

### Option A: End-to-End Evidence Pipeline (Recommended for research)

This runs the complete chain: download data → clean → validate → measure → write reports → generate figures → run tests.

```powershell
# Full chain (downloads from Kaggle, runs everything)
python -m data_quality.reporting.run_pipeline

# Reuse cached Kaggle download, skip re-download
python -m data_quality.reporting.run_pipeline --skip-download

# Skip the pytest test suite (faster)
python -m data_quality.reporting.run_pipeline --skip-tests
```

**What this produces:**

| Output | Path | Description |
|--------|------|-------------|
| Cleaned data | `data/kaggle_cleaned_data.csv` | Contract-ready derived tier |
| Results report | `results/RESULTS.md` | Single top-level research report |
| System testing | `results/pipeline/system_testing_results.md` | Measured evidence chain |
| Data profiling | `results/pipeline/data_profiling.md` | Raw data profile |
| Comparative results | `results/pipeline/comparative_results.md` | Dashboard vs spreadsheet checks |
| Figures (11 PNG) | `results/figures/fig01_*.png` through `fig11_*.png` | All visualisations |

---

### Option B: Streamlit Dashboard Only (Interactive UI)

For live, interactive exploration of data quality:

```powershell
# First, ensure cleaned data exists
python -m data_quality.preprocess.clean

# Then launch the dashboard
streamlit run app.py
```

**Then open:** `http://localhost:8501`

The dashboard has six tabs:

| Tab | Purpose |
|-----|---------|
| **Data Preview** | View uploaded records |
| **Quality Metrics** | Accuracy, completeness, consistency, integrity scores vs targets |
| **Distribution** | Histograms of selected variables |
| **Validation Results** | Detected anomalies and flagged records |
| **Cost Analysis** | Budget vs actual, cost variance |
| **Summary Statistics** | Mean, median, mode, std, min, max |

**To upload your own data:** Use the file uploader in the sidebar. Your CSV must match one of the two contract tiers (see Data Contract section above).

---

### Option C: Live Flask API Only (Programmatic access)

For external system integration:

```powershell
# Option 1: Run via the API module
python -m data_quality.api.server

# Option 2: Create app programmatically in Python
from data_quality.api.server import create_app
app = create_app()
app.run(port=5000)
```

**Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /validate` | JSON body | Validate a record or batch. Returns `200` / `202` / `422` |
| `GET /status` | — | Return validation counters (accepted/rejected/quarantined) |
| `GET /flagged` | — | Return flagged-records table (optionally `?rule=R9`) |
| `GET /health` | — | Liveness probe |

**Example request:**

```powershell
curl -X POST http://localhost:5000/validate `
  -H "Content-Type: application/json" `
  -d '{"project_id":"P01","time_period":"Month-1","pmb_budget":100000,"actual_cost":95000,"progress_pct":50,"revenue_claimed":90000,"actual_date":"2024-01-15","baseline_start_date":"2024-01-01"}'
```

**Example response (accepted):**

```json
{
  "status": "accepted",
  "tier": "raw",
  "records": 1,
  "batch": false,
  "valid_records": 1,
  "invalid_records": 0,
  "total_findings": 0,
  "findings": [],
  "elapsed_ms": 1.234
}
```

## Using the Dashboard UI

### Step 1: Prepare data

If you haven't generated the cleaned dataset yet:

```powershell
python -m data_quality.preprocess.download      # downloads from Kaggle
python -m data_quality.preprocess.clean         # transforms into contract
```

This produces `data/kaggle_cleaned_data.csv` (76 derived records across 8 projects).

### Step 2: Launch

```powershell
streamlit run app.py
```

### Step 3: Explore

1. Upload `data/kaggle_cleaned_data.csv` via the sidebar file uploader
2. Select **Batch** mode for full-dataset analysis or **Incremental** mode for new records
3. Click **Process Data**
4. Review the six tabs for quality scores, anomalies, cost variance, and statistics

### Expected data format

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `project_id` | string | Yes | Project identifier (P##) |
| `time_period` | string | Yes | Reporting period (e.g., Month-1) |
| `pmb_budget` | numeric | Yes | Period planned budget |
| `actual_cost` | numeric | Yes | Period actual cost |
| `progress_pct` | numeric (0–100) | Yes | Cumulative completion |
| `revenue_claimed` | numeric | Yes | Period revenue claimed |
| `actual_date` | datetime | Yes | Calendar date |
| `baseline_start_date` | datetime | Yes | Project baseline start |

## Project Structure

```
Data-Quality-Dashboard/
├── app.py                          # Streamlit dashboard (six-tab UI)
├── README.md                       # This file
├── ddm.md                          # Project description document
├── LICENSE
├── pyproject.toml                  # Package configuration
├── requirements.txt                # Python dependencies
│
├── data/                           # Cleaned CSV data files
│   ├── kaggle_original_data.csv    # Raw cumulative EVM extract
│   └── kaggle_cleaned_data.csv     # Contract-ready derived tier
│
├── results/                        # Generated outputs
│   ├── RESULTS.md                  # Single top-level results report
│   ├── figures/                    # 11 generated PNG visualisations
│   └── pipeline/                   # Pipeline-generated evidence reports
│
├── data_quality/                   # Core Python package
│   ├── contracts/                  # Raw (10-field) & derived (8-field) contracts
│   ├── engine/                     # Rules R1–R14 + shared Validator
│   ├── pipeline/                   # Batch & incremental orchestration
│   ├── api/                        # Flask service endpoints
│   ├── fixtures/                   # Controlled defect injection
│   ├── preprocess/                 # Download and clean pipeline
│   ├── reporting/                  # Evaluation + document generation
│   └── legacy/                     # Superseded single-tier baseline
│
├── tests/                          # 214 pytest test suite
│
└── team/                           # Individual contribution statements
```

### Package layout detail

| Module | Purpose |
|--------|---------|
| `data_quality.contracts.raw` | Raw WBS-level contract schema (10 fields, pandera) |
| `data_quality.contracts.derived` | Derived project-level contract schema (8 fields, pandera) |
| `data_quality.engine.validator` | Single shared `Validator` — dual-mode consistency guarantee |
| `data_quality.engine.record_rules` | R1–R5, R11, R12 — per-record validation rules |
| `data_quality.engine.cross_record_rules` | R6–R10, R13, R14 — cross-record validation rules |
| `data_quality.engine.findings` | `Finding` dataclass + counting semantics |
| `data_quality.pipeline.runner` | `DataPipeline` — batch + incremental orchestration |
| `data_quality.pipeline.quality` | Dimension scoring (completeness, consistency, accuracy, integrity) |
| `data_quality.api.server` | Flask API — `POST /validate`, `GET /status`, `GET /flagged` |
| `data_quality.preprocess.download` | Kaggle download + EVM time-phase extraction |
| `data_quality.preprocess.clean` | De-cumulativisation + contract enforcement |
| `data_quality.reporting.run_pipeline` | End-to-end evidence chain |
| `data_quality.reporting.evaluation` | Measured evaluation (detection, false positives, etc.) |
| `data_quality.reporting.figures` | Figure generation (11 PNGs) |
| `data_quality.legacy` | Superseded single-tier baseline (kept for comparison) |

## Testing

The project includes a 214-test pytest suite:

```powershell
# Run all tests
pytest tests/ -q

# Run with verbose output
pytest tests/ -v

# Run specific test file
pytest tests/test_engine.py -v
```

Key test files:

| Test File | Covers |
|-----------|--------|
| `test_engine.py` | Validation rules R1–R14, Validator behavior |
| `test_api.py` | Flask API endpoints and response codes |
| `test_evaluation.py` | Detection completeness, false positives, dual-mode consistency |
| `test_preprocess.py` | Download and clean pipeline |
| `test_real_data_quality.py` | Real Kaggle data validation |
| `test_reporting_evidence.py` | Report generation and figure output |
| `test_hygiene.py` | README/results consistency (no hand-typed numbers) |
| `test_legacy_*.py` | Superseded baseline regression |
