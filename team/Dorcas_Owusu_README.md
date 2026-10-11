# Diagnostics Lead - Dorcas Owusu (B01829419)

## Role Overview

As the Diagnostics Lead, you are responsible for **Objective 2** (Systematic Profiling and Metric Definition). Your work encompasses the design, operationalisation, and validation of the diagnostic measurement framework for the group's data quality dashboard.

## Project Objectives

### Objective 2: Systematic Profiling and Metric Definition
To systematically profile the Project Portfolio Dataset and define quantitative metrics and detection rules for completeness, consistency, accuracy and integrity in both batch and incremental modes, and to quantify the impact of detected inconsistencies on cost variance, estimate accuracy and portfolio-level forecasting reliability.

**Key References:**
- Batini and Scannapieco (2016) - Data and information quality
- U.S. Government Accountability Office (2020) - Cost estimation guide
- gacevedob (2022) - Project Portfolio Dataset

## Individual Contribution Statement

My individual contribution encompasses the design, operationalisation, and validation of the diagnostic measurement framework for the group's data quality dashboard. Specifically, I am responsible for:

1. **Conducting systematic exploratory profiling of the Project Portfolio Dataset** to characterise missing values, duplicates, format conflicts, and logical anomalies across budget and actual cost records
2. **Defining and operationalising quantitative metrics for completeness, consistency, accuracy, and integrity** tailored to multi-project cost data
3. **Designing detection rules that operate consistently in both batch and incremental modes**, including live API submissions, and handing these rules to the Backend Lead for implementation
4. **Quantifying the impact of each category of inconsistency on cost variance, estimate accuracy, and portfolio-level forecasting reliability**
5. **Producing a validated quality-score framework, impact report, and technical documentation** to enable seamless integration with the backend pipeline, frontend visualisation, and evaluation components

All diagnostic artefacts, including the quality-score framework, detection rules, and impact quantification analysis, will be produced independently by me and submitted as part of my final dissertation. I will coordinate closely with the Backend Lead (responsible for pipeline implementation), the Frontend Lead (responsible for visualisation), the Theory Lead (responsible for conceptual alignment), and the Evaluation Lead (responsible for test-case construction) to ensure that metric definitions are implemented consistently across all components. My contribution is explicitly scoped to the diagnostic measurement layer; I do not claim responsibility for pipeline implementation, visual design, or formal system testing protocols, which are assigned to other group members.

## Dissertation Structure

Your dissertation should include the following sections aligned with your objectives:

1. **Introduction** (5 marks)
   - Importance of data quality in multi-project environments
   - Gap in systematic profiling and metric definition
   - Overview of diagnostic framework approach

2. **Literature Review** (15 marks)
   - Data quality dimensions and metrics (Wang and Strong, 1996)
   - Data quality engineering (Batini and Scannapieco, 2016)
   - Cost estimation and data quality (GAO, 2020)
   - Anomaly detection in project cost data

3. **Research Design** (15 marks)
   - Profiling methodology for Project Portfolio Dataset
   - Metric operationalisation framework
   - Detection rule design methodology
   - Impact quantification approach

4. **Implementation** (25 marks)
   - Data profiling results and findings
   - Quality-score framework implementation
   - Detection rules specification
   - Impact analysis on cost variance and forecasting

5. **Testing** (10 marks)
   - Metric validation results
   - Detection rule testing
   - Impact quantification verification

6. **Presentation of Results** (10 marks)
   - Profiling statistics and visualisations
   - Quality-score metrics
   - Detection rule performance
   - Impact analysis results

7. **Conclusions** (10 marks)
   - Contribution to diagnostic measurement knowledge
   - Practical implications for project controls
   - Limitations and future work

8. **Critical Self-Evaluation** (10 marks)
   - Reflection on diagnostic framework development
   - Challenges in metric operationalisation
   - Lessons learned from impact quantification

## Key Responsibilities

### 1. Validation Engine
- **Location**: `data_quality/engine/`
- Implement and maintain the 14 validation rules (R1-R14)
- Ensure the Validator correctly identifies all anomaly categories
- Maintain the findings structure for reporting

### 2. Anomaly Detection
- **Location**: `data_quality/engine/`
- Implement record-level rules (R1-R8, R10-R12)
- Implement cross-record rules (R9, R13, R14)
- Ensure proper categorization of anomalies

### 3. Diagnostic Reporting
- **Location**: `data_quality/engine/findings.py`
- Structure validation findings for clear reporting
- Ensure findings include sufficient detail for remediation
- Maintain the mapping between rules and anomaly categories

## Core Files to Understand

```
data_quality/
  engine/
    validator.py          # Main Validator class orchestrating all rules
    rules.py             # Rule definitions and implementations
    record_rules.py      # Single-record validation rules (R1-R8, R10-R12)
    cross_record_rules.py # Multi-record validation rules (R9, R13, R14)
    findings.py          # Findings data structure and formatting
```

## Key Concepts

### Validation Rules

**Record-Level Rules:**
- **R1**: Required fields must not be missing
- **R2**: Fields must match declared datatypes
- **R3**: Date fields must be valid dates
- **R4**: Numeric fields must be numeric
- **R5**: Categorical fields must match allowed values
- **R6**: Numeric fields must be within bounds
- **R7**: Progress must be between 0-100%
- **R8**: Costs must be non-negative
- **R10**: Actual date must not be before baseline
- **R11**: Cumulative values must be monotonic
- **R12**: No duplicate composite keys

**Cross-Record Rules:**
- **R9**: Cumulative totals must not decrease
- **R13**: Spend must not exceed progress
- **R14**: Revenue must not exceed budget

### Anomaly Categories

1. **Missing Values**: Required fields with null/empty values
2. **Type Errors**: Values that don't match expected datatype
3. **Bounds Violations**: Values outside acceptable ranges
4. **Logical Anomalies**: Cross-record inconsistencies
5. **Duplicates**: Repeated composite keys

## Commands for Your Role

```bash
# Test the validation engine
python -m pytest tests/test_engine.py -v

# Test individual rule implementations
python -m pytest tests/test_engine.py::test_record_rules -v
python -m pytest tests/test_engine.py::test_cross_record_rules -v

# Run validation on real data
python -c "from data_quality.engine.validator import Validator; from data_quality.contracts.raw import get_raw_contract; import pandas as pd; df = pd.read_csv('data/kaggle_cleaned_data.csv'); v = Validator(get_raw_contract()); results = v.validate(df); print(results)"

# View findings structure
python -c "from data_quality.engine.findings import ValidationFindings; help(ValidationFindings)"
```

## Diagnostic Tasks

1. **Rule Implementation**: Ensure all 14 rules are correctly implemented in `record_rules.py` and `cross_record_rules.py`
2. **Rule Testing**: Write comprehensive tests for each rule in `tests/test_engine.py`
3. **Findings Formatting**: Ensure `findings.py` produces clear, actionable diagnostic messages
4. **Performance**: Optimize validation for large datasets (especially cross-record rules)

## Common Issues

| Issue | Solution |
|-------|----------|
| Rule not firing on known bad data | Check rule logic in `record_rules.py` or `cross_record_rules.py` |
| False positives | Review rule thresholds in `rules.py` |
| Cross-record rules too slow | Optimize in `cross_record_rules.py` with vectorized operations |
| Findings unclear | Improve message formatting in `findings.py` |

## Rule-by-Rule Reference

| Rule | Category | File | Description |
|------|----------|------|-------------|
| R1 | Missing Values | `record_rules.py` | Required field validation |
| R2 | Type Errors | `record_rules.py` | Datatype validation |
| R3 | Type Errors | `record_rules.py` | Date format validation |
| R4 | Type Errors | `record_rules.py` | Numeric type validation |
| R5 | Type Errors | `record_rules.py` | Categorical value validation |
| R6 | Bounds Violations | `record_rules.py` | Numeric range validation |
| R7 | Bounds Violations | `record_rules.py` | Progress percentage validation |
| R8 | Bounds Violations | `record_rules.py` | Non-negative cost validation |
| R9 | Logical Anomalies | `cross_record_rules.py` | Monotonic cumulative validation |
| R10 | Logical Anomalies | `record_rules.py` | Date sequence validation |
| R11 | Logical Anomalies | `cross_record_rules.py` | Monotonic validation (cumulative) |
| R12 | Duplicates | `record_rules.py` | Duplicate key validation |
| R13 | Logical Anomalies | `cross_record_rules.py` | Spend vs progress validation |
| R14 | Logical Anomalies | `cross_record_rules.py` | Revenue vs budget validation |

## Dependencies

Your work depends on:
- **Theory Lead**: Provides the data contract specifications
- **Backend Lead**: Provides the pipeline that calls the Validator

Your work enables:
- **Evaluation Lead**: Provides the validation results for evidence generation
- **Frontend Lead**: Provides findings for dashboard display

## Next Steps

1. Review `data_quality/engine/rules.py` to understand all 14 rules
2. Examine `data_quality/engine/validator.py` to understand the orchestration
3. Run `python -m pytest tests/test_engine.py` to verify all rules pass
4. Test validation on the anomaly test set: `data/kaggle_anomaly_test_set.csv`
