"""
Record-level rules: R1-R5, R11, R12.

These judge a record using only values inside that record, so they need no
history and behave identically in batch mode, incremental mode and through the
live API.  Scale is linear in volume.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .findings import Finding
from .rules import _finding, _readable_as_date, record_key


def rule_r1_missing_required(
    df: pd.DataFrame, key_columns: list[str], required: list[str]
) -> list[Finding]:
    """R1: every required field must be present.

    An empty string counts as absent, because a required text field holding
    ``""`` is as unusable downstream as one holding a null.
    """
    findings: list[Finding] = []
    for _, row in df.iterrows():
        for column in required:
            if column not in df.columns:
                continue
            value = row[column]
            if pd.isna(value) or (isinstance(value, str) and value.strip() == ""):
                findings.append(
                    _finding(
                        "R1",
                        record_key(row, key_columns),
                        column,
                        f"Required field '{column}' is missing",
                        f"Supply a value for '{column}'",
                    )
                )
    return findings


def rule_r2_datatypes(
    df: pd.DataFrame, key_columns: list[str], expected: dict[str, str]
) -> list[Finding]:
    """R2: values must be readable as the declared datatype.

    A date is judged by whether it can be *read* as a date, not by whether it
    already is one, so ISO text and Excel serials are accepted.
    """
    findings: list[Finding] = []
    for _, row in df.iterrows():
        for column, kind in expected.items():
            if column not in df.columns:
                continue
            value = row[column]
            if pd.isna(value):
                continue  # R1 already reports missing values

            if kind == "datetime":
                ok = _readable_as_date(value)
            elif kind == "numeric":
                ok = isinstance(value, (int, float, np.number)) and not isinstance(value, bool)
            elif kind == "string":
                ok = isinstance(value, str)
            else:
                ok = True

            if not ok:
                findings.append(
                    _finding(
                        "R2",
                        record_key(row, key_columns),
                        column,
                        f"Field '{column}' expected {kind}, got {type(value).__name__}",
                        f"Convert '{column}' to {kind}",
                    )
                )
    return findings


def rule_r3_period_index(df: pd.DataFrame, key_columns: list[str]) -> list[Finding]:
    """R3: period_index must be at least 1."""
    findings: list[Finding] = []
    if "period_index" not in df.columns:
        return findings
    for _, row in df.iterrows():
        value = row["period_index"]
        if pd.isna(value) or value < 1:
            if pd.isna(value):
                continue
            findings.append(
                _finding(
                    "R3",
                    record_key(row, key_columns),
                    "period_index",
                    f"period_index is {value}, must be >= 1",
                    "Renumber reporting periods from 1",
                )
            )
    return findings

def rule_r4_negative_values(
    df: pd.DataFrame, key_columns: list[str], columns: list[str]
) -> list[Finding]:
    """R4: cumulative money values must be non-negative."""
    findings: list[Finding] = []
    for _, row in df.iterrows():
        for column in columns:
            if column not in df.columns:
                continue
            value = row[column]
            if pd.isna(value) or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float, np.number)):
                continue  # R2 reports the type problem instead
            if value < 0:
                findings.append(
                    _finding(
                        "R4",
                        record_key(row, key_columns),
                        column,
                        f"{column} is {value}, must be >= 0",
                        f"Correct {column} to a non-negative value",
                    )
                )
    return findings


def rule_r5_duplicate_key(df: pd.DataFrame, key_columns: list[str]) -> list[Finding]:
    """R5: the composite key must be unique.

    Every row in a colliding group is flagged, not just the later copy, so a
    practitioner sees the whole group instead of inferring it.
    """
    findings: list[Finding] = []
    present = [c for c in key_columns if c in df.columns]
    if len(present) < len(key_columns):
        return findings
    duplicated = df.duplicated(subset=present, keep=False)
    for _, row in df[duplicated].iterrows():
        key = record_key(row, key_columns)
        findings.append(
            _finding(
                "R5",
                key,
                ", ".join(key_columns),
                f"Composite key {key} is not unique",
                "Remove or re-key the duplicate record",
            )
        )
    return findings


def rule_r11_source_file_consistency(
    df: pd.DataFrame, key_columns: list[str]
) -> list[Finding]:
    """R11: source_file must be consistent with project_id.

    The real workbooks name each file after the project it contains, e.g.
    ``P018 - P01 Airport Carpark.xlsx``.  A record whose filename carries a
    different project code than its own ``project_id`` is misattributed.
    """
    findings: list[Finding] = []
    if not {"project_id", "source_file"} <= set(df.columns):
        return findings
    for _, row in df.iterrows():
        source = row["source_file"]
        if pd.isna(source) or not isinstance(source, str):
            continue
        codes = set(re.findall(r"P\d{2}", source))
        # Only judge when the filename actually carries a project code.
        if codes and str(row["project_id"]) not in codes:
            findings.append(
                _finding(
                    "R11",
                    record_key(row, key_columns),
                    "source_file",
                    f"source_file '{source}' does not match project_id "
                    f"'{row['project_id']}'",
                    "Correct the project attribution for this record",
                )
            )
    return findings


def rule_r12_wbs_description_present(
    df: pd.DataFrame, key_columns: list[str]
) -> list[Finding]:
    """R12: a WBS code must carry a description."""
    findings: list[Finding] = []
    if not {"wbs_code", "wbs_description"} <= set(df.columns):
        return findings
    for _, row in df.iterrows():
        description = row["wbs_description"]
        if pd.isna(description) or str(description).strip() == "":
            findings.append(
                _finding(
                    "R12",
                    record_key(row, key_columns),
                    "wbs_description",
                    f"wbs_code '{row['wbs_code']}' has no description",
                    "Supply a work package description",
                )
            )
    return findings
