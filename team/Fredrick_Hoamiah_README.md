# Frontend / Visualisation Lead - Fredrick Hoamiah (B01934177)

## Role Overview

As the Frontend / Visualisation Lead, you are responsible for **Objective 4** (Interactive Visualisation and Prioritisation). Your work encompasses the design, implementation, and refinement of the interactive frontend for the group's data quality dashboard.

## Project Objectives

### Objective 4: Interactive Visualisation and Prioritisation
To design and implement an interactive Python dashboard that visualises and prioritises data quality inconsistencies, communicates validation failures clearly for both historical and incremental data, and supports practitioner decision-making.

**Key References:**
- Few (2013) - Information Dashboard Design
- Batini and Scannapieco (2016) - Data and information quality
- Yigitbasioglu and Velcu (2012) - Dashboard performance management
- Streamlit, Dash, Plotly documentation

## Individual Contribution Statement

My individual contribution encompasses the design, implementation, and refinement of the interactive frontend for the group's data quality dashboard. Specifically, I am responsible for:

1. **Designing a coherent information architecture and visual hierarchy** that supports both portfolio-level overviews and detailed record-level inspection
2. **Implementing interactive visualisations for the four core data quality dimensions** - completeness, consistency, accuracy, and integrity - using appropriate chart types, colour scales, and filtering
3. **Providing clear visual and textual feedback for validation failures**, including unexpected data types, missing required fields, out-of-bounds numerical values, and logical anomalies
4. **Supporting dual operating views**: exploratory analysis of the full historical dataset and near-real-time monitoring of newly ingested records via queries to the backend API
5. **Producing a documented, maintainable frontend artefact** that integrates cleanly with the backend pipeline and diagnostic scoring components

All frontend artefacts, including the interactive dashboard code, visualisations, prioritisation mechanisms, dual-mode user views, and technical documentation, will be produced independently by me and submitted as part of my final dissertation. I will coordinate closely with the Diagnostics Lead (responsible for quality scores), the Backend Lead (responsible for flagged records and the live API), the Theory Lead (responsible for design principle alignment), and the Evaluation Lead (responsible for interface testing) to ensure seamless integration while maintaining clear boundaries of individual responsibility. My contribution is explicitly scoped to the frontend and visualisation layer; I do not claim responsibility for metric definition, pipeline implementation, or formal system testing protocols, which are assigned to other group members.

## Dissertation Structure

Your dissertation should include the following sections aligned with your objectives:

1. **Introduction** (5 marks)
   - Importance of effective visualisation in data quality
   - Gap in interactive dashboard design for project controls
   - Overview of visualisation and prioritisation approach

2. **Literature Review** (15 marks)
   - Information visualisation principles (Few, 2013)
   - Dashboard design in performance management (Yigitbasioglu and Velcu, 2012)
   - Visual encoding for data quality (Batini and Scannapieco, 2016)
   - Interactive frameworks (Streamlit, Dash, Plotly)

3. **Research Design** (15 marks)
   - Information architecture design
   - Visual hierarchy and layout methodology
   - Dual-mode view design (historical/incremental)
   - Prioritisation mechanism design

4. **Implementation** (25 marks)
   - Streamlit dashboard implementation
   - Interactive visualisations for four dimensions
   - Validation failure visual feedback
   - Dual-mode view implementation

5. **Testing** (10 marks)
   - Usability testing results
   - Visualisation effectiveness validation
   - Dual-mode view testing
   - Performance testing for interactive components

6. **Presentation of Results** (10 marks)
   - Dashboard screenshots and walkthroughs
   - Visualisation examples
   - User interaction flows
   - Prioritisation mechanism demonstration

7. **Conclusions** (10 marks)
   - Contribution to visualisation knowledge
   - Practical implications for practitioner decision-making
   - Limitations and future work

8. **Critical Self-Evaluation** (10 marks)
   - Reflection on visual design challenges
   - Lessons learned from dual-mode implementation
   - Challenges in visual feedback design

## Key Responsibilities

### 1. Streamlit Dashboard
- **Location**: `app.py` (root-level file)
- Implement the interactive dashboard with six tabs
- Design intuitive user interface for data quality monitoring
- Ensure dual-mode views (historical and incremental) work correctly

### 2. Data Visualization
- **Location**: `app.py` and `data_quality/reporting/figures.py`
- Create interactive charts using Plotly
- Visualize dimension scores, distributions, and cost variance
- Ensure figures are exportable for research documentation

### 3. User Experience
- **Location**: `app.py` and `.streamlit/config.toml`
- Design responsive layout with sidebar controls
- Implement mode toggle for historical/incremental views
- Ensure clear visual feedback for validation outcomes

## Core Files to Understand

```
app.py                          # Main Streamlit application (37KB)
.streamlit/config.toml          # Streamlit theme and configuration
data_quality/
  reporting/
    figures.py                  # Figure generation for research documentation
  pipeline/
    quality.py                  # Dimension scores for visualization
```

## Key Concepts

### Dashboard Tabs

1. **Data Preview**: Shows first 5 rows of uploaded dataset with all columns
2. **Metric Table**: Displays four quality dimension scores as a table
3. **Metric Graph**: Shows dimension scores as a pie chart
4. **Distribution**: Histogram of selected variable with 30 bins
5. **Summary Statistics**: Mean, median, mode in a three-row table
6. **Cost Variance**: Histogram of cost variance (EV minus AC)

### Visualization Types

- **Histograms**: Distribution analysis for cost variables
- **Line Charts**: Time-series for planned vs actual costs
- **Pie Charts**: Dimension score breakdown
- **Box Plots**: Statistical distribution with quartiles
- **Bar Charts**: Comparative analysis (injected vs detected defects)

### Dual-Mode Views

- **Historical Mode**: Exploratory analysis of past cost data
- **Incremental Mode**: Continuous monitoring of new records
- Mode toggle switches between views with different data sources

## Commands for Your Role

```bash
# Start the Streamlit dashboard
streamlit run app.py

# Test the dashboard with real data
streamlit run app.py -- data/kaggle_cleaned_data.csv

# Generate figures for research documentation
python -m data_quality.reporting.figures

# View the Streamlit configuration
cat .streamlit/config.toml

# Test figure generation
python -m pytest tests/test_reporting_evidence.py -v
```

## Visualization Tasks

1. **Dashboard Layout**: Ensure six tabs are properly implemented in `app.py`
2. **Interactive Charts**: Ensure Plotly charts are responsive and interactive
3. **Color Scheme**: Maintain consistent color palette across all visualizations
4. **Export Capability**: Ensure figures can be saved as PNG for research
5. **Mode Toggle**: Ensure historical/incremental mode switch works correctly

## Common Issues

| Issue | Solution |
|-------|----------|
| Charts not rendering | Check Plotly imports and figure structure in `app.py` |
| Colors inconsistent | Review color palette in `.streamlit/config.toml` and `app.py` |
| Mode toggle not working | Check state management in `app.py` for mode switching |
| Figures not saving | Verify figure export logic in `reporting/figures.py` |
| Dashboard slow on large datasets | Implement pagination or sampling in `app.py` |

## Color Palette

The dashboard uses a consistent color palette defined in `app.py`:

```python
ACCENT = "#007AFF"      # system blue - primary series
GOOD = "#34C759"        # green   - within target / valid
WARN = "#FF9F0A"        # amber   - attention
BAD = "#FF3B30"         # red     - out of target / invalid
NEUTRAL = "#8E8E93"     # grey    - reference lines
```

## Dashboard Flow

```
User Uploads Data
    ↓
File Upload Widget (Sidebar)
    ↓
Data Pipeline (data_quality/pipeline/runner.py)
    ↓
Validation Results
    ↓
Dimension Scores (data_quality/pipeline/quality.py)
    ↓
Tab Selection
    ↓
Visualization (Plotly)
    ↓
Interactive Display
```

## Figure Generation

Research figures are generated separately from the dashboard:

```bash
python -m data_quality.reporting.figures
```

This generates:
- `fig01_data_preview.png` - Data preview table
- `fig02_dimension_scores.png` - Dimension scores pie chart
- `fig03_cost_distribution.png` - Cost distribution histogram
- `fig04_summary_statistics.png` - Summary statistics bar chart
- `fig05_planned_vs_actual.png` - Planned vs actual line chart
- `fig06_project_summary.png` - Project-level comparison
- `fig07_anomaly_breakdown.png` - Anomaly category breakdown
- `fig08_incremental_validation.png` - Incremental validation results
- `fig09_system_testing.png` - System testing attainment
- `fig10_cost_variance_effect.png` - Cost variance before/after
- `fig11_pipeline_workflow.png` - Pipeline workflow diagram

## Dependencies

Your work depends on:
- **Theory Lead**: Provides dimension scores for visualization
- **Backend Lead**: Provides API endpoints for real-time data
- **Diagnostics Lead**: Provides validation findings for display

Your work enables:
- **Evaluation Lead**: Provides visual evidence for research documentation
- **All Stakeholders**: Interactive access to data quality metrics

## Next Steps

1. Review `app.py` to understand the dashboard structure
2. Examine `.streamlit/config.toml` for theme configuration
3. Run `streamlit run app.py` to test the dashboard locally
4. Review `data_quality/reporting/figures.py` to understand figure generation
5. Test all six tabs with different datasets to ensure robustness
