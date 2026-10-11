# Backend / Pipeline Lead - Obed Sarbeng Amponsah (B01845424)

## Role Overview

As the Backend / Pipeline Lead, you are responsible for **Objective 3** (Design and Enforce Pipelines). Your work encompasses the end-to-end design, implementation, and validation of the data processing pipeline and validation engine for the group's data quality dashboard.

## Project Objectives

### Objective 3: Design and Enforce Pipelines
To develop and deploy a modular, reproducible data pipeline and validation engine in Python that uniformly applies the formal data contract in batch and incremental modes, exposes a live Flask API endpoint for real-time validation of incoming records, handles dynamic validation errors at runtime, and generates structured error logs and machine-readable quality annotations.

**Key References:**
- Hevner et al. (2004) - Design Science Research
- Batini and Scannapieco (2016) - Data and information quality
- Python ecosystem (pandas, Flask, pandera/Great Expectations)

## Individual Contribution Statement

My individual contribution encompasses the end-to-end design, implementation, and validation of the data processing pipeline and validation engine for the group's data quality dashboard. Specifically, I am responsible for:

1. **Designing and implementing a modular, version-controlled data ingestion and transformation pipeline** capable of processing both the full historical Project Portfolio Dataset and newly arriving cost records
2. **Defining and implementing the formal data contract** - required fields, data types, allowed ranges, and logical constraints - based on the conceptual contract defined by the Theory Lead
3. **Developing validation logic that detects missing values, unexpected data types, out-of-bounds numerical inputs, format conflicts, and logical anomalies** in batch, incremental, and live API modes
4. **Building and deploying a live Flask API endpoint** that validates incoming records synchronously, returns structured JSON responses with field-level error detail, and writes all outcomes to a flagged-records table for dashboard consumption
5. **Ensuring complete reproducibility through configuration-driven pipelines, version control, and identical behaviour** between development, testing, and demonstration environments

All pipeline artefacts, including the version-controlled code, data contract schema, validation engine, Flask API, structured error logs, and technical documentation, will be produced independently by me and submitted as part of my final dissertation. I will coordinate closely with the Diagnostics Lead (responsible for detection rules), the Frontend Lead (responsible for consuming flagged data and querying the API), the Theory Lead (responsible for architectural alignment), and the Evaluation Lead (responsible for testing the pipeline and API) to ensure seamless component integration while maintaining clear boundaries of individual responsibility. My contribution is explicitly scoped to the data engineering and pipeline layer; I do not claim responsibility for metric definition, visual design, impact quantification, or formal system testing protocols, which are assigned to other group members.

## Dissertation Structure

Your dissertation should include the following sections aligned with your objectives:

1. **Introduction** (5 marks)
   - Importance of robust data pipelines in multi-project environments
   - Gap in dual-mode pipeline implementations
   - Overview of pipeline and API design approach

2. **Literature Review** (15 marks)
   - Data pipeline architectures and patterns
   - API design for real-time validation
   - Schema validation frameworks (pandera, Great Expectations)
   - Flask and Python web frameworks

3. **Research Design** (15 marks)
   - Pipeline architecture design
   - Data contract implementation methodology
   - API endpoint specification
   - Error handling and logging strategy

4. **Implementation** (25 marks)
   - Data ingestion and transformation pipeline
   - Validation engine implementation
   - Flask API endpoint development
   - Configuration-driven design and reproducibility

5. **Testing** (10 marks)
   - Pipeline testing results
   - API endpoint testing
   - Error handling verification
   - Reproducibility validation

6. **Presentation of Results** (10 marks)
   - Pipeline architecture diagrams
   - API endpoint documentation
   - Performance metrics
   - Error log examples

7. **Conclusions** (10 marks)
   - Contribution to pipeline engineering knowledge
   - Practical implications for real-time validation
   - Limitations and future work

8. **Critical Self-Evaluation** (10 marks)
   - Reflection on pipeline development challenges
   - Lessons learned from API implementation
   - Challenges in dual-mode consistency

## Key Responsibilities

### 1. Data Pipeline
- **Location**: `data_quality/pipeline/`
- Implement batch and incremental processing modes
- Orchestrate the full data flow: ingestion → validation → scoring → reporting
- Ensure the pipeline uses the shared Validator consistently

### 2. Flask API Service
- **Location**: `data_quality/api/`
- Implement the live validation API endpoints
- Provide synchronous validation for external systems
- Ensure API uses the same Validator as batch/incremental modes

### 3. Data Preprocessing
- **Location**: `data_quality/preprocess/`
- Download and clean the Kaggle dataset
- Transform raw WBS-level data into contract-compliant format
- Generate test datasets with controlled defect injection

## Core Files to Understand

```
data_quality/
  pipeline/
    runner.py           # Main pipeline orchestrator (batch/incremental)
    quality.py          # Dimension scoring implementation
  api/
    server.py           # Flask API endpoints (POST /validate, GET /status, GET /flagged)
  preprocess/
    download.py         # Kaggle dataset download
    clean.py            # Data cleaning and transformation
  fixtures/
    builder.py          # Controlled defect injection for testing
```

## Key Concepts

### Processing Modes

**Batch Mode:**
- Processes entire dataset at once
- Used for historical analysis and baseline establishment
- Output: Full validation report with all findings

**Incremental Mode:**
- Processes new records against existing baseline
- Used for continuous monitoring
- Output: Validation results for new records only

**Live API Mode:**
- Synchronous validation of individual records
- Used for real-time integration with external systems
- Output: Immediate HTTP response with validation status

### API Endpoints

- **POST /validate**: Accepts a record, validates it, returns 200/202/422
- **GET /status**: Returns current validation status and metrics
- **GET /flagged**: Returns all currently flagged records

## Commands for Your Role

```bash
# Run the full pipeline (batch mode)
python -m data_quality.reporting.run_pipeline

# Run batch validation only
python -m data_quality.pipeline.runner --mode batch

# Run incremental validation
python -m data_quality.pipeline.runner --mode incremental

# Start the Flask API server
python -m data_quality.api.server

# Download the Kaggle dataset
python -m data_quality.preprocess.download

# Clean the raw data
python -m data_quality.preprocess.clean

# Test the API
python -m pytest tests/test_api.py -v

# Test the pipeline
python -m pytest tests/test_legacy_pipeline.py -v
```

## Pipeline Tasks

1. **Batch Processing**: Ensure `pipeline/runner.py` correctly processes full datasets
2. **Incremental Processing**: Ensure new records are validated against existing baseline
3. **API Integration**: Ensure Flask API uses the same Validator as other modes
4. **Data Cleaning**: Ensure `preprocess/clean.py` produces contract-compliant data
5. **Performance**: Optimize pipeline for large datasets

## Common Issues

| Issue | Solution |
|-------|----------|
| Pipeline fails on large datasets | Check memory usage in `pipeline/runner.py`, consider chunking |
| API returns different results than batch | Verify both use the same `Validator` instance |
| Incremental mode doesn't detect new anomalies | Check baseline comparison logic in `pipeline/runner.py` |
| Cleaned data violates contract | Review transformation logic in `preprocess/clean.py` |

## Pipeline Flow

```
Raw Data (Kaggle)
    ↓
preprocess/download.py
    ↓
preprocess/clean.py
    ↓
kaggle_cleaned_data.csv
    ↓
pipeline/runner.py (batch/incremental)
    ↓
engine/validator.py
    ↓
pipeline/quality.py (dimension scoring)
    ↓
reporting/ (evidence generation)
```

## API Flow

```
HTTP POST /validate
    ↓
api/server.py
    ↓
engine/validator.py
    ↓
HTTP Response (200/202/422)
```

## Dependencies

Your work depends on:
- **Theory Lead**: Provides the data contract specifications
- **Diagnostics Lead**: Provides the Validator and rules

Your work enables:
- **Frontend Lead**: Provides API endpoints for dashboard integration
- **Evaluation Lead**: Provides processed data for evidence generation

## Next Steps

1. Review `data_quality/pipeline/runner.py` to understand the orchestration
2. Examine `data_quality/api/server.py` to understand the API implementation
3. Run `python -m data_quality.reporting.run_pipeline` to test the full pipeline
4. Start the API server: `python -m data_quality.api.server` and test with curl/Postman
5. Review `data_quality/preprocess/clean.py` to understand data transformation
