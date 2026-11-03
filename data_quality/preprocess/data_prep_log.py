"""
Data-preparation log (Chapter 3, Sections 3.3.3 - 3.3.4).

Records the transformation from the eight principal source workbooks to the two
analytical views:

  * number of source cost records read from each workbook
  * number of rows rejected by parsing
  * number of leaf-level records retained
  * number of parent-level records excluded from aggregation
  * number of rows written to each analytical view

This log is the evidence for the row counts in Table 3.3 and is regenerated
whenever the pipeline runs, supporting the reproducibility claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass
class WorkbookRecord:
    """Per-workbook transformation evidence."""

    source_file: str
    source_records_read: int
    rows_rejected_by_parsing: int
    leaf_level_records: int
    parent_level_records: int
    parent_level_excluded: int
    rows_written_to_wbs_view: int


@dataclass
class DataPrepLog:
    """Complete data-preparation evidence for all eight workbooks."""

    workbooks: list[WorkbookRecord] = field(default_factory=list)
    total_source_records: int = 0
    total_rejected: int = 0
    total_leaf_level: int = 0
    total_parent_excluded: int = 0
    wbs_level_rows: int = 0
    project_period_rows: int = 0
    leaf_level_projects: int = 0
    leaf_level_periods: int = 0


def classify_leaf_level(df: pd.DataFrame):
    """Classify records as leaf-level or parent-level using the WBS hierarchy."""
    if df.empty:
        return df.copy(), df.copy(), 0

    work = df.copy()
    work["wbs_code"] = work["wbs_code"].astype(str)

    def is_parent(code: str, all_codes: set) -> bool:
        for other in all_codes:
            if other != code and other.startswith(code) and len(other) > len(code):
                return True
        return False

    leaf_frames = []
    parent_frames = []
    parent_excluded = 0

    for project_id, group in work.groupby("project_id"):
        all_codes = set(group["wbs_code"].astype(str))
        group = group.copy()
        group["_is_parent"] = group["wbs_code"].apply(lambda c: is_parent(str(c), all_codes))

        money_cols = [c for c in ("pv_cum", "ac_cum", "ev_cum") if c in group.columns]
        has_money = group[money_cols].notna().any(axis=1) if money_cols else pd.Series(False, index=group.index)

        leaf_mask = (~group["_is_parent"]) & has_money
        leaf_frames.append(group[leaf_mask].drop(columns="_is_parent"))

        parent_mask = group["_is_parent"] | (~has_money)
        parent_excluded += int(parent_mask.sum())
        parent_frames.append(group[parent_mask].drop(columns="_is_parent"))

    leaf_df = pd.concat(leaf_frames, ignore_index=True) if leaf_frames else work.iloc[0:0].copy()
    parent_df = pd.concat(parent_frames, ignore_index=True) if parent_frames else work.iloc[0:0].copy()
    return leaf_df, parent_df, parent_excluded


def aggregate_project_period(leaf_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate leaf-level WBS records into the project-period view."""
    money_cols = [c for c in ("pv_cum", "ac_cum", "ev_cum") if c in leaf_df.columns]
    agg = {"pv_cum": "sum", "ac_cum": "sum", "ev_cum": "sum"}
    if "progress_pct" in leaf_df.columns:
        agg["progress_pct"] = "max"

    group_cols = [c for c in ("project_id", "period_date", "period_index") if c in leaf_df.columns]
    result = leaf_df.groupby(group_cols, as_index=False).agg(agg)

    for attr in ("project_name", "baseline_start_date"):
        if attr in leaf_df.columns:
            first_attr = leaf_df.groupby("project_id")[attr].first().reset_index()
            result = result.merge(first_attr, on="project_id", how="left")

    return result


def build_log(per_workbook: list):
    """Build a DataPrepLog from per-workbook transformation records."""
    log = DataPrepLog()
    for rec in per_workbook:
        wb = WorkbookRecord(
            source_file=rec["source_file"],
            source_records_read=rec["source_records_read"],
            rows_rejected_by_parsing=rec.get("rows_rejected_by_parsing", 0),
            leaf_level_records=rec["leaf_level_records"],
            parent_level_records=rec.get("parent_level_records", 0),
            parent_level_excluded=rec.get("parent_level_excluded", 0),
            rows_written_to_wbs_view=rec["rows_written_to_wbs_view"],
        )
        log.workbooks.append(wb)
        log.total_source_records += wb.source_records_read
        log.total_rejected += wb.rows_rejected_by_parsing
        log.total_leaf_level += wb.leaf_level_records
        log.total_parent_excluded += wb.parent_level_excluded
        log.wbs_level_rows += wb.rows_written_to_wbs_view
    return log


def log_to_markdown(log: DataPrepLog) -> str:
    """Render the log as a Markdown table suitable for Appendix B."""
    lines = [
        "# Data-Preparation Log (Appendix B)",
        "",
        "## Per-workbook transformation evidence",
        "",
        "| Source workbook | Records read | Rejected by parsing | Leaf-level | Parent-level | Parent excluded | WBS-view rows |",
        "|---|---|---|---|---|---|---|",
    ]
    for wb in log.workbooks:
        lines.append(
            f"| {wb.source_file} | {wb.source_records_read} | {wb.rows_rejected_by_parsing} | "
            f"{wb.leaf_level_records} | {wb.parent_level_records} | {wb.parent_level_excluded} | "
            f"{wb.rows_written_to_wbs_view} |"
        )
    lines += [
        "",
        "## Aggregation totals",
        "",
        f"- Total source cost records read: **{log.total_source_records}**",
        f"- Total rows rejected by parsing: **{log.total_rejected}**",
        f"- Total leaf-level records retained: **{log.total_leaf_level}**",
        f"- Total parent-level records excluded: **{log.total_parent_excluded}**",
        f"- WBS-level view rows: **{log.wbs_level_rows}**",
        f"- Project-period view rows: **{log.project_period_rows}**",
        "",
        "## Aggregation assumption",
        "",
        "WBS-level records represent mutually exclusive cost components.  Only "
        "leaf-level records are summed into the project-period view; parent-level "
        "rows are excluded to prevent double-counting (Section 3.3.4).",
    ]
    return "\n".join(lines)
