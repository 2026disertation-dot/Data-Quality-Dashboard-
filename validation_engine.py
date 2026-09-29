"""
Validation Engine using Great Expectations
Implements comprehensive anomaly detection for budget and actual cost records
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json


# Tolerance, in ratio terms, allowed between cumulative spend and reported
# progress before a record is flagged by the progress_mismatch rule.
PROGRESS_COST_TOLERANCE = 0.5

# Caps applied to the two components of the quality score, so that a single
# record carrying many findings, or a single high-severity finding, can never
# drive the score to zero on its own.
MAX_SEVERITY_PENALTY = 20.0
SEVERITY_PENALTY_PER_FINDING = 10.0


def _is_readable_as_date(value) -> bool:
    """
    Report whether a value can be interpreted as a date.

    Dates reach the validator in several shapes: real ``Timestamp`` objects from
    a parsed frame, ISO text from a CSV, and Excel serial numbers from a
    spreadsheet.  All three describe a date, so all three are accepted.  Only a
    value with no date reading at all - free text, or a bare number that is not a
    plausible serial - is treated as a type error.

    Args:
        value: A single cell value.

    Returns:
        bool: True when the value can be read as a date.
    """
    if isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
        return True

    # Reject bare numbers before parsing.  ``pd.to_datetime(20110401)`` reads an
    # 8-digit integer as a date, but a stray figure in a date column is a type
    # error rather than a date, unless it looks like an Excel serial.
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, np.number)):
        if pd.isna(value):
            return False
        # Excel's serial date range starts at 1 (1900-01-01) and runs to about
        # 2958465 (the year 9999).
        return 1 <= float(value) <= 2958465

    try:
        parsed = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError, OverflowError):
        return False
    except Exception:
        return False

    return pd.notna(parsed)


def _count_flagged_rows(anomalies: dict) -> int:
    """
    Count the unique rows that carry at least one finding.

    The three count keys in a validation result mean different things and
    must not be used interchangeably:

    ``total_anomalies``
        Number of findings/events.  One row breaking four rules produces four
        findings.
    ``invalid_records``
        Number of *unique rows* with at least one finding.  That row is still
        a single bad record.
    ``valid_records``
        ``total_records`` minus the unique invalid rows.

    Deriving ``invalid_records`` from the finding count is what previously
    produced negative ``valid_records`` values (e.g. 31 findings across 8 rows
    reported as 8 valid out of 31), because a single row could be subtracted
    once per rule it broke.

    Args:
        anomalies: Mapping of anomaly category to a list of finding dicts.
            Each finding is expected to carry a ``row_index`` key; findings
            without one are ignored because they cannot be attributed to a
            specific record.

    Returns:
        int: Number of distinct rows referenced by the findings.
    """
    flagged = set()
    for findings in anomalies.values():
        for finding in findings:
            row_index = finding.get("row_index")
            if row_index is not None:
                flagged.add(row_index)
    return len(flagged)


def _cumulative_by_project(df: pd.DataFrame, column: str) -> pd.Series:
    """
    Cumulative sum of a cost column, computed within each project.

    The dashboard's records are time-phased: every row holds the budget and the
    cost of a single reporting period. Rules that compare cost against budget
    therefore have to work on cumulative totals, otherwise each period is
    judged against figures that really belong to the whole project.

    Args:
        df: Input DataFrame.
        column: Column to accumulate.

    Returns:
        pd.Series: Cumulative values aligned to the index of ``df``.
    """
    values = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

    # Without a project key (or with an ambiguous index) the best available
    # approximation is to accumulate in the order the rows were supplied.
    if "project_id" not in df.columns or df.index.has_duplicates:
        return values.cumsum()

    frame = pd.DataFrame({"value": values, "project": df["project_id"]}, index=df.index)

    # Accumulate in reporting order so the totals mean something.
    if "actual_date" in df.columns:
        frame["_order"] = pd.to_datetime(df["actual_date"], errors="coerce")
        frame = frame.sort_values(["project", "_order"], kind="stable")

    cumulative = frame.groupby("project", sort=False)["value"].cumsum()
    return cumulative.reindex(df.index)


def _cost_within_budget_multiple(df: pd.DataFrame, multiple: float) -> pd.Series:
    """
    Check that cumulative actual cost stays within ``multiple`` x cumulative budget.

    A reporting period with no planned budget is not an unlimited overrun: the
    plan may already have been spent while costs are still being incurred, so
    the period is judged on the cumulative position of its project. Periods
    whose project has no budget at all cannot be evaluated and are not flagged.

    Args:
        df: Input DataFrame.
        multiple: Largest acceptable multiple of the cumulative budget.

    Returns:
        pd.Series: Boolean mask, True where the record is acceptable.
    """
    cumulative_budget = _cumulative_by_project(df, "pmb_budget")
    cumulative_actual = _cumulative_by_project(df, "actual_cost")
    evaluable = cumulative_budget > 0
    return (~evaluable) | (cumulative_actual <= cumulative_budget * multiple)


def _progress_covers_expenditure(df: pd.DataFrame) -> pd.Series:
    """
    Check that cumulative spend stays within reported progress plus a tolerance.

    ``progress_pct`` is cumulative completion, so it is compared against the
    cumulative cost-to-budget ratio. Comparing it with a single period's
    figures would mix two different bases and flag every period of a project
    that is spending ahead of its curve.

    Args:
        df: Input DataFrame.

    Returns:
        pd.Series: Boolean mask, True where the record is acceptable.
    """
    cumulative_budget = _cumulative_by_project(df, "pmb_budget")
    cumulative_actual = _cumulative_by_project(df, "actual_cost")
    evaluable = cumulative_budget > 0
    ratio = cumulative_actual / cumulative_budget.where(evaluable)
    progress = pd.to_numeric(df["progress_pct"], errors="coerce").fillna(0.0) / 100.0
    return (~evaluable) | (ratio <= progress + PROGRESS_COST_TOLERANCE)


# Tolerance, in currency units, allowed when comparing a period movement against
# the previous one.  A negative movement is clipped to zero during cleaning, so
# any real fall is a defect rather than rounding noise.
MONOTONICITY_TOLERANCE = 0.01


def _cumulative_is_monotonic(df: pd.DataFrame, column: str) -> pd.Series:
    """
    Check that a project's cumulative cost total never falls over time.

    The dashboard's records are time-phased: each row holds the budget, cost and
    revenue of a *single* reporting period, so a period figure may legitimately
    be smaller than the one before it - spend is not uniform across a project.
    What must never fall is the running total, which is what every downstream
    variance and estimate-at-completion figure is built from.

    The check therefore accumulates each project's series in reporting order and
    compares every running total against the total that preceded it.  This is the
    only check in the rule set that depends on the *neighbouring* records: each
    total is defined by everything reported before it, so a restatement or a
    duplicated period is visible here and nowhere else.  No whole-column formula
    can see it, because ``MIN()`` and ``COUNTBLANK()`` compare each cell to a
    constant rather than to its neighbours.

    Args:
        df: Input DataFrame.
        column: Period-level cost column to accumulate.

    Returns:
        pd.Series: Boolean mask, True where the record is acceptable.
    """
    if column not in df.columns:
        return pd.Series(True, index=df.index)

    if "project_id" not in df.columns or df.index.has_duplicates:
        frame = pd.DataFrame(
            {"value": pd.to_numeric(df[column], errors="coerce"), "project": "all"},
            index=df.index,
        )
    else:
        frame = pd.DataFrame(
            {"value": pd.to_numeric(df[column], errors="coerce"),
             "project": df["project_id"]},
            index=df.index,
        )

    if "actual_date" in df.columns:
        frame["_order"] = pd.to_datetime(df["actual_date"], errors="coerce")
        frame = frame.sort_values(["project", "_order"], kind="stable")

    grouped = frame.groupby("project", sort=False)["value"]
    running_total = grouped.cumsum()

    # The total as it stood *before* this period was reported.  The shift has to
    # happen inside each project before the cumulative sum, otherwise the running
    # total of a second project is contaminated by the first one's.
    prior_total = grouped.shift(1).groupby(frame["project"], sort=False).cumsum()

    # A well-formed period movement is non-negative, so the running total can
    # only ever hold or rise.  A fall therefore means the period itself carries
    # a negative movement - a credit note or a restatement keyed against the
    # wrong period - which is exactly what this rule exists to catch.
    fell = (prior_total.notna()
            & running_total.notna()
            & (running_total < prior_total - MONOTONICITY_TOLERANCE))
    return (~fell).reindex(df.index).fillna(True)


class ValidationEngine:
    """
    Validation engine for detecting data quality anomalies in cost records.
    Supports both batch and incremental validation modes.
    """
    
    def __init__(self):
        """Initialize the validation engine with default rules"""
        self.validation_rules = self._get_default_validation_rules()
        self.validation_results = []
    
    def _get_default_validation_rules(self) -> dict:
        """
        Define default validation rules for cost records.
        
        Returns:
            dict: Validation rules configuration
        """
        return {
            "missing_values": {
                "fields": ["project_id", "time_period", "pmb_budget", "actual_cost", 
                          "progress_pct", "revenue_claimed", "actual_date", "baseline_start_date"],
                "severity": "high",
                "description": "Missing required fields"
            },
            "type_errors": {
                "field_types": {
                    "project_id": "string",
                    "time_period": "string",
                    "pmb_budget": "numeric",
                    "actual_cost": "numeric",
                    "progress_pct": "numeric",
                    "revenue_claimed": "numeric",
                    "actual_date": "datetime",
                    "baseline_start_date": "datetime"
                },
                "severity": "high",
                "description": "Data type mismatches"
            },
            "bounds_violations": {
                "numeric_bounds": {
                    "pmb_budget": {"min": 0},
                    "actual_cost": {"min": 0},
                    "progress_pct": {"min": 0, "max": 100},
                    "revenue_claimed": {"min": 0}
                },
                "severity": "medium",
                "description": "Values outside valid ranges"
            },
            "logical_anomalies": {
                "rules": [
                    {
                        "name": "actual_date_before_baseline",
                        "description": "Actual cost date must not precede baseline start date",
                        "check": lambda df: df["actual_date"] >= df["baseline_start_date"]
                    },
                    {
                        "name": "negative_cost_variance",
                        "description": "Cumulative actual cost should not exceed the cumulative budget by more than 200%",
                        "check": lambda df: _cost_within_budget_multiple(df, 3.0)
                    },
                    {
                        "name": "progress_mismatch",
                        "description": "Cumulative cost should not exceed reported progress by more than 0.5 of the budget",
                        "check": _progress_covers_expenditure
                    },
                    {
                        "name": "cumulative_cost_decrease",
                        "description": "Cumulative budget, cost and revenue must not fall between consecutive reporting periods",
                        "check": lambda df: (
                            _cumulative_is_monotonic(df, "pmb_budget")
                            & _cumulative_is_monotonic(df, "actual_cost")
                            & _cumulative_is_monotonic(df, "revenue_claimed")
                        )
                    }
                ],
                "severity": "high",
                "description": "Logical constraint violations"
            },
            "duplicates": {
                "fields": ["project_id", "time_period"],
                "severity": "medium",
                "description": "Duplicate records for same project and period"
            }
        }
    
    def validate_batch(self, df: pd.DataFrame) -> dict:
        """
        Validate an entire dataset in batch mode.
        
        Args:
            df: Input DataFrame to validate
            
        Returns:
            dict: Validation results with anomaly counts and details
        """
        results = {
            "mode": "batch",
            "total_records": len(df),
            "valid_records": 0,
            "invalid_records": 0,
            "anomalies": {
                "missing_values": [],
                "type_errors": [],
                "bounds_violations": [],
                "logical_anomalies": [],
                "duplicates": []
            },
            "summary": {}
        }
        
        # Check for missing values
        missing_results = self._check_missing_values(df)
        results["anomalies"]["missing_values"] = missing_results
        
        # Check for type errors
        type_results = self._check_type_errors(df)
        results["anomalies"]["type_errors"] = type_results
        
        # Check for bounds violations
        bounds_results = self._check_bounds_violations(df)
        results["anomalies"]["bounds_violations"] = bounds_results
        
        # Check for logical anomalies
        logical_results = self._check_logical_anomalies(df)
        results["anomalies"]["logical_anomalies"] = logical_results
        
        # Check for duplicates
        duplicate_results = self._check_duplicates(df)
        results["anomalies"]["duplicates"] = duplicate_results
        
        # Calculate summary statistics.  ``total_anomalies`` counts findings;
        # ``invalid_records`` counts unique offending rows.  Conflating the two
        # let a single record break several rules and drive ``valid_records``
        # negative.
        total_anomalies = sum(len(results["anomalies"][key]) for key in results["anomalies"])
        results["invalid_records"] = _count_flagged_rows(results["anomalies"])
        results["valid_records"] = max(0, results["total_records"] - results["invalid_records"])
        
        results["summary"] = {
            "missing_count": len(missing_results),
            "type_error_count": len(type_results),
            "bounds_violation_count": len(bounds_results),
            "logical_anomaly_count": len(logical_results),
            "duplicate_count": len(duplicate_results),
            "total_anomalies": total_anomalies
        }
        
        # Calculate quality score after summary is complete
        results["summary"]["data_quality_score"] = self._calculate_quality_score(results)
        
        return results
    
    def validate_incremental(self, new_records: pd.DataFrame, 
                           existing_df: pd.DataFrame = None) -> dict:
        """
        Validate newly arriving records in incremental mode.
        
        Args:
            new_records: New records to validate
            existing_df: Existing dataset (optional, for duplicate checking)
            
        Returns:
            dict: Validation results for new records
        """
        # ``total_records`` is the canonical count for both modes, so that
        # consumers (including the Streamlit dashboard) can read one key
        # regardless of how the data arrived.  ``new_records`` is retained as
        # an explicit alias because it reads more precisely in incremental mode
        # and existing callers rely on it.
        results = {
            "mode": "incremental",
            "total_records": len(new_records),
            "new_records": len(new_records),
            "valid_records": 0,
            "invalid_records": 0,
            "anomalies": {
                "missing_values": [],
                "type_errors": [],
                "bounds_violations": [],
                "logical_anomalies": [],
                "duplicates": []
            },
            "summary": {}
        }
        
        # Check for missing values
        missing_results = self._check_missing_values(new_records)
        results["anomalies"]["missing_values"] = missing_results
        
        # Check for type errors
        type_results = self._check_type_errors(new_records)
        results["anomalies"]["type_errors"] = type_results
        
        # Check for bounds violations
        bounds_results = self._check_bounds_violations(new_records)
        results["anomalies"]["bounds_violations"] = bounds_results
        
        # Check for logical anomalies.  The cross-record rules (cumulative
        # budget overrun, progress mismatch, cumulative monotonicity) are only
        # meaningful against a project's full time-phased history, so when
        # prior data is available it is prepended for evaluation and only
        # findings landing on the new rows are retained.  Validating new rows
        # in isolation reports every cumulative rule as trivially satisfied and
        # inflates the score.
        if existing_df is not None and len(existing_df) > 0:
            # Remember where each new record ends up once the two frames are
            # stacked, so findings can be reported against the caller's own
            # row labels (as the other checks do) rather than frame positions.
            new_labels = list(new_records.index)
            stacked = pd.concat([existing_df, new_records], ignore_index=True)
            offset = len(existing_df)

            context_findings = self._check_logical_anomalies(stacked)

            end = offset + len(new_records)
            logical_results = []
            for finding in context_findings:
                position = finding.get("row_index")
                if position is None or not (offset <= position < end):
                    continue  # Finding belongs to historical data
                logical_results.append({**finding, "row_index": new_labels[position - offset]})
        else:
            logical_results = self._check_logical_anomalies(new_records)

        results["anomalies"]["logical_anomalies"] = logical_results

        # Check for duplicates against existing data
        if existing_df is not None:
            duplicate_results = self._check_incremental_duplicates(new_records, existing_df)
        else:
            duplicate_results = self._check_duplicates(new_records)
        results["anomalies"]["duplicates"] = duplicate_results
        
        # Calculate summary statistics.  As in batch mode, findings and
        # offending records are counted separately so the record counts stay
        # non-negative and additive.
        total_anomalies = sum(len(results["anomalies"][key]) for key in results["anomalies"])
        results["invalid_records"] = _count_flagged_rows(results["anomalies"])
        results["valid_records"] = max(0, results["total_records"] - results["invalid_records"])
        
        results["summary"] = {
            "missing_count": len(missing_results),
            "type_error_count": len(type_results),
            "bounds_violation_count": len(bounds_results),
            "logical_anomaly_count": len(logical_results),
            "duplicate_count": len(duplicate_results),
            "total_anomalies": total_anomalies
        }
        
        # Calculate quality score after summary is complete
        results["summary"]["data_quality_score"] = self._calculate_quality_score(results)
        
        return results
    
    def _check_missing_values(self, df: pd.DataFrame) -> list:
        """Check for missing values in required fields"""
        anomalies = []
        required_fields = self.validation_rules["missing_values"]["fields"]
        
        for idx, row in df.iterrows():
            for field in required_fields:
                if pd.isna(row[field]) or row[field] == "":
                    anomalies.append({
                        "row_index": idx,
                        "field": field,
                        "anomaly_type": "missing_value",
                        "severity": self.validation_rules["missing_values"]["severity"],
                        "description": f"Missing value in required field: {field}",
                        "suggested_remediation": f"Provide a valid value for {field}"
                    })
        
        return anomalies
    
    def _check_type_errors(self, df: pd.DataFrame) -> list:
        """Check for data type mismatches

        A datetime field is judged by whether the value can be *interpreted* as
        a date, not by whether it already is one.  Spreadsheets and CSV exports
        hand back dates as text ("2011-04-01"), and the data contract's pandera
        schema leaves that column as ``str`` even with ``coerce=True`` set.
        Requiring an existing ``Timestamp`` therefore flagged every row of a
        perfectly valid dataset, which drove valid_records to zero and the score
        to 0.0 for data that is in fact clean.

        A value counts as a type error only when no date reading is possible -
        free text, a bare number, or a malformed date string.
        """
        anomalies = []
        field_types = self.validation_rules["type_errors"]["field_types"]
        
        for idx, row in df.iterrows():
            for field, expected_type in field_types.items():
                if field not in df.columns:
                    continue
                    
                value = row[field]
                if pd.isna(value):
                    continue  # Skip missing values (handled separately)
                
                type_error = False
                if expected_type == "numeric":
                    if not isinstance(value, (int, float, np.number)):
                        type_error = True
                elif expected_type == "string":
                    if not isinstance(value, str):
                        type_error = True
                elif expected_type == "datetime":
                    if not _is_readable_as_date(value):
                        type_error = True
                
                if type_error:
                    anomalies.append({
                        "row_index": idx,
                        "field": field,
                        "anomaly_type": "type_error",
                        "severity": self.validation_rules["type_errors"]["severity"],
                        "description": f"Type error in {field}: expected {expected_type}, got {type(value).__name__}",
                        "suggested_remediation": f"Convert {field} to {expected_type}"
                    })
        
        return anomalies
    
    def _check_bounds_violations(self, df: pd.DataFrame) -> list:
        """Check for values outside valid ranges"""
        anomalies = []
        numeric_bounds = self.validation_rules["bounds_violations"]["numeric_bounds"]
        
        for idx, row in df.iterrows():
            for field, bounds in numeric_bounds.items():
                if field not in df.columns:
                    continue
                    
                value = row[field]
                if pd.isna(value):
                    continue
                
                # A value of the wrong type (for example a text string in a
                # numeric field) is reported by the type check. Comparing it
                # numerically here would raise and abort the entire batch.
                if isinstance(value, bool) or not isinstance(
                    value, (int, float, np.number)
                ):
                    continue
                
                violation = False
                violation_type = ""
                
                if "min" in bounds and value < bounds["min"]:
                    violation = True
                    violation_type = f"below minimum ({bounds['min']})"
                elif "max" in bounds and value > bounds["max"]:
                    violation = True
                    violation_type = f"above maximum ({bounds['max']})"
                
                if violation:
                    anomalies.append({
                        "row_index": idx,
                        "field": field,
                        "anomaly_type": "bounds_violation",
                        "severity": self.validation_rules["bounds_violations"]["severity"],
                        "description": f"Bounds violation in {field}: value {value} is {violation_type}",
                        "suggested_remediation": f"Ensure {field} is within valid range"
                    })
        
        return anomalies
    
    def _check_logical_anomalies(self, df: pd.DataFrame) -> list:
        """Check for logical constraint violations"""
        anomalies = []
        logical_rules = self.validation_rules["logical_anomalies"]["rules"]
        
        for rule in logical_rules:
            rule_name = rule["name"]
            rule_description = rule["description"]
            check_function = rule["check"]
            
            try:
                # Apply the check function
                mask = check_function(df)
                
                # Find rows that violate the rule
                violations = df[~mask]
                
                for idx, row in violations.iterrows():
                    anomalies.append({
                        "row_index": idx,
                        "field": "multiple",
                        "anomaly_type": "logical_anomaly",
                        "severity": self.validation_rules["logical_anomalies"]["severity"],
                        "description": f"Logical anomaly: {rule_description}",
                        "suggested_remediation": f"Review data for {rule_name} violation"
                    })
            except Exception as e:
                # If check fails, skip it
                continue
        
        return anomalies
    
    def _check_duplicates(self, df: pd.DataFrame) -> list:
        """Check for duplicate records"""
        anomalies = []
        duplicate_fields = self.validation_rules["duplicates"]["fields"]
        
        # Find duplicates based on specified fields
        duplicates = df[df.duplicated(subset=duplicate_fields, keep=False)]
        
        for idx, row in duplicates.iterrows():
            key_values = {field: row[field] for field in duplicate_fields}
            anomalies.append({
                "row_index": idx,
                "field": ", ".join(duplicate_fields),
                "anomaly_type": "duplicate",
                "severity": self.validation_rules["duplicates"]["severity"],
                "description": f"Duplicate record: {key_values}",
                "suggested_remediation": "Remove duplicate record or verify if it's legitimate"
            })
        
        return anomalies
    
    def _check_incremental_duplicates(self, new_records: pd.DataFrame, 
                                     existing_df: pd.DataFrame) -> list:
        """Check for duplicates between new records and existing data"""
        anomalies = []
        duplicate_fields = self.validation_rules["duplicates"]["fields"]
        
        for idx, new_row in new_records.iterrows():
            # Check if this record already exists in the existing dataset
            for field in duplicate_fields:
                if field not in existing_df.columns or field not in new_records.columns:
                    continue
            
            # Create a filter to find matching records
            mask = pd.Series([True] * len(existing_df))
            for field in duplicate_fields:
                mask = mask & (existing_df[field] == new_row[field])
            
            matching_records = existing_df[mask]
            
            if len(matching_records) > 0:
                key_values = {field: new_row[field] for field in duplicate_fields}
                anomalies.append({
                    "row_index": idx,
                    "field": ", ".join(duplicate_fields),
                    "anomaly_type": "duplicate",
                    "severity": self.validation_rules["duplicates"]["severity"],
                    "description": f"Duplicate record with existing data: {key_values}",
                    "suggested_remediation": "Record already exists in dataset"
                })
        
        return anomalies
    
    def _calculate_quality_score(self, results: dict) -> float:
        """
        Calculate overall data quality score based on validation results.

        The score is built from two bounded components so that it always lands
        inside [0, 100] and always degrades gracefully:

        1. **Record validity** - the share of records carrying no finding at
           all.  This is the dominant term and uses the unique-row counts, not
           the finding count, so a handful of bad rows in a large dataset does
           not zero the score.
        2. **Severity penalty** - a severity-weighted finding density, capped
           at ``MAX_SEVERITY_PENALTY``, which distinguishes a record with one
           mild issue from one with many severe ones.

        The previous implementation subtracted the raw finding count from the
        record count, so a dataset where a few rows broke several rules scored
        0.0 despite being mostly clean.

        Args:
            results: Validation results dictionary

        Returns:
            float: Quality score between 0 and 100
        """
        total_records = results.get("total_records", results.get("new_records", 0))
        if total_records <= 0:
            return 100.0

        # Prefer the unique-row counts.  They are clamped to the row total so a
        # stale or externally supplied value cannot push the score out of range.
        invalid_records = min(max(int(results.get("invalid_records", 0)), 0), total_records)
        valid_records = min(max(total_records - invalid_records, 0), total_records)

        record_validity = (valid_records / total_records) * 100

        severity_weights = {
            "high": 2.0,
            "medium": 1.0,
            "low": 0.5
        }

        weighted_findings = 0.0
        for findings in results.get("anomalies", {}).values():
            for finding in findings:
                severity = finding.get("severity", "medium")
                weighted_findings += severity_weights.get(severity, 1.0)

        # Findings per record, not per dataset, so the penalty reflects
        # concentration of problems rather than absolute dataset size.
        severity_penalty = (weighted_findings / total_records) * SEVERITY_PENALTY_PER_FINDING
        severity_penalty = min(severity_penalty, MAX_SEVERITY_PENALTY)

        score = record_validity - severity_penalty
        return round(max(0.0, min(100.0, score)), 2)
    
    def get_validation_summary(self, results: dict) -> str:
        """
        Generate a human-readable summary of validation results.
        
        Args:
            results: Validation results dictionary
            
        Returns:
            str: Formatted summary
        """
        mode = results["mode"]
        total = results.get("total_records", results.get("new_records", 0))
        valid = results["valid_records"]
        invalid = results["invalid_records"]
        score = results["summary"]["data_quality_score"]
        
        summary = f"""
Validation Summary ({mode.upper()} Mode)
====================================
Total Records: {total}
Valid Records: {valid}
Invalid Records: {invalid}
Data Quality Score: {score}/100

Anomaly Breakdown:
- Missing Values: {results['summary']['missing_count']}
- Type Errors: {results['summary']['type_error_count']}
- Bounds Violations: {results['summary']['bounds_violation_count']}
- Logical Anomalies: {results['summary']['logical_anomaly_count']}
- Duplicates: {results['summary']['duplicate_count']}
"""
        return summary


if __name__ == "__main__":
    # Test the validation engine
    import pandas as pd
    
    # Create sample data with various anomalies
    test_data = pd.DataFrame({
        "project_id": ["PROJ001", "PROJ002", None, "PROJ004", "PROJ001"],
        "time_period": ["Week-1", "Week-2", "Week-3", "Week-1", "Week-1"],
        "pmb_budget": [100000.0, 150000.0, 200000.0, -50000.0, 100000.0],
        "actual_cost": [95000.0, 145000.0, 180000.0, 300000.0, 95000.0],
        "progress_pct": [45.0, 50.0, 150.0, 30.0, 45.0],
        "revenue_claimed": [90000.0, 140000.0, 170000.0, 280000.0, 90000.0],
        "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29", "2024-01-08", "2024-01-15"]),
        "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-10", "2024-01-01"])
    })
    
    # Initialize validation engine
    engine = ValidationEngine()
    
    # Run batch validation
    results = engine.validate_batch(test_data)
    
    # Print summary
    print(engine.get_validation_summary(results))
    
    # Print detailed anomalies
    print("\nDetailed Anomalies:")
    for anomaly_type, anomalies in results["anomalies"].items():
        if anomalies:
            print(f"\n{anomaly_type.upper()}:")
            for anomaly in anomalies[:3]:  # Show first 3 of each type
                print(f"  - {anomaly['description']}")