"""
The validator: orchestrates both contract tiers and produces a result dict.

This is the single entry point used by batch mode, incremental mode and the
live API.  All three call :meth:`Validator.validate`, so no mode can drift from
another - which is the dual-mode consistency claim in Chapter 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from ..contracts.raw import RAW_CUMULATIVE_COLUMNS, RAW_KEY
from ..contracts.derived import DERIVED_KEY, DERIVED_MONEY_COLUMNS
from .cross_record_rules import (
    rule_r13_budget_overrun,
    rule_r14_progress_mismatch,
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
    def counts(self) -> dict[str, int]:
        """Record-level counts, with valid and invalid always summing to total."""
        return summarise_counts(self.all_findings, self.total_records)

    @property
    def invalid_records(self) -> int:
        return self.counts["invalid_records"]

    @property
    def valid_records(self) -> int:
        return self.counts["valid_records"]

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
    for column in IDENTIFIER_COLUMNS:
        if column in out.columns:
            out[column] = out[column].astype(str)
    for column in ("period_date", "actual_date", "baseline_start_date"):
        if column in out.columns:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    return out


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
        df = normalise_types(df)
        if tier == "raw":
            return self._validate_raw(df, existing)
        return self._validate_derived(df, existing)

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

    @staticmethod
    def _r9_with_context(
        df: pd.DataFrame,
        existing: pd.DataFrame | None,
        key_columns: list[str],
        group_columns: list[str] | None = None,
        value_columns: list[str] | None = None,
    ) -> list[Finding]:
        """Run R9, using prior records as history when available.

        R9 is the only rule that needs context from outside the new batch: a
        running total is defined by everything reported before it.  When
        ``existing`` is supplied the two frames are stacked and only findings
        whose composite key belongs to the new rows are returned.
        """
        group_columns = group_columns or ["project_id", "wbs_code"]
        value_columns = value_columns or RAW_CUMULATIVE_COLUMNS

        needed = set(group_columns) | {"period_index"} | set(value_columns)
        if not needed <= set(df.columns):
            return []

        if existing is None or len(existing) == 0:
            return rule_r9_cumulative_monotonicity(
                df, key_columns, group_columns, value_columns
            )

        if not needed <= set(existing.columns):
            return []

        stacked = pd.concat([existing, df], ignore_index=True)
        findings = rule_r9_cumulative_monotonicity(
            stacked, key_columns, group_columns, value_columns
        )

        # Keep only findings that land on a row the caller actually submitted.
        new_keys = {
            "|".join(str(v) for v in row)
            for row in df[key_columns].itertuples(index=False, name=None)
        }
        return [f for f in findings if f.record_key in new_keys]

    # -- raw tier ---------------------------------------------------------

    def _validate_raw(
        self, df: pd.DataFrame, existing: pd.DataFrame | None
    ) -> ValidationResult:
        """Validate WBS-level records against rules R1-R12."""
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
        result.findings.extend(rule_r8_date_ordering(df, key, series))
        result.findings.extend(rule_r10_date_window(df, key, series))
        result.findings.extend(rule_r11_source_file_consistency(df, key))
        result.findings.extend(rule_r12_wbs_description_present(df, key))
        result.findings.extend(
            self._r9_with_context(df, existing, key, series, RAW_CUMULATIVE_COLUMNS)
        )
        return result

    # -- derived tier -----------------------------------------------------

    def _validate_derived(
        self, df: pd.DataFrame, existing: pd.DataFrame | None
    ) -> ValidationResult:
        """Validate time-phased project records.

        The derived tier has no WBS columns, so the WBS-specific rules R6, R7,
        R11 and R12 do not apply and are skipped rather than reported as
        passes.  R8 is re-expressed as the baseline-date relationship, which is
        the derived contract's equivalent constraint.
        """
        key = list(DERIVED_KEY)
        result = ValidationResult(tier="derived", total_records=len(df))
        result.schema_errors = self._schema_findings(df, DERIVED_REQUIRED)

        money = [c for c in DERIVED_MONEY_COLUMNS if c in df.columns]

        result.findings.extend(rule_r1_missing_required(df, key, DERIVED_REQUIRED))
        result.findings.extend(rule_r2_datatypes(df, key, DERIVED_EXPECTED_TYPES))
        result.findings.extend(rule_r4_negative_values(df, key, money))
        result.findings.extend(rule_r5_duplicate_key(df, key))
        result.findings.extend(self._baseline_date_ordering(df, key))
        result.findings.extend(self._cumulative_with_context(df, existing, key))
        result.findings.extend(
            self._r9_with_context(df, existing, key, ["project_id"], money)
        )

        # R13 and R14 read cumulative running totals, so they are evaluated over
        # the new records stacked on any prior history: a period only breaches a
        # cumulative limit once earlier periods are counted.
        combined = df if existing is None or len(existing) == 0 else pd.concat(
            [existing, df], ignore_index=True
        )
        result.findings.extend(rule_r13_budget_overrun(combined, key))
        result.findings.extend(rule_r14_progress_mismatch(combined, key))

        # Report only findings that land on rows the caller submitted.
        if combined is not df:
            new_keys = {
                "|".join(str(v) for v in row)
                for row in df[key].itertuples(index=False, name=None)
            }
            result.findings = [f for f in result.findings if f.record_key in new_keys]

        return result

    @staticmethod
    def _cumulative_with_context(
        df: pd.DataFrame, existing: pd.DataFrame | None, key: list[str]
    ) -> list[Finding]:
        """Run R13 and R14, using prior records as history when available.

        Both rules read a project's running totals, so validating a single new
        period in isolation would judge it against a near-empty cumulative
        position and either miss a genuine overrun or invent one.  When
        ``existing`` is supplied the frames are stacked and only findings whose
        composite key belongs to the new rows are returned.
        """
        from .cross_record_rules import _in_period_order, _running_total  # noqa: F401

        needed = {"project_id", "pmb_budget", "actual_cost", "progress_pct"}
        if not needed <= set(df.columns):
            return []

        frame = df
        if existing is not None and len(existing) and needed <= set(existing.columns):
            stacked = pd.concat([existing, df], ignore_index=True)
            findings = rule_r13_budget_overrun(stacked, key) + rule_r14_progress_mismatch(stacked, key)
            new_keys = {
                "|".join(str(v) for v in row)
                for row in df[key].itertuples(index=False, name=None)
            }
            return [f for f in findings if f.record_key in new_keys]

        frame = df
        return rule_r13_budget_overrun(frame, key) + rule_r14_progress_mismatch(frame, key)

    @staticmethod
    def _baseline_date_ordering(df: pd.DataFrame, key: list[str]) -> list[Finding]:
        """R8 on the derived tier: actual_date must not precede the baseline.

        This is the derived contract's counterpart to the raw tier's
        period-date ordering rule, and it is a genuine per-record check: it
        needs no neighbouring row.
        """
        findings: list[Finding] = []
        needed = {"actual_date", "baseline_start_date"}
        if not needed <= set(df.columns):
            return findings

        dates = pd.to_datetime(df["actual_date"], errors="coerce")
        baselines = pd.to_datetime(df["baseline_start_date"], errors="coerce")
        for position in df.index[dates < baselines]:
            row = df.loc[position]
            findings.append(
                _finding(
                    "R8",
                    "|".join(str(row.get(c, "")) for c in key),
                    "actual_date",
                    f"actual_date {row['actual_date']:%Y-%m-%d} precedes "
                    f"baseline_start_date {row['baseline_start_date']:%Y-%m-%d}",
                    "Verify the reporting period against the project baseline",
                )
            )
        return findings
        return [f for f in findings if f.record_key in new_keys]
