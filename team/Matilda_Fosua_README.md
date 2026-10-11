# Evaluation & Validation Lead - Matilda Fosua (B01847480)

## Role Overview

As the Evaluation & Validation Lead, you are responsible for **Objective 5** (Empirical Evaluation). Your work encompasses the conception, implementation, and documentation of the assessment mechanism for the team's data quality dashboard.

## Project Objectives

### Objective 5: Empirical Evaluation
To evaluate the effectiveness, efficiency and technical reliability of the dashboard against traditional spreadsheet-based quality checks under historical and dynamic/malformed data conditions through structured system testing, including live API endpoint testing.

**Key References:**
- Myers et al. (2011) - The Art of Software Testing
- Hevner et al. (2004) - Design Science Research
- Batini and Scannapieco (2016) - Data and information quality
- System testing frameworks and methodologies

## Individual Contribution Statement

My personal involvement includes the conception, implementation, and documentation of the assessment mechanism for the team's data quality dashboard. Specifically, I am responsible for:

1. **Designing a structured evaluation protocol** that covers the complete historical Project Portfolio Dataset, controlled dynamic/malformed test sets, and live API submissions
2. **Constructing realistic test cases** that include missing required fields, unexpected data types, out-of-bounds numerical values, and logical anomalies
3. **Conducting comparative testing of the dashboard against traditional spreadsheet-based quality checks** on identical test sets
4. **Applying a structured system testing framework** covering functional, integration, boundary, regression, performance, error handling, detection completeness, false positive, and live API testing
5. **Producing a comprehensive evaluation report** that answers the evaluation objective and provides evidence-based recommendations for final refinements

All evaluation artefacts, including the evaluation protocol, test cases, comparative results, system testing report, and final effectiveness report, will be produced independently by me and submitted as part of my final dissertation. I will coordinate closely with the Backend Lead (responsible for pipeline and API artefacts), the Frontend Lead (responsible for the testable interface), the Diagnostics Lead (responsible for detection rule specifications), and the Theory Lead (responsible for alignment with the Design Science Research evaluation cycle) to ensure that testing is rigorous, independent, and reproducible. My contribution is explicitly scoped to the evaluation and validation layer; I do not claim responsibility for metric definition, pipeline implementation, or frontend visual design, which are assigned to other group members.

## Dissertation Structure

Your dissertation should include the following sections aligned with your objectives:

1. **Introduction** (5 marks)
   - Importance of rigorous evaluation in Design Science Research
   - Gap in empirical evaluation of data quality dashboards
   - Overview of evaluation and testing approach

2. **Literature Review** (15 marks)
   - System testing methodologies (Myers et al., 2011)
   - Design Science Research evaluation (Hevner et al., 2004)
   - Comparative analysis methods
   - Spreadsheet-based quality checks literature

3. **Research Design** (15 marks)
   - Evaluation protocol design
   - Test case construction methodology
   - Comparative testing framework
   - System testing strategy

4. **Implementation** (25 marks)
   - Test case implementation
   - Comparative testing execution
   - System testing results
   - Live API endpoint testing

5. **Testing** (10 marks)
   - Test coverage validation
   - Reproducibility verification
   - Statistical analysis of results

6. **Presentation of Results** (10 marks)
   - Comparative performance metrics
   - Detection completeness analysis
   - Time-to-insight measurements
   - System testing evidence

7. **Conclusions** (10 marks)
   - Contribution to evaluation methodology
   - Practical implications for dashboard effectiveness
   - Limitations and future work

8. **Critical Self-Evaluation** (10 marks)
   - Reflection on evaluation challenges
   - Lessons learned from comparative testing
   - Challenges in system testing

## Key Responsibilities

### 1. Evidence Generation
- **Location**: `data_quality/reporting/`
- Implement the full evidence chain from data to documentation
- Generate all tables and figures for research documentation
- Ensure results are reproducible and never hand-typed

### 2. System Testing
- **Location**: `tests/` and `data_quality/reporting/evaluation.py`
- Implement comprehensive test suites for all components
- Validate system against research requirements
- Ensure all tests pass before release

### 3. Comparative Analysis
- **Location**: `data_quality/reporting/evaluation.py`
- Compare dashboard performance against spreadsheet baseline
- Measure detection completeness, time-to-insight, and reproducibility
- Generate statistical evidence for research claims

## Core Files to Understand

```
data_quality/
  reporting/
    report.py           # Main report generator (README.md, RESULTS.md)
    evaluation.py       # Comparative analysis and statistical testing
    figures.py          # Figure generation for research documentation
    run_pipeline.py     # Full evidence chain orchestrator
tests/
  test_engine.py       # Validation engine tests
  test_api.py          # API endpoint tests
  test_legacy_pipeline.py # Pipeline tests
  test_real_data_quality.py # Real data validation tests
  test_evaluation.py   # Evaluation and comparative tests
```

## Key Concepts

### Evidence Chain

The evidence chain ensures all results are generated from real data:

```
Raw Data (Kaggle)
    ↓
preprocess/clean.py
    ↓
Cleaned Data
    ↓
pipeline/runner.py
    ↓
Validation Results
    ↓
pipeline/quality.py
    ↓
Dimension Scores
    ↓
reporting/evaluation.py
    ↓
Comparative Analysis
    ↓
reporting/report.py
    ↓
README.md + RESULTS.md + figures/
```

### System Testing Categories

1. **Functional Testing**: All validation rules work correctly
2. **Integration Testing**: End-to-end pipeline works correctly
3. **Performance Testing**: Response times meet requirements
4. **Comparative Testing**: Dashboard vs spreadsheet baseline
5. **Real Data Testing**: System works on actual Kaggle dataset

### Comparative Metrics

- **Detection Completeness**: Percentage of defects detected by each method
- **Time-to-Insight**: Time required to identify quality issues
- **Reproducibility**: Consistency of results across runs
- **False Positive Rate**: Percentage of false alarms

## Commands for Your Role

```bash
# Run the full evidence chain
python -m data_quality.reporting.run_pipeline

# Generate documentation only
python -m data_quality.reporting.report

# Generate figures only
python -m data_quality.reporting.figures

# Run all tests
python -m pytest -v

# Run specific test suites
python -m pytest tests/test_engine.py -v
python -m pytest tests/test_api.py -v
python -m pytest tests/test_evaluation.py -v

# Run comparative analysis
python -m data_quality.reporting.evaluation

# View generated results
cat results/RESULTS.md
```

## Evaluation Tasks

1. **Evidence Generation**: Ensure `reporting/run_pipeline.py` generates all evidence correctly
2. **Test Coverage**: Ensure all components have comprehensive tests in `tests/`
3. **Comparative Analysis**: Ensure `reporting/evaluation.py` measures dashboard vs spreadsheet correctly
4. **Reproducibility**: Ensure running the pipeline twice produces identical results
5. **Documentation**: Ensure `README.md` and `RESULTS.md` are auto-generated and never hand-typed

## Common Issues

| Issue | Solution |
|-------|----------|
| Results differ between runs | Check for randomness or non-deterministic code in pipeline |
| Tests fail on real data | Review `test_real_data_quality.py` for dataset-specific issues |
| Figures not generating | Check `reporting/figures.py` for Plotly export issues |
| Comparative analysis inconsistent | Verify spreadsheet baseline data is correct |
| Documentation out of sync | Run `python -m data_quality.reporting.report` to regenerate |

## Test Structure

```
tests/
  conftest.py              # Shared test fixtures
  test_engine.py           # Validation engine tests (14 rules)
  test_api.py              # Flask API endpoint tests
  test_legacy_pipeline.py   # Pipeline orchestration tests
  test_real_data_quality.py # Real data validation tests
  test_evaluation.py        # Comparative analysis tests
  test_preprocess.py       # Data cleaning tests
  test_hygiene.py          # Code quality tests
```

## Evidence Files

All evidence is generated in the `results/` directory:

- **RESULTS.md**: Detailed results with tables and statistics
- **figures/**: All 11 figures for research documentation
- **data_profiling.md**: Detailed data profiling results
- **system_testing_results.md**: System testing outcomes
- **comparative_results.md**: Dashboard vs spreadsheet comparison

## Dependencies

Your work depends on:
- **All Leads**: Provides the components you test and evaluate
- **Backend Lead**: Provides the pipeline you orchestrate
- **Diagnostics Lead**: Provides the validation logic you verify

Your work enables:
- **All Leads**: Evidence that their components work correctly
- **Research Documentation**: Measurable, reproducible results

## Next Steps

1. Review `data_quality/reporting/run_pipeline.py` to understand the evidence chain
2. Examine `data_quality/reporting/evaluation.py` to understand comparative analysis
3. Run `python -m pytest -v` to verify all tests pass
4. Run `python -m data_quality.reporting.run_pipeline` to generate full evidence
5. Review `results/RESULTS.md` to understand the output format
