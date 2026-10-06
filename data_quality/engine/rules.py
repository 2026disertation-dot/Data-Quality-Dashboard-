"""
Rules R1-R12 (Table 4.2).

The rules are split into two groups, and the split matters:

**Record-level rules** (R1-R4, R5, R11, R12)
    Judge a single record using only values inside that record.  They scale
    linearly with volume and need no history, so they behave identically whether
    a record arrives in a batch, on its own, or through the live API.

**Cross-record rules** (R6, R7, R8, R9)
    Judge a record against its neighbours - its other rows, or the row before it
    in its own series.  These are the rules that whole-column spreadsheet
    formulas structurally cannot express, and they are the reason the measured
    dashboard beats the spreadsheet baseline.

Honest limitation
-----------------
Of the cross-record rules, only **R9** genuinely requires historical context.
R6, R7 and R8 compare values *within* the data under validation (a project's
names, a code's descriptions, a series' date order), so a single record batch
carries everything they need.  R6, R7 and R11 in particular return zero
violations on the real dataset, which is a genuine result rather than a gap: the
source workbooks are structurally consistent.  That is reported honestly in
Chapter 6 rather than inflated.
"""

from __future__ import annotations

from typing import Callable

import functools

import pandas as pd

from .findings import Finding

# --------------------------------------------------------------------------
# Rule catalogue.  This table is the executable form of Table 4.2 and is the
# single source for rule metadata used by the reports, so the dissertation and
# the code cannot drift apart.
# --------------------------------------------------------------------------
RULE_CATALOGUE: dict[str, dict[str, str]] = {
    "R1": {
        "rule": "Required fields must not be missing",
        "dimension": "completeness",
        "example": "Missing project_id or ac_cum",
    },
    "R2": {
        "rule": "Fields must match declared datatypes",
        "dimension": "accuracy",
        "example": "period_date not a valid date",
    },
    "R3": {
        "rule": "period_index must be >= 1",
        "dimension": "accuracy",
        "example": "period_index = 0",
    },
    "R4": {
        "rule": "Cumulative money values must be >= 0",
        "dimension": "accuracy",
        "example": "Negative ac_cum",
    },
    "R5": {
        "rule": "Composite key must be unique",
        "dimension": "consistency",
        "example": "Duplicate project_id + wbs_code + period_index",
    },
    "R6": {
        "rule": "project_name must be consistent per project_id",
        "dimension": "consistency",
        "example": "One project_id carrying two names",
    },
    "R7": {
        "rule": "wbs_description must be consistent per project_id + wbs_code",
        "dimension": "consistency",
        "example": "Same WBS code with different descriptions",
    },
    "R8": {
        "rule": "period_date must increase with period_index",
        "dimension": "integrity",
        "example": "Period 2 dated before period 1",
    },
    "R9": {
        "rule": "Cumulative values must not decrease over time",
        "dimension": "integrity",
        "example": "ac_cum falls from 5000 to 4000",
    },
    "R10": {
        "rule": "period_date must fall within the project reporting window",
        "dimension": "accuracy",
        "example": "Date outside the project's own observed range",
    },
    "R11": {
        "rule": "source_file must be consistent with project_id",
        "dimension": "consistency",
        "example": "P01 records attributed to the P02 workbook",
    },
    "R13": {
        "rule": "Cumulative actual cost must stay within 3x cumulative budget",
        "dimension": "integrity",
        "example": "Project running far beyond its planned baseline",
    },
    "R14": {
        "rule": "Cumulative spend must not exceed reported progress by more than 0.5",
        "dimension": "integrity",
        "example": "Spend at 90% of budget while reporting 40% progress",
    },
    "R12": {
        "rule": "wbs_code must carry a non-empty description",
        "dimension": "completeness",
        "example": "Empty wbs_description",
    },
    "R13": {
        "rule": "Cumulative actual cost must stay within 3x cumulative budget",
        "dimension": "integrity",
        "example": "Running cost position exceeds the agreed multiple",
    },
    "R14": {
        "rule": "Cumulative spend must not outrun reported progress",
        "dimension": "integrity",
        "example": "Cost ratio exceeds progress_pct plus tolerance",
    },
}


def rule_dimension(rule_id: str) -> str:
    """Return the data quality dimension a rule belongs to."""
    return RULE_CATALOGUE[rule_id]["dimension"]


def _finding(rule_id: str, key: str, field: str, description: str, remediation: str) -> Finding:
    """Build a :class:`Finding` with the rule's declared dimension and severity."""
    from .findings import SEVERITY

    dimension = RULE_CATALOGUE[rule_id]["dimension"]
    return Finding(
        rule_id=rule_id,
        dimension=dimension,
        record_key=key,
        field=field,
        severity=SEVERITY[dimension],
        description=description,
        remediation=remediation,
    )


def record_key(row: pd.Series, key_columns: list[str]) -> str:
    """Build a stable composite key string for a row."""
    return "|".join(str(row.get(column, "")) for column in key_columns)


@functools.lru_cache(maxsize=8192)
def _readable_as_date(value) -> bool:
    """Report whether a value can be interpreted as a date.

    Cached because this is called once per cell per date column and the dataset
    holds only 14 distinct dates across 2,727 rows: without it, pandas re-runs
    format inference on the same 14 strings thousands of times.  Only affects
    speed, not results.

    Dates arrive as real Timestamps, as ISO text from CSV, or as Excel serial
    numbers from a spreadsheet.  All three describe a date.  A bare number that
    is not a plausible serial, or free text, is a type error.

    Requiring an existing ``Timestamp`` instead would flag every row of a valid
    upload, because pandera leaves date columns as ``str`` even with
    ``coerce=True``.
    """
    from datetime import datetime

    import numpy as np

    if isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, np.number)):
        if pd.isna(value):
            return False
        # Excel serials run from 1 (1900-01-01) to about 2958465 (year 9999).
        return 1 <= float(value) <= 2958465
    try:
        parsed = pd.to_datetime(value, errors="raise")
    except Exception:
        return False
    return bool(pd.notna(parsed))


def make_finding(rule_id: str, key: str, field: str, description: str, remediation: str) -> Finding:
    """Build a :class:`Finding` carrying the rule's declared dimension."""
    from .findings import SEVERITY

    dimension = RULE_CATALOGUE[rule_id]["dimension"]
    return Finding(
        rule_id=rule_id,
        dimension=dimension,
        record_key=key,
        field=field,
        severity=SEVERITY[dimension],
        description=description,
        remediation=remediation,
    )


# Re-exported so rule implementations share one naming convention.
_finding = make_finding