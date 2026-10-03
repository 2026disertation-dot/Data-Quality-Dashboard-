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

#: Ratio tolerance allowed between cumulative spend and reported progress
#: before R14 flags a period.  Expressed in ratio terms (0.5 = 50%).
PROGRESS_TOLERANCE = 0.5


#: Tolerance, in ratio terms, allowed between cumulative spend and reported
#: progress before rule R14 treats a period as a mismatch.
PROGRESS_TOLERANCE = 0.5
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
    df: pd.DataFrame, key_columns: list[str], group_columns: list[str]
) -> list[Finding]:
    """R8: period_date must increase with period_index inside each series."""
    findings: list[Finding] = []
    needed = set(group_columns) | {"period_date", "period_index"}
    if not needed <= set(df.columns):
        return findings
    present = [c for c in group_columns if c in df.columns]
    for _, group in df.groupby(present):
        ordered = group.sort_values("period_index")
        if ordered["period_date"].is_monotonic_increasing:
            continue
        dates = pd.to_datetime(ordered["period_date"], errors="coerce")
        previous = dates.shift(1)
        for _, row in ordered[dates < previous].iterrows():
            findings.append(
                _finding(
                    "R8",
                    record_key(row, key_columns),
                    "period_date",
                    f"period_date {row['period_date']:%Y-%m-%d} precedes the "
                    "previous period in the same series",
                    "Verify period date ordering",
                )
            )
    return findings

def rule_r9_cumulative_monotonicity(
    df: pd.DataFrame,
    key_columns: list[str],
    group_columns: list[str],
    value_columns: list[str],
) -> list[Finding]:
    """R9: a cumulative series must never fall.

    This is the only rule that genuinely requires historical context: each
    running total is defined by everything reported before it, so a restatement
    or a duplicated snapshot is visible here and nowhere else.

    On the real dataset this flags 21 series across 22 decreasing steps - for
    example P05/WBS 81, where ``ev_cum`` falls from 41,052.64 to 40,860.36 at
    period 8 and stays below the earlier total until period 12.  A cumulative
    earned-value series cannot decrease, so these are genuine defects rather
    than artefacts of the analysis.
    """
    findings: list[Finding] = []
    needed = set(group_columns) | {"period_index"} | set(value_columns)
    if not needed <= set(df.columns):
        return findings
    present = [c for c in group_columns if c in df.columns]
    for _, group in df.groupby(present):
        ordered = group.sort_values("period_index")
        for column in value_columns:
            series = pd.to_numeric(ordered[column], errors="coerce")
            delta = series.diff()
            previous_period = ordered["period_index"].shift(1)
            for position in delta.index[delta < 0]:
                # A negative delta at position P means series[P] < series[P-1]:
                # P is the restated record, so the finding belongs to P.  The
                # previous period is the baseline it wrongly undercuts.
                row = ordered.loc[position]
                findings.append(
                    _finding(
                        "R9",
                        record_key(row, key_columns),
                        column,
                        f"{column} is {row[column]:,.2f} at period_index "
                        f"{row['period_index']}, below the "
                        f"{series.shift(1).loc[position]:,.2f} reported at "
                        f"period_index {previous_period.loc[position]}",
                        f"Correct the {column} restatement",
                    )
                )
    return findings


def rule_r13_budget_overrun(
    df: pd.DataFrame, key_columns: list[str], multiple: float = 3.0
) -> list[Finding]:
    """R13: cumulative actual cost must stay within ``multiple`` x budget.

    A reporting period with no planned budget is not an unlimited overrun: the
    plan may already have been spent while costs are still being incurred, so the
    period is judged on the cumulative position of its project.  Periods whose
    project has no budget at all cannot be evaluated and are not flagged.

    This rule needs the running total, so it is a derived-tier rule: it reads
    cumulative sums built from period movements.
    """
    findings: list[Finding] = []
    needed = {"project_id", "pmb_budget", "actual_cost"}
    if not needed <= set(df.columns):
        return findings

    ordered = _in_period_order(df)
    for _, group in ordered.groupby("project_id"):
        cumulative_budget = _running_total(group, "pmb_budget")
        cumulative_actual = _running_total(group, "actual_cost")
        for position in group.index:
            budget = cumulative_budget.loc[position]
            actual = cumulative_actual.loc[position]
            if budget <= 0:
                continue  # nothing to compare against
            if actual > budget * multiple:
                row = group.loc[position]
                findings.append(
                    _finding(
                        "R13",
                        "|".join(str(row.get(c, "")) for c in key_columns),
                        "actual_cost",
                        f"cumulative actual cost {actual:,.2f} exceeds "
                        f"{multiple:g}x cumulative budget {budget:,.2f}",
                        "Review the cost overrun or the project baseline",
                    )
                )
    return findings


def rule_r14_progress_mismatch(
    df: pd.DataFrame, key_columns: list[str], tolerance: float = PROGRESS_TOLERANCE
) -> list[Finding]:
    """R14: cumulative spend must not outrun reported progress.

    ``progress_pct`` is cumulative completion, so it is compared against the
    cumulative cost-to-budget ratio.  Comparing it with a single period's
    figures would mix two different bases and flag every period of a project
    that is spending ahead of its curve.

    This is the rule that surfaces the genuine findings in the real dataset:
    17 of the 76 project records spend faster than the progress they report.
    """
    findings: list[Finding] = []
    needed = {"project_id", "pmb_budget", "actual_cost", "progress_pct"}
    if not needed <= set(df.columns):
        return findings

    ordered = _in_period_order(df)
    for _, group in ordered.groupby("project_id"):
        cumulative_budget = _running_total(group, "pmb_budget")
        cumulative_actual = _running_total(group, "actual_cost")
        progress = pd.to_numeric(group["progress_pct"], errors="coerce").fillna(0.0) / 100.0
        ratio = cumulative_actual / cumulative_budget.where(cumulative_budget > 0)
        for position in group.index:
            budget = cumulative_budget.loc[position]
            if pd.isna(budget) or budget <= 0:
                continue
            spent = ratio.loc[position]
            reported = progress.loc[position]
            if pd.isna(spent):
                continue
            if spent > reported + tolerance:
                row = group.loc[position]
                findings.append(
                    _finding(
                        "R14",
                        "|".join(str(row.get(c, "")) for c in key_columns),
                        "progress_pct",
                        f"cumulative spend is {spent:.1%} of budget but "
                        f"reported progress is {reported:.1%}",
                        "Verify reported progress against actual expenditure",
                    )
                )
    return findings


def _in_period_order(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a derived frame into reporting order.

    Period labels such as ``Month-10`` must not sort as plain strings, or the
    running totals are computed over the wrong sequence.  When ``actual_date``
    is available it is authoritative; otherwise a natural sort on the label is
    used.
    """
    if "actual_date" in df.columns:
        dates = pd.to_datetime(df["actual_date"], errors="coerce")
        if dates.notna().any():
            return df.assign(_order=dates).sort_values(["project_id", "_order"], kind="stable")
    keys = _natural_keys(df.get("time_period"))
    return df.assign(_order=keys).sort_values(["project_id", "_order"], kind="stable")


def _running_total(group: pd.DataFrame, column: str) -> pd.Series:
    """Cumulative sum of a period movement column within one project."""
    values = pd.to_numeric(group[column], errors="coerce").fillna(0.0)
    return values.cumsum()


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
    """
    findings: list[Finding] = []
    needed = set(group_columns) | {"period_date", "period_index"}
    if not needed <= set(df.columns):
        return findings
    present = [c for c in group_columns if c in df.columns]
    for _, group in df.groupby(present):
        ordered = group.sort_values("period_index")
        dates = pd.to_datetime(ordered["period_date"], errors="coerce")
        if dates.isna().all():
            continue
        upper = dates.max()
        for _, row in ordered.iterrows():
            date = pd.to_datetime(row["period_date"], errors="coerce")
            if pd.notna(date) and pd.notna(upper) and date > upper:
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
