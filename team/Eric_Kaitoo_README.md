# Theory & Integration Lead - Eric Kaitoo (B01848427)

## Role Overview

As the Theory & Integration Lead, you are responsible for **Objective 1** (Theoretical and Architectural Foundation) and **Objective 6** (Integration and Dual-Mode Consistency Assurance). Your work establishes the coherent theoretical and architectural framework that guides all subsequent design decisions and ensures dual-mode consistency across the entire system.

## Project Objectives

### Objective 1: Theoretical and Architectural Foundation
To establish a coherent theoretical and architectural framework by synthesising data quality dimensions, project cost-control principles and dashboard design knowledge, and by defining a conceptual data contract that governs dual-mode operation.

**Key References:**
- Wang and Strong (1996) - Data quality dimensions
- Batini and Scannapieco (2016) - Data and information quality
- Hevner et al. (2004) - Design Science Research
- Project Management Institute (2021) - PMBOK Guide

### Objective 6: Integration and Dual-Mode Consistency Assurance
To integrate the diagnostic, backend, frontend and evaluation components into a coherent artefact and to ensure dual-mode consistency across the entire system, so that the same data contract and validation logic apply identically to historical and incremental data.

## Individual Contribution Statement

My individual contribution encompasses the theoretical framing, architectural integration, and dual-mode consistency assurance for the group's data quality dashboard. Specifically, I am responsible for:

1. **Establishing and maintaining the overarching Design Science Research framing** that maps problem identification, artefact design, demonstration, and evaluation
2. **Synthesising the core theoretical foundations** - data quality dimensions, project cost-control principles, and dashboard design knowledge - into a coherent conceptual model
3. **Defining the high-level system architecture** and the conceptual data contract that govern interactions between the diagnostic, backend, frontend, and evaluation components
4. **Ensuring that every major component explicitly supports both batch and incremental operating modes**, including live API submissions, and that dual-mode consistency is maintained across the system
5. **Producing an integrative theoretical and architectural report** that strengthens the academic contribution and practical coherence of the final dashboard artefact

All theoretical and integrative artefacts, including the conceptual model, architectural diagrams, and the conceptual data contract, will be produced independently by me and submitted as part of my final dissertation. My contribution is explicitly scoped to the theoretical and integrative layer; I do not claim responsibility for the detailed implementation of diagnostic metrics, backend pipelines, frontend visualisations, or formal system testing protocols, which remain the responsibility of the respective component leads.

## Dissertation Structure

Your dissertation should include the following sections aligned with your objectives:

1. **Introduction** (5 marks)
   - Problem identification in multi-project data quality
   - Research gap in dual-mode validation
   - Overview of Design Science Research approach

2. **Literature Review** (15 marks)
   - Data quality dimensions (Wang and Strong, 1996)
   - Design Science Research methodology (Hevner et al., 2004)
   - Dashboard design principles (Few, 2013)
   - Project controls and cost data quality (PMI, 2021)

3. **Research Design** (15 marks)
   - Conceptual model development
   - High-level system architecture
   - Conceptual data contract definition
   - Dual-mode consistency framework

4. **Implementation** (25 marks)
   - Architectural integration documentation
   - Data contract specifications
   - Integration between components
   - Dual-mode consistency verification

5. **Testing** (10 marks)
   - Integration testing results
   - Dual-mode consistency validation
   - API integration verification

6. **Presentation of Results** (10 marks)
   - Architectural diagrams
   - Conceptual model visualisation
   - Integration evidence
   - Dual-mode consistency metrics

7. **Conclusions** (10 marks)
   - Contribution to theoretical knowledge
   - Practical implications for project controls
   - Limitations and future work

8. **Critical Self-Evaluation** (10 marks)
   - Reflection on theoretical contributions
   - Challenges in architectural integration
   - Lessons learned from dual-mode consistency assurance

## Key Responsibilities

### 1. Data Quality Framework
- **Location**: `data_quality/contracts/`
- Define the four data quality dimensions: Accuracy, Completeness, Consistency, Integrity
- Maintain the data contract specifications (`raw.py`, `derived.py`)
- Ensure theoretical alignment between research claims and implementation

### 2. Integration Architecture
- **Location**: Root-level integration points
- Coordinate between backend pipeline, frontend dashboard, and API services
- Ensure the shared Validator is used consistently across batch, incremental, and live modes
- Maintain the unified data contract that all components reference

### 3. Research Alignment
- **Location**: Documentation and validation
- Ensure the implementation aligns with the research document methodology
- Validate that theoretical claims match actual measured results
- Review `results/RESULTS.md` for consistency with research expectations

## Core Files to Understand

```
data_quality/
  contracts/
    raw.py          # Raw 10-field data contract (R1-R12 rules)
    derived.py      # Derived 8-field data contract (R13-R14 rules)
  engine/
    validator.py    # Shared Validator used across all modes
    rules.py        # Rule definitions and theoretical basis
  pipeline/
    quality.py      # Dimension scoring formulas
```

## Key Concepts

### Data Quality Dimensions
1. **Accuracy**: Proportion of values matching declared datatypes
2. **Completeness**: Proportion of non-missing values in required fields
3. **Consistency**: Proportion of unique composite keys across records
4. **Integrity**: Proportion of records passing logical cross-record checks

### Integration Points
- **Batch Mode**: `data_quality/pipeline/runner.py` → `validator.py`
- **Incremental Mode**: `data_quality/pipeline/runner.py` → `validator.py`
- **Live API**: `data_quality/api/server.py` → `validator.py`
- **Dashboard**: `app.py` → `data_quality/pipeline/quality.py`

## Commands for Your Role

```bash
# View the data contract specifications
cat data_quality/contracts/raw.py
cat data_quality/contracts/derived.py

# Test the shared validator across all modes
python -m pytest tests/test_engine.py -v

# Run the full pipeline to verify integration
python -m data_quality.reporting.run_pipeline

# Check dimension scoring implementation
python -c "from data_quality.pipeline.quality import DimensionScorer; help(DimensionScorer)"
```

## Research Alignment Tasks

1. **Review Data Contract**: Ensure rules R1-R14 in `contracts/raw.py` and `contracts/derived.py` match the research methodology
2. **Validate Dimension Scores**: Check that `pipeline/quality.py` implements the formulas correctly
3. **Cross-Reference Results**: Compare `results/RESULTS.md` with the research document to identify discrepancies
4. **Integration Testing**: Verify that batch, incremental, and API modes all use the same Validator

## Common Issues

| Issue | Solution |
|-------|----------|
| Dimension scores don't match research | Check formulas in `pipeline/quality.py` against research definitions |
| API returns different results than batch | Verify both use the same `Validator` instance from `engine/validator.py` |
| Data contract violations in cleaned data | Review `preprocess/clean.py` to ensure it respects the contract |

## Dependencies

Your work depends on:
- **Backend Lead**: Provides the pipeline implementation
- **Diagnostics Lead**: Provides the validation engine
- **Evaluation Lead**: Provides the evidence chain

Your work enables:
- **Frontend Lead**: Uses dimension scores for visualization
- **All Leads**: Unified theoretical framework for their components

## Next Steps

1. Read the research document to understand the theoretical framework
2. Review `data_quality/contracts/` to understand the data contract implementation
3. Examine `data_quality/engine/validator.py` to understand the shared validation logic
4. Run `python -m data_quality.reporting.run_pipeline` to see the full integration in action
