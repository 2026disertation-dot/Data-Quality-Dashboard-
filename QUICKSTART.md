# Quick Start Guide

## Get Started in 5 Minutes

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Prepare the Data
```bash
python run_pipeline.py
```
Downloads the Kaggle Project Portfolio Dataset, cleans it into the data contract
(8 projects, 76 monthly records), builds the real-data test fixtures, measures
the dashboard, writes `results/*.md` and `results/figures/*.png`, and runs the
173-test suite.

Reuse an already-downloaded copy with `python run_pipeline.py --skip-download`.

No Kaggle credentials? Put the dataset's 16 workbooks in one folder and run:
```bash
python download_kaggle_data.py --local-dir C:/path/to/dataset
```

### 3. Run the Dashboard
```bash
streamlit run app.py
```

### 4. Upload Data
- Open your browser to `http://localhost:8501`
- Upload `data/kaggle_cleaned_data.csv`
- Select "Batch Mode" (historical) or "Incremental Mode" (new records)
- Click "Process Data"

### 5. Explore Results
- Navigate through the tabs to see:
  - Data preview and structure
  - Quality metrics and scores
  - Distribution analysis
  - Validation results and anomalies
  - Cost analysis and variance
  - Summary statistics

## Data Format

Your CSV must have these columns:

| Column              | Type     | Required | Description                              |
| ---------------------| ----------| ----------| ------------------------------------------|
| project_id          | string   | Yes      | Project identifier (e.g. `P01`)          |
| time_period         | string   | Yes      | Reporting period (e.g. `Month-1`)        |
| pmb_budget          | numeric  | Yes      | Planned budget for the period (≥ 0)      |
| actual_cost         | numeric  | Yes      | Actual cost incurred in the period (≥ 0) |
| progress_pct        | numeric  | Yes      | Cumulative progress percentage (0–100)   |
| revenue_claimed     | numeric  | Yes      | Revenue claimed in the period (≥ 0)      |
| actual_date         | datetime | Yes      | Date of the cost record                  |
| baseline_start_date | datetime | Yes      | Project baseline start date              |

The composite key `project_id` + `time_period` must be unique.

## Common Use Cases

### Historical Data Analysis
1. Upload your complete dataset
2. Select "Batch Mode"
3. Review overall quality scores
4. Identify patterns in anomalies
5. Export cleaned data if needed

### Real-time Monitoring
1. Load initial dataset in Batch Mode
2. Upload new records using Incremental Mode
3. Monitor validation results for new data
4. Address anomalies immediately

### Data Quality Audit
1. Upload dataset for audit
2. Review all validation results
3. Filter by anomaly type
4. Generate quality report
5. Track improvements over time

## Tips

- **Use the real data**: start with `data/kaggle_cleaned_data.csv`
- **Check data format**: ensure your CSV matches the required column names
- **Review anomalies first**: check the Validation Results tab before detailed analysis
- **Use filters**: Apply project and time period filters for focused analysis
- **Export results**: Use the export functionality to share findings

## Next Steps

- Read the full [README.md](README.md) for the measured results and figures
- See `results/data_profiling.md` for the measured profiling tables
- See `results/comparative_results.md` for the dashboard-vs-spreadsheet comparison
- See `data/README.md` for what each data file contains
- Run the test suite: `pytest tests/ -q`
- Customize validation rules in `validation_engine.py`
- Modify the data contract in `data_contract.py`