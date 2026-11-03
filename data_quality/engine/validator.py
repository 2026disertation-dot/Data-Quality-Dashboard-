"""
The validator: orchestrates both contract tiers and produces a result dict.

This is the single entry point used by batch mode, incremental mode, the live
API and the dashboard.  All four call :meth:`Validator.validate`, so no mode can
drift from another - which is the multi-mode consistency claim in Chapter 4.

Rule gating follows Chapter 3 Table 3.9:

* WBS-level view:      R1-R7, R10, R11, R12
* Project-period view: R8, R9, R13, R14

Each rule runs only against the tier for which its evaluation view is defined,
so no rule is invoked against columns that do not exist on its target tier
(Chapter 4, Challenges 5 and 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ..contracts.raw import RAW_CUMULATIVE_COLUMNS, RAW_KEY
from ..contracts.derived import DERIVED_CUMULATIVE_COLUMNS, DERIVED_KEY
from .cross_record_rules import (
    rule_r6_project_name_consistency,
    rule_r7_wbs_description_consistency,
    rule_r8_date_ordering,
    rule_r9_cumulative_monotonicity,
    rule_r10_date_window,
    rule_r13_budget_overrun,
    rule_r14_progress_mismatch,
)
from .findings import DIMENSIONS, Finding, summarise_counts
from .record_rules import (
    rule_r1_missing_required,
    rule_r2_datatypes,
    rule_r3_period_index,
    rule_r4_negative_values,
    rule_r5_duplicate_key,
    rule_r11_source_file_consistency,
    rule_r12_wbs_description_present,
)
from .rules import _finding

Tier = Literal["raw", "derived"]

#: Columns that must be treated as text identifiers rather than numbers.
#:
#: ``wbs_code`` is the important one.  A CSV read infers it as ``int64``, which
#: would (a) make every row a spurious R2 type error and (b) destroy leading
#: zeros, so WBS 011 and WBS 11 would collide.  Coercion happens before any rule
#: runs so the rules judge the value, not the reader's guess at its type.
IDENTIFIER_COLUMNS = ["project_id", "project_name", "source_file",
                      "wbs_code", "wbs_description", "time_period"]

RAW_REQUIRED = [
    "project_id", "project_name", "source_file", "wbs_code", "wbs_description",
    "period_date", "period_index", "pv_cum", "ac_cum", "ev_cum",
]
RAW_EXPECTED_TYPES = {
    "project_id": "string", "project_name": "string", "source_file": "string",
    "wbs_code": "string", "wbs_description": "string",
    "period_date": "datetime", "period_index": "numeric",
    "pv_cum": "numeric", "ac_cum": "numeric", "ev_cum": "numeric",
}

DERIVED_REQUIRED = [
    "project_id", "time_period", "pmb_budget", "actual_cost", "progress_pct",
    "revenue_claimed", "actual_date", "baseline_start_date",
]
DERIVED_EXPECTED_TYPES = {
    "project_id": "string", "time_period": "string",
    "pmb_budget": "numeric", "actual_cost": "numeric", "progress_pct": "numeric",
    "revenue_claimed": "numeric", "actual_date": "datetime",
    "baseline_start_date": "datetime",
}


@dataclass
class ValidationResult:
    """Outcome of validating one frame against one contract tier."""

    tier: Tier
    total_records: int
    findings: list[Finding] = field(default_factory=list)
    schema_errors: list[Finding] = field(default_factory=list)

    @property
    def all_findings(self) -> list[Finding]:
        """Schema errors first, then rule findings."""
        return self.schema_errors + self.findings

    @property
    def invalid_record_keys(self) -> set:
        """Return distinct record keys associated with findings."""
        return {
            finding.record_key
            for finding in self.all_findings
            if finding.record_key is not None
        }

    @property
    def counts(self) -> dict[str, int]:
        """Record-level counts, with valid and invalid always summing to total."""
        return summarise_counts(self.all_findings, self.total_records)

    @property
    def invalid_records(self) -> int:
        """Return the number of distinct invalid records."""
        return len(self.invalid_record_keys)
    @property
    def valid_records(self) -> int:
        """Return the number of records without findings."""
        return self.total_records - self.invalid_records
    def findings_by_rule(self) -> dict[str, int]:
        """Count findings per rule id, ordered R1..R12."""
        out: dict[str, int] = {}
        for f in self.all_findings:
            out[f.rule_id] = out.get(f.rule_id, 0) + 1
        return {k: out[k] for k in sorted(out)}

    def findings_by_dimension(self) -> dict[str, int]:
        """Count findings per data quality dimension."""
        out = {d: 0 for d in DIMENSIONS}
        for f in self.all_findings:
            out[f.dimension] = out.get(f.dimension, 0) + 1
        return out

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "tier": self.tier,
            **self.counts,
            "by_rule": self.findings_by_rule(),
            "by_dimension": self.findings_by_dimension(),
            "findings": [f.to_dict() for f in self.all_findings],
        }



def _unreadable_dates(df: pd.DataFrame) -> dict[str, list]:
    """Locate date cells that are present but cannot be read as a date."""
    from .rules import _readable_as_date

    bad: dict[str, list] = {}
    for column in ("period_date", "actual_date", "baseline_start_date"):
        if column not in df.columns:
            continue
        positions = [
            int(position)
            for position, value in df[column].items()
            if not pd.isna(value) and not _readable_as_date(value)
        ]
        if positions:
            bad[column] = positions
    return bad


def normalise_types(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce identifier columns to text before any rule runs.

    A CSV reader infers ``wbs_code`` as ``int64``.  Left alone, that makes every
    row a spurious R2 type error and silently drops leading zeros, so WBS 011
    and WBS 11 would collide.  Coercing first means the rules judge the value
    rather than the reader's guess at its type.

    Dates are parsed with ``errors="coerce"`` so an unparseable date becomes a
    null and is then reported by R1, rather than raising and aborting the batch.

    Args:
        df: Frame as read from disk or submitted by a caller.

    Returns:
        pd.DataFrame: A copy with identifiers as strings and dates parsed.
    """
    out = df.copy()
    # Remember which date cells were supplied but unreadable.  Coercion turns
    # them into NaT, which R1 would then report as *missing* - misattributing a
    # type error to a completeness rule.  Flagging them first keeps R2 honest.
    out.attrs["unreadable_dates"] = _unreadable_dates(df)
    for column in IDENTIFIER_COLUMNS:
        if column in out.columns:
            # Plain astype(str) would turn None into the literal string "None",
            # which R1 can no longer detect as missing.  Missing stays missing.
            series = out[column]
            out[column] = series.where(series.isna(), series.astype(str))
    for column in ("period_date", "actual_date", "baseline_start_date"):
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    return out


def _unreadable_date_findings(
    df: pd.DataFrame, key: list[str], expected: dict[str, str]
) -> list[Finding]:
    """Report date cells that were supplied but cannot be read as dates."""
    from .rules import _readable_as_date

    findings: list[Finding] = []
    for column in expected:
        if expected.get(column) != "datetime" or column not in df.columns:
            continue
        for position, value in df[column].items():
            if pd.isna(value) or _readable_as_date(value):
                continue
            row = df.loc[position]
            findings.append(
                _finding(
                    "R2",
                    "|".join(str(row.get(c, "")) for c in key),
                    column,
                    f"Field '{column}' cannot be read as a date: {value!r}",
                    f"Supply {column} as an ISO date",
                )
            )
    return findings


class Validator:
    """Validate raw or derived frames against rules R1-R12."""

    def validate(
        self,
        df: pd.DataFrame,
        tier: Tier = "raw",
        existing: pd.DataFrame | None = None,
    ) -> ValidationResult:
        """Validate ``df`` against the contract for ``tier``.

        Args:
            df: Frame to validate.
            tier: ``"raw"`` for WBS-level records, ``"derived"`` for the
                time-phased project records.
            existing: Prior records of the same tier.  When supplied, R9 is
                evaluated over ``existing`` stacked beneath ``df`` and only
                findings landing on the new rows are returned, so a restatement
                that reverses a running total is still caught.

        Returns:
            ValidationResult: Counts plus every finding.
        """
        if tier not in ("raw", "derived"):
            raise ValueError(f"Unsupported tier: {tier!r}. Expected 'raw' or 'derived'.")
        key = list(RAW_KEY) if tier == "raw" else list(DERIVED_KEY)
        expected = RAW_EXPECTED_TYPES if tier == "raw" else DERIVED_EXPECTED_TYPES

        # Captured before coercion: an unreadable date becomes NaT afterwards,
        # and NaT reads as *missing*, which would misattribute a type error to R1.
        unreadable = _unreadable_date_findings(df, key, expected)
        normalised = normalise_types(df)

        if tier == "raw":
            result = self._validate_raw(normalised, existing)
        else:
            result = self._validate_derived(normalised, existing)
        result.findings.extend(unreadable)
        return result

    # -- shared helpers ---------------------------------------------------

    @staticmethod
    def _schema_findings(
        df: pd.DataFrame, required: list[str]
    ) -> list[Finding]:
        """Report columns the contract requires but the frame does not carry.

        Missing *values* are rule R1's job; this only reports a structurally
        absent column, which no per-record rule could ever see.
        """
        findings: list[Finding] = []
        absent = [c for c in required if c not in df.columns]
        for column in absent:
            findings.append(
                _finding(
                    "R1",
                    "<frame>",
                    column,
                    f"Required column '{column}' is absent from the input",
                    f"Supply the '{column}' column",
                )
            )
        return findings

    # -- raw tier ---------------------------------------------------------

    def _validate_raw(
        self, df: pd.DataFrame, existing: pd.DataFrame | None
    ) -> ValidationResult:
        """Validate WBS-level records against rules R1-R7, R10, R11, R12.

        The WBS-level view (Chapter 3 Table 3.9) applies the record-level rules
        and the cross-record rules that read WBS columns.  R8, R9, R13 and R14
        are project-period rules and are deliberately **not** run here.
        """
        key = list(RAW_KEY)
        result = ValidationResult(tier="raw", total_records=len(df))
        result.schema_errors = self._schema_findings(df, RAW_REQUIRED)

        series = ["project_id", "wbs_code"]

        result.findings.extend(rule_r1_missing_required(df, key, RAW_REQUIRED))
        result.findings.extend(rule_r2_datatypes(df, key, RAW_EXPECTED_TYPES))
        result.findings.extend(rule_r3_period_index(df, key))
        result.findings.extend(
            rule_r4_negative_values(df, key, RAW_CUMULATIVE_COLUMNS)
        )
        result.findings.extend(rule_r5_duplicate_key(df, key))
        result.findings.extend(rule_r6_project_name_consistency(df, key))
        result.findings.extend(rule_r7_wbs_description_consistency(df, key))
        result.findings.extend(rule_r10_date_window(df, key, series))
        result.findings.extend(rule_r11_source_file_consistency(df, key))
        result.findings.extend(rule_r12_wbs_description_present(df, key))
        return result

    # -- derived tier -----------------------------------------------------

    def _validate_derived(
        self, df: pd.DataFrame, existing: pd.DataFrame | None
    ) -> ValidationResult:
        """Validate project-period records against rules R8, R9, R13, R14.

        The project-period view (Chapter 3 Table 3.9) applies only the four
        rules defined on the derived contract.  The WBS-specific rules
        (R1-R7, R10-R12) read columns that do not exist on the 8-field derived
        contract and are deliberately **not** run here (Chapter 4, Challenge 7).
        R8 and R9 read a project's period sequence, so prior periods supplied as
        ``existing`` are stacked as history and only findings landing on the
        submitted rows are returned.
        """
        key = list(DERIVED_KEY)
        result = ValidationResult(tier="derived", total_records=len(df))
        result.schema_errors = self._schema_findings(df, DERIVED_REQUIRED)

        # R8/R9 read the project's period sequence.  When prior periods are
        # supplied, stack them so a restatement that reverses a running total,
        # or a date that moves backwards, is still caught; then keep only the
        # findings that land on the submitted rows.
        context = df
        if (
            existing is not None
            and len(existing)
            and {"project_id", "time_period"} <= set(existing.columns)
        ):
            context = pd.concat([existing, df], ignore_index=True)

        history_findings = rule_r8_date_ordering(context, key)
        history_findings += rule_r9_cumulative_monotonicity(
            context, key, ["project_id"], DERIVED_CUMULATIVE_COLUMNS
        )
        if context is not df:
            new_keys = {
                "|".join(str(v) for v in row)
                for row in df[key].itertuples(index=False, name=None)
            }
            history_findings = [
                f for f in history_findings if f.record_key in new_keys
            ]

        result.findings.extend(history_findings)
        result.findings.extend(rule_r13_budget_overrun(df, key))
        result.findings.extend(rule_r14_progress_mismatch(df, key))
        return result
