"""
Data profiling for the real Kaggle Project Portfolio cost records.

The research results chapter needs a *data profiling* table: how many records
are affected by each category of data quality defect, what share of the dataset
that is, and which project suffers most.  This module measures that table
instead of asserting it, so the figures can be read straight into the write-up.

Two profiling views are produced, and they answer different questions:

* :func:`profile_frame` describes the *structure* of the data as it arrived -
  per column type, null count, range, distinct count and any format conflicts.
  This is the data-cleaning evidence.
* :func:`anomaly_category_table` reconciles the *validation engine's* findings
  into the five anomaly categories the research uses (missing fields, duplicate
  records, format conflicts, out-of-bounds values, logical anomalies) and
  attributes each to the project that suffers most.

Nothing here is hard-coded: every number is computed from the frame passed in,
so the tables stay correct for whatever data the pipeline actually produced.

Usage::

    python profiling.py
    python profiling.py --cleaned data/kaggle_cleaned_data.csv
"""

import argparse
import os

import pandas as pd

from dqd.legacy.contract import get_contract_specification

# Real, cleaned dataset produced by dqd/preprocess/clean.py
DEFAULT_CLEANED = os.path.join("data", "kaggle_cleaned_data.csv")

# Where the profiling tables are written for the write-up
DEFAULT_REPORT = os.path.join("results", "data_profiling.md")

# The anomaly categories used throughout the research, in report order.  The
# names match the validation engine's own categories, so the table and the
# engine can never drift apart.
ANOMALY_CATEGORY_ORDER = [
    "missing_values",
    "duplicates",
    "format_conflicts",
    "bounds_violations",
    "logical_anomalies",
]

# Human-readable labels for the categories above
CATEGORY_LABELS = {
    "missing_values": "Missing required fields",
    "duplicates": "Duplicate records",
    "format_conflicts": "Format conflicts",
    "bounds_violations": "Out-of-bounds numerical values",
    "logical_anomalies": "Logical anomalies",
}

# The contract's declared numeric fields, used to spot format conflicts
CONTRACT_NUMERIC_FIELDS = [
    "pmb_budget",
    "actual_cost",
    "progress_pct",
    "revenue_claimed",
]

# The contract's declared date fields
CONTRACT_DATE_FIELDS = ["actual_date", "baseline_start_date"]


def load_cleaned_data(path=DEFAULT_CLEANED):
    """
    Load the real cleaned dataset with its date columns parsed.

    Args:
        path: Path to the cleaned CSV.

    Returns:
        pd.DataFrame | None: The dataset, or None when it cannot be loaded.
    """
    if not os.path.exists(path):
        print(f"ERROR: {path} not found - run download_kaggle_data.py and "
              f"clean_kaggle_data.py first.")
        return None
    try:
        return pd.read_csv(path, parse_dates=["actual_date", "baseline_start_date"])
    except Exception as exc:
        print(f"ERROR: could not read {path}: {exc}")
        return None


def project_column(df):
    """
    Return the per-record project identifier, defaulting to positional labels.

    Used to attribute an anomaly to the project that suffers most.

    Args:
        df: The frame to inspect.

    Returns:
        pd.Series: Project identifier aligned to ``df``'s index.
    """
    if "project_id" in df.columns:
        return df["project_id"].astype(str)
    return pd.Series([f"row-{index}" for index in df.index], index=df.index)



def profile_frame(df):
    """
    Build a per-column structural profile of a cost-record frame.

    For every contract column this records the dtype pandas actually holds, the
    number and share of missing values, the distinct count, the value range and
    whether the stored dtype conflicts with the declared contract type.  The
    "format conflicts" column is the important one for the cleaning chapter: it
    counts the cells a spreadsheet would have to coerce on import.

    Args:
        df: The frame to profile.

    Returns:
        pd.DataFrame: One row per contract column, indexed by column name.
    """
    required = get_contract_specification()["required_fields"]
    rows = {}
    total = max(len(df), 1)

    for column in required:
        if column not in df.columns:
            rows[column] = {
                "dtype": "ABSENT",
                "non_null": 0,
                "missing": len(df),
                "missing_pct": 100.0 if len(df) else 0.0,
                "distinct": 0,
                "min": None,
                "max": None,
                "format_conflicts": len(df),
            }
            continue

        series = df[column]
        non_null = int(series.notna().sum())
        missing = int(series.isna().sum())

        if column in CONTRACT_NUMERIC_FIELDS:
            # A cell is a format conflict when it holds a value that is not
            # numeric at all - exactly what a text value in a money column
            # looks like after a dirty import.
            numeric = pd.to_numeric(series, errors="coerce")
            conflicts = int((series.notna() & numeric.isna()).sum())
            low, high = numeric.min(), numeric.max()
        elif column in CONTRACT_DATE_FIELDS:
            parsed = pd.to_datetime(series, errors="coerce")
            conflicts = int((series.notna() & parsed.isna()).sum())
            low, high = parsed.min(), parsed.max()
        else:
            conflicts = 0
            low, high = series.min(), series.max()

        rows[column] = {
            "dtype": str(series.dtype),
            "non_null": non_null,
            "missing": missing,
            "missing_pct": round(missing / total * 100.0, 2),
            "distinct": int(series.nunique(dropna=True)),
            "min": low,
            "max": high,
            "format_conflicts": conflicts,
        }

    return pd.DataFrame.from_dict(rows, orient="index")


def format_conflict_counts(df):
    """
    Count the cells that hold a non-numeric value in a numeric field.

    Args:
        df: The frame to inspect.

    Returns:
        pd.Series: ``(row_index, field)`` pairs for each offending cell.
    """
    pairs = []
    for column in CONTRACT_NUMERIC_FIELDS:
        if column not in df.columns:
            continue
        raw = df[column]
        numeric = pd.to_numeric(raw, errors="coerce")
        mask = raw.notna() & numeric.isna()
        for index in df.index[mask]:
            pairs.append((index, column))
    return pd.Series(pairs, dtype=object)


def duplicate_key_counts(df):
    """
    Count records participating in a duplicated project/period key.

    The data contract's composite key is ``project_id`` + ``time_period``.  A
    duplicated key is an inconsistency because the same reporting period cannot
    legitimately hold two different cost records for one project.

    Args:
        df: The frame to inspect.

    Returns:
        tuple: ``(duplicated_rows, duplicate_groups, key_columns)``.
    """
    key_columns = ["project_id", "time_period"]
    if not all(column in df.columns for column in key_columns):
        return 0, 0, key_columns

    duplicated = df.duplicated(subset=key_columns, keep=False)
    return int(duplicated.sum()), int(df.duplicated(subset=key_columns).sum()), key_columns


def anomaly_category_table(df, validation_results):
    """
    Reconcile validation findings into the research's anomaly categories.

    The validation engine reports findings under its own category names.  Format
    conflicts are not one of them - they are a *type* property of the stored data
    - so they are measured directly from the frame.  Every other category is
    counted from the engine's findings, which carry the offending row index, so
    the most-affected project is derived rather than guessed.

    Args:
        df: The frame that was validated.
        validation_results: Output of ``ValidationEngine.validate_batch``.

    Returns:
        pd.DataFrame: Columns ``category``, ``label``, ``records_affected``,
        ``pct_of_total``, ``most_affected_project``, ``projects_affected``.
    """
    total = len(df)
    project = project_column(df)
    anomalies = (validation_results or {}).get("anomalies", {}) or {}

    counts = {}
    projects = {}

    # Format conflicts are a property of the stored data, not of the engine's
    # findings, so they are measured rather than read off the anomaly output.
    conflicts = format_conflict_counts(df)
    counts["format_conflicts"] = int(conflicts.size)
    if conflicts.size:
        rows = pd.Index([pair[0] for pair in conflicts])
        projects["format_conflicts"] = (
            project.reindex(rows).dropna().astype(str).value_counts().to_dict()
        )
    else:
        projects["format_conflicts"] = {}

    for category in ("missing_values", "duplicates", "bounds_violations",
                     "logical_anomalies"):
        entries = anomalies.get(category, []) or []
        rows = {entry.get("row_index") for entry in entries}
        rows.discard(None)
        counts[category] = len(rows)
        hit = project.reindex(sorted(rows)).dropna().astype(str)
        projects[category] = hit.value_counts().to_dict()

    rows = []
    for category in ANOMALY_CATEGORY_ORDER:
        by_project = projects.get(category, {}) or {}
        if by_project:
            # Ties are broken on the project name so the table is deterministic.
            most_affected = max(by_project.items(), key=lambda item: (item[1], item[0]))[0]
            projects_affected = len(by_project)
        else:
            most_affected = "-"
            projects_affected = 0
        rows.append({
            "category": category,
            "label": CATEGORY_LABELS[category],
            "records_affected": counts.get(category, 0),
            "pct_of_total": round(counts.get(category, 0) / total * 100.0, 2) if total else 0.0,
            "most_affected_project": most_affected,
            "projects_affected": projects_affected,
        })

    return pd.DataFrame(rows)


def project_summary(df):
    """
    Per-project cost summary, ordered by project identifier.

    Args:
        df: The cleaned cost records.

    Returns:
        pd.DataFrame: One row per project with periods, dates and cost totals.
    """
    if df.empty or "project_id" not in df.columns:
        return pd.DataFrame()

    grouped = df.groupby("project_id", as_index=False).agg(
        periods=("time_period", "size"),
        first_reporting=("actual_date", "min"),
        last_reporting=("actual_date", "max"),
        total_pmb_budget=("pmb_budget", "sum"),
        total_actual_cost=("actual_cost", "sum"),
        total_revenue_claimed=("revenue_claimed", "sum"),
        final_progress_pct=("progress_pct", "last"),
    )
    for column in ("total_pmb_budget", "total_actual_cost", "total_revenue_claimed"):
        grouped[column] = grouped[column].round(2)
    grouped["final_progress_pct"] = grouped["final_progress_pct"].round(2)
    grouped["cost_variance"] = (
        grouped["total_revenue_claimed"] - grouped["total_actual_cost"]
    ).round(2)
    return grouped


def summary_statistics_table(df, columns=None):
    """
    Descriptive statistics for the numeric cost columns.

    Args:
        df: The cleaned cost records.
        columns: Columns to summarise. Defaults to the money and progress fields.

    Returns:
        pd.DataFrame: One row per column with count, mean, median, mode, std,
        min, max, skew and the share of zero-valued cells.
    """
    if columns is None:
        columns = CONTRACT_NUMERIC_FIELDS

    rows = {}
    total = max(len(df), 1)
    for column in columns:
        if column not in df.columns:
            continue
        series = pd.to_numeric(df[column], errors="coerce")
        modes = series.mode(dropna=True)
        present = bool(series.notna().any())
        rows[column] = {
            "count": int(series.notna().sum()),
            "mean": round(float(series.mean()), 2) if present else None,
            "median": round(float(series.median()), 2) if present else None,
            "mode": round(float(modes.iloc[0]), 2) if not modes.empty else None,
            "std": round(float(series.std()), 2) if present else None,
            "min": round(float(series.min()), 2) if present else None,
            "max": round(float(series.max()), 2) if present else None,
            "skew": round(float(series.skew()), 3) if series.notna().sum() > 2 else None,
            "zero_pct": round(float((series == 0).sum()) / total * 100.0, 2),
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def to_markdown(frame, floatfmt=2):
    """
    Render a DataFrame as a GitHub-flavoured markdown table.

    Kept local so the reports have no dependency beyond pandas.

    Args:
        frame: The table to render.
        floatfmt: Decimal places for float columns.

    Returns:
        str: The markdown table, including a header row and separator.
    """
    if frame is None or len(frame) == 0:
        return "_no rows_"

    def render(value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "-"
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, float):
            return f"{value:,.{floatfmt}f}"
        return str(value)

    columns = list(frame.columns)
    header = "| " + " | ".join(str(column) for column in columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join(render(value) for value in row) + " |"
        for row in frame.itertuples(index=False)
    ]
    return "\n".join([header, separator] + body)


def build_report(df, validation_results, source=DEFAULT_CLEANED):
    """
    Build the full profiling report from the real data.

    Args:
        df: The cleaned cost records.
        validation_results: Output of ``ValidationEngine.validate_batch``.
        source: Path the data was read from, recorded in the report header.

    Returns:
        str: The markdown report text.
    """
    fields = get_contract_specification()["required_fields"]
    profile = profile_frame(df)
    categories = anomaly_category_table(df, validation_results)
    projects = project_summary(df)
    stats = summary_statistics_table(df)
    duplicated_rows, duplicate_groups, key_columns = duplicate_key_counts(df)

    total_cells = len(df) * len(fields)
    total_missing = int(profile["missing"].sum())
    total_conflicts = int(profile["format_conflicts"].sum())
    flagged = int(categories["records_affected"].sum())

    lines = [
        "# Data Profiling Results",
        "",
        "Generated by `profiling.py` from the real Kaggle Project Portfolio data. "
        "Every figure below is measured from the data actually present; no value "
        "in this report is hand-entered.",
        "",
        f"- Source: `{source}`",
        f"- Records: {len(df)} across {df['project_id'].nunique()} project(s)",
        f"- Reporting periods: {df['time_period'].nunique()}",
        f"- Cells profiled: {total_cells} ({len(df)} records x {len(fields)} contract fields)",
        "",
        "## Table 1: Column-level profile",
        "",
        to_markdown(profile.reset_index().rename(columns={"index": "field"})),
        "",
        "## Table 2: Anomaly categories",
        "",
        to_markdown(categories.drop(columns=["category"])),
        "",
        f"Total records carrying at least one category-level finding: {flagged} "
        f"({round(flagged / len(df) * 100.0, 2) if len(df) else 0.0}% of the dataset).",
        "",
        "## Table 3: Project summary",
        "",
        to_markdown(projects),
        "",
        "## Table 4: Summary statistics",
        "",
        to_markdown(stats.reset_index().rename(columns={"index": "field"})),
        "",
        "## Duplicate keys",
        "",
        f"- Composite key: `{' + '.join(key_columns)}`",
        f"- Records participating in a duplicated key: {duplicated_rows}",
        f"- Redundant records (the repeats beyond the first): {duplicate_groups}",
        "",
        "## Structural totals",
        "",
        f"- Missing required values: {total_missing} of {total_cells} cells "
        f"({round(total_missing / total_cells * 100.0, 2) if total_cells else 0.0}%)",
        f"- Format conflicts (non-numeric value in a numeric field): {total_conflicts}",
        f"- Records with a duplicated composite key: {duplicated_rows}",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_report(df, validation_results, path=DEFAULT_REPORT, source=DEFAULT_CLEANED):
    """
    Write the profiling report to disk.

    Args:
        df: The cleaned cost records, or None to load them from ``source``.
        validation_results: Output of ``ValidationEngine.validate_batch``.
        path: Destination markdown file.
        source: Path the data was read from.

    Returns:
        str | None: The report text, or None when the data was unavailable.
    """
    if df is None:
        df = load_cleaned_data(source)
    if df is None:
        return None

    report = build_report(df, validation_results, source=source)
    if path:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(report)
        print(f"Wrote {path}")
    return report


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Profile the real cleaned Kaggle project cost records."
    )
    parser.add_argument("--cleaned", default=DEFAULT_CLEANED,
                        help="Cleaned Kaggle dataset to profile")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="Where to write the profiling report ('' to skip)")
    args = parser.parse_args()

    df = load_cleaned_data(args.cleaned)
    if df is None:
        return 1

    from dqd.legacy.engine import ValidationEngine

    results = ValidationEngine().validate_batch(df)
    write_report(df, results, path=args.report or None, source=args.cleaned)

    print("\nColumn profile:")
    print(profile_frame(df).to_string())
    print("\nAnomaly categories:")
    print(anomaly_category_table(df, results).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
