"""
Cross-record rules: R6, R7, R8, R9, R10.

These judge a record against its neighbours, which is precisely what a
whole-column spreadsheet formula cannot express.  A formula such as ``MIN()`` or
``COUNTBLANK()`` can tell you that a column is dirty; it cannot tell you *which
row* is wrong, and it cannot see a series that falls between two periods.

Honest limitation
-----------------
Of these, only **R9** genuinely requires historical context beyond the data
under validation: each running total is defined by everything reported before it.
R6, R7 and R8 compare values *within* the frame being validated, so a single
record batch already carries what they need.  On the real dataset R6, R7 and
R11 return zero violations - the source workbooks are structurally consistent -
which is reported honestly rather than inflated.
"""

from __future__ import annotations

import pandas as pd

from .findings import Finding
from .rules import _finding, record_key

#: Fraction by which cumulative spend may exceed the spend implied by reported
#: progress before R14 treats a period as a mismatch (spec default 20%).
PROGRESS_TOLERANCE = 0.20

#: Largest multiple of cumulative budget tolerated before R13 flags a period.
BUDGET_OVERRUN_MULTIPLE = 3.0


def rule_r6_project_name_consistency(
    df: pd.DataFrame, key_columns: list[str]
) -> list[Finding]:
    """R6: one project_id must map to exactly one project_name."""
    findings: list[Finding] = []
    if not {"project_id", "project_name"} <= set(df.columns):
        return findings
    per_project = df.groupby("project_id")["project_name"].nunique()
    conflicting = set(per_project[per_project > 1].index)
    for _, row in df.iterrows():
        if row["project_id"] in conflicting:
            findings.append(
                _finding(
                    "R6",
                    record_key(row, key_columns),
                    "project_name",
                    f"project_id '{row['project_id']}' maps to more than one "
                    "project_name",
                    "Align project_name with the master record",
                )
            )
    return findings


def rule_r7_wbs_description_consistency(
    df: pd.DataFrame, key_columns: list[str]
) -> list[Finding]:
    """R7: one (project_id, wbs_code) must map to one wbs_description."""
    findings: list[Finding] = []
    if not {"project_id", "wbs_code", "wbs_description"} <= set(df.columns):
        return findings
    group_cols = ["project_id", "wbs_code"]
    per_group = df.groupby(group_cols)["wbs_description"].nunique()
    conflicting = set(per_group[per_group > 1].index)
    for _, row in df.iterrows():
        if (row["project_id"], row["wbs_code"]) in conflicting:
            findings.append(
                _finding(
                    "R7",
                    record_key(row, key_columns),
                    "wbs_description",
                    f"wbs_code '{row['wbs_code']}' in project "
                    f"'{row['project_id']}' carries more than one description",
                    "Align wbs_description with the master record",
                )
            )
    return findings


def rule_r8_date_ordering(
    df: pd.DataFrame, key_columns: list[str], group_columns: list[str] | None = None
) -> list[Finding]:
    """R8: reporting dates must increase with the reporting period.

    R8 is a project-period rule (Chapter 3 Table 3.9): on the derived tier the
    periods are ordered by their ``time_period`` label and ``actual_date`` must
    not move backwards.  The WBS-level shape (ordered by ``period_index``,
    carrying ``period_date``) is handled as well, so the same function can be
    exercised directly by the unit tests.
    """
    findings: list[Finding] = []

    # -- derived / project-period view ----------------------------------
    if {"actual_date", "time_period"} <= set(df.columns):
        present = [c for c in (group_columns or ["project_id"]) if c in df.columns]
        for _, group in df.groupby(present):
            ordered = group.assign(
                _order=_natural_keys(group["time_period"])
            ).sort_values("_order", kind="stable")
            dates = pd.to_datetime(ordered["actual_date"], errors="coerce")
            for i in range(1, len(ordered)):
                current, previous = dates.iloc[i], dates.iloc[i - 1]
                if pd.notna(current) and pd.notna(previous) and current < previous:
                    row = ordered.iloc[i]
                    findings.append(
                        _finding(
                            "R8",
                            record_key(row, key_columns),
                            "actual_date",
                            f"actual_date {current:%Y-%m-%d} precedes the "
                            f"{previous:%Y-%m-%d} reported at the previous period",
                            "Correct actual_date to maintain chronological order",
                        )
                    )
        return findings

    # -- WBS-level fallback ----------------------------------------------
    group_columns = group_columns or ["project_id", "wbs_code"]
    needed = set(group_columns) | {"period_date", "period_index"}
    if not needed <= set(df.columns):
        return findings
    present = [c for c in group_columns if c in df.columns]
    for _, group in df.groupby(present):
        ordered = group.sort_values("period_index")
        dates = pd.to_datetime(ordered["period_date"], errors="coerce")
        previous = dates.shift(1)
        for position in dates.index[dates < previous]:
            row = ordered.loc[position]
            findings.append(
                _finding(
                    "R8",
                    record_key(row, key_columns),
                    "period_date",
                    f"period_date {dates.loc[position]:%Y-%m-%d} precedes the "
                    "previous period in the same series",
                    "Verify period date ordering",
                )
            )
    return findings

def rule_r9_cumulative_monotonicity(
    df: pd.DataFrame,
    key_columns: list[str],
    group_columns: list[str] | None = None,
    value_columns: list[str] | None = None,
) -> list[Finding]:
    """R9: a cumulative series must never fall.

    This is a project-period rule (Chapter 3 Table 3.9).  Periods are placed in
    reporting order and every cumulative column must be non-decreasing; a
    restatement that falls below the previous period is the defect R9 exists to
    catch.  On the derived tier the columns are the cumulative contract fields
    ``pmb_budget``, ``actual_cost`` and ``revenue_claimed`` (Chapter 4
    Challenge 6).  The WBS-level shape (ordered by ``period_index``) is handled
    too so the function can be exercised directly by the unit tests.
    """
    findings: list[Finding] = []
    group_columns = group_columns or ["project_id"]
    present = [c for c in group_columns if c in df.columns]
    if not present:
        return findings

    if "period_index" in df.columns:
        by_label = False
        if value_columns is None:
            value_columns = ["pv_cum", "ac_cum", "ev_cum"]
    elif "time_period" in df.columns:
        by_label = True
        if value_columns is None:
            value_columns = ["pmb_budget", "actual_cost", "revenue_claimed"]
    else:
        return findings

    for _, group in df.groupby(present):
        if by_label:
            ordered = group.assign(
                _order=_natural_keys(group["time_period"])
            ).sort_values("_order", kind="stable")
            labels = ordered["time_period"].tolist()
        else:
            ordered = group.sort_values("period_index", kind="stable")
            labels = ordered["period_index"].tolist()

        for column in value_columns:
            if column not in ordered.columns:
                continue
            series = pd.to_numeric(ordered[column], errors="coerce")
            for i in range(1, len(ordered)):
                current, previous = series.iloc[i], series.iloc[i - 1]
                if pd.isna(current) or pd.isna(previous):
                    continue
                if current < previous:
                    # The falling record is the restatement, so the finding
                    # belongs to it; the previous period is the baseline it
                    # wrongly undercuts.
                    row = ordered.iloc[i]
                    findings.append(
                        _finding(
                            "R9",
                            record_key(row, key_columns),
                            column,
                            f"{column} fell from {previous:,.2f} at "
                            f"{labels[i - 1]} to {current:,.2f} at {labels[i]}",
                            f"Correct the {column} restatement so it does not decrease",
                        )
                    )
    return findings


def rule_r13_budget_overrun(
    df: pd.DataFrame, key_columns: list[str], multiple: float = BUDGET_OVERRUN_MULTIPLE
) -> list[Finding]:
    """R13: cumulative actual cost must stay within ``multiple`` x budget.

    The derived contract stores cumulative figures, so each row already carries
    the project's cumulative actual cost and cumulative planned budget; the rule
    compares them directly (Chapter 4 Code Block 4.5).  A period with no planned
    budget cannot be judged and is not flagged.
    """
    findings: list[Finding] = []
    needed = {"actual_cost", "pmb_budget"}
    if not needed <= set(df.columns):
        return findings

    for _, row in df.iterrows():
        actual = row["actual_cost"]
        budget = row["pmb_budget"]
        if pd.isna(actual) or pd.isna(budget) or budget <= 0:
            continue
        if actual > budget * multiple:
            findings.append(
                _finding(
                    "R13",
                    record_key(row, key_columns),
                    "actual_cost",
                    f"Cumulative actual cost {actual:,.2f} exceeds "
                    f"{multiple:g}x cumulative budget {budget:,.2f}",
                    "Review cost allocation against the PMB",
                )
            )
    return findings


def rule_r14_progress_mismatch(
    df: pd.DataFrame, key_columns: list[str], tolerance: float = PROGRESS_TOLERANCE
) -> list[Finding]:
    """R14: cumulative spend must not outrun reported progress.

    ``progress_pct`` is cumulative completion, so the expected spend at that
    progress is ``pmb_budget x progress_pct/100``.  A period is flagged when the
    cumulative actual cost exceeds that expectation by more than ``tolerance``
    (the spec default is 20%, Chapter 4 Code Block 4.5).
    """
    findings: list[Finding] = []
    needed = {"actual_cost", "pmb_budget", "progress_pct"}
    if not needed <= set(df.columns):
        return findings

    for _, row in df.iterrows():
        actual = row["actual_cost"]
        budget = row["pmb_budget"]
        progress = row["progress_pct"]
        if pd.isna(actual) or pd.isna(budget) or pd.isna(progress):
            continue
        if budget <= 0:
            continue
        expected_max_spend = budget * (progress / 100.0)
        if actual > expected_max_spend * (1.0 + tolerance):
            findings.append(
                _finding(
                    "R14",
                    record_key(row, key_columns),
                    "actual_cost",
                    f"Actual cost {actual:,.2f} exceeds expected spend "
                    f"{expected_max_spend:,.2f} for {progress:g}% progress "
                    f"(tolerance {tolerance * 100:.0f}%)",
                    "Review cost allocation or progress reporting",
                )
            )
    return findings


def _natural_keys(periods) -> pd.Series:
    """Build a natural sort key so ``Month-10`` follows ``Month-2``."""
    def key(label):
        text = str(label)
        prefix, separator, number = text.rpartition("-")
        if separator and number.isdigit():
            return (prefix, int(number), "")
        return (text, 0, "")

    if periods is None:
        return pd.Series(dtype=object)
    return pd.Series([key(p) for p in periods], index=periods.index, dtype=object)


def rule_r10_date_window(
    df: pd.DataFrame, key_columns: list[str], group_columns: list[str]
) -> list[Finding]:
    """R10: period_date must fall inside the series' own observed window.

    A date beyond the series' latest reporting period indicates a mistyped
    period rather than a genuine observation.  The window is derived from the
    data under validation, so the rule needs no external calendar.  Only dates
    *beyond* the window are flagged; an early date legitimately occurs because a
    baseline start date precedes the first reporting period.

    The window is the latest date the *other* rows of the series report at this
    period or a later one: a date later than every subsequent report has no
    corroboration and is therefore a candidate mistyping.  The comparison is
    deliberately leave-one-out - an earlier version compared each date with the
    maximum of its own group, which the date itself necessarily helped define,
    so the rule could never fire on any input.  A series' final period has no
    later observation to judge it against and so defines the window rather than
    being tested against it.
    """
    findings: list[Finding] = []
    needed = set(group_columns) | {"period_date", "period_index"}
    if not needed <= set(df.columns):
        return findings
    present = [c for c in group_columns if c in df.columns]
    for _, group in df.groupby(present):
        ordered = group.sort_values("period_index")
        dates = pd.to_datetime(ordered["period_date"], errors="coerce")
        periods = ordered["period_index"].tolist()
        count = len(ordered)
        for i in range(count):
            date = dates.iloc[i]
            if pd.isna(date):
                continue
            peers = [
                dates.iloc[j]
                for j in range(count)
                if j != i and periods[j] >= periods[i] and pd.notna(dates.iloc[j])
            ]
            if peers and date > max(peers):
                row = ordered.iloc[i]
                findings.append(
                    _finding(
                        "R10",
                        record_key(row, key_columns),
                        "period_date",
                        f"period_date {date:%Y-%m-%d} falls beyond the series' "
                        "observed reporting window",
                        "Verify the reported period date",
                    )
                )
    return findings
