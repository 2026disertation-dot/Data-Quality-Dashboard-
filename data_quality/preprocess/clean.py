"""
Clean and transform the Kaggle Project Portfolio Dataset into the dashboard's
data contract.

Input is the long-format EVM time-phase produced by ``download_kaggle_data.py``:
one row per project x reporting month x Portfolio WBS line, carrying the
*cumulative* planned value (PV), actual cost (AC) and earned value (EV).

The dashboard's contract is time-phased - one record per project and reporting
period - so this module performs the business transformation in four steps:

1. **Aggregate** the leaf-level Portfolio WBS lines up to the project level,
   summing the cumulative EVM figures for each reporting month (parent-level
   rows are filtered out first so they are not double-counted).
2. **Store** the aggregated PV / AC / EV directly as the cumulative contract
   fields ``pmb_budget``, ``actual_cost`` and ``revenue_claimed``.  Validation
   consumes cumulative values so that R9 checks cumulative monotonicity on the
   project-period view; period movements are derived on the fly by the
   dashboard for display only.
3. **Derive** the remaining contract fields:
   ``time_period`` (``Month-<n>``, mirroring the ``Week-<n>`` convention used by
   the sample generator), ``progress_pct`` (cumulative earned value as a
   percentage of the performance measurement baseline, clipped to 0-100) and
   ``baseline_start_date`` (the project's first reporting month).
4. **Enforce** the contract's constraints (non-negative money, 0-100 progress,
   no missing keys, ``actual_date`` not before ``baseline_start_date``) and
   validate the result with :func:`data_contract.validate_data_contract`.

Every figure in the output is derived from the source workbooks.  Nothing is
simulated: the previous version of this script filled unparsable projects with
``numpy.random`` data, which made the dashboard output meaningless.

Usage::

    python -m data_quality.preprocess.clean
    python -m data_quality.preprocess.clean --source data/kaggle_original_data.csv \\
                                --output data/kaggle_cleaned_data.csv
"""

import argparse
import os
from dataclasses import dataclass, field

import pandas as pd

from data_quality.legacy.contract import validate_data_contract

# Default input: the cumulative EVM data written by download_kaggle_data.py
DEFAULT_SOURCE = os.path.join("data", "kaggle_original_data.csv")

# Default output: dashboard-ready, contract compliant data
DEFAULT_OUTPUT = os.path.join("data", "kaggle_cleaned_data.csv")

# Column order required by the data contract (see data_quality/legacy/contract.py)
CONTRACT_COLUMNS = [
    "project_id",
    "time_period",
    "pmb_budget",
    "actual_cost",
    "progress_pct",
    "revenue_claimed",
    "actual_date",
    "baseline_start_date",
]

# Source columns the transform relies on
REQUIRED_SOURCE_COLUMNS = {"project_id", "period_date", "pv_cum", "ac_cum", "ev_cum"}

# Prefix used to build the time_period identifier
TIME_PERIOD_PREFIX = "Month-"

# Decimal places kept for money and percentage columns
ROUND_TO = 2


@dataclass
class CleaningReport:
    """Summary of everything the cleaning step changed or had to repair."""

    source_records: int = 0
    records: int = 0
    projects: int = 0
    periods: int = 0
    wbs_lines: int = 0
    dropped_rows: int = 0
    negative_diffs: int = 0
    progress_clipped: int = 0
    baselines: dict = field(default_factory=dict)

    def describe(self) -> str:
        """Render the report as a readable multi-line summary."""
        lines = [
            f"Source EVM records : {self.source_records}",
            f"WBS lines         : {self.wbs_lines}",
            f"Projects          : {self.projects}",
            f"Reporting periods : {self.periods}",
            f"Output records    : {self.records}",
            f"Rows dropped      : {self.dropped_rows} (missing project or period date)",
            f"Negative diffs    : {self.negative_diffs} (cumulative series went backwards)",
            f"Progress clipped  : {self.progress_clipped} (earned value outside 0-100%)",
            "Baseline budgets  :",
        ]
        for project_id in sorted(self.baselines):
            lines.append(f"    {project_id}: {self.baselines[project_id]:>15,.2f}")
        return "\n".join(lines)


def de_cumulativise(values, confirmed_revision: bool = False):
    """
    Convert a cumulative series into period movements.

    This helper is used for dashboard display only.  The validation pipeline
    always consumes the stored cumulative values, so that R9 checks cumulative
    monotonicity (Chapter 4, Challenge 6).

    Negative movements are retained for display unless the decrease has been
    explicitly confirmed as a historical revision, in which case the movement is
    floored at zero.

    Args:
        values: Cumulative values ordered from the first reporting period.
        confirmed_revision: If True, negative movements are floored at zero.

    Returns:
        tuple: (period_values, negative_count) where period_values is a
        float Series of period movements and negative_count counts the
        movements that were negative before clipping.
    """
    cumulative = pd.to_numeric(values, errors="coerce").astype(float)
    cumulative = cumulative.reset_index(drop=True)
    # A blank in a cumulative series means "unchanged since the last known
    # value", not "reset to zero", so carry the last value forward.
    cumulative = cumulative.ffill().fillna(0.0)

    periods = cumulative.diff()
    if len(periods):
        periods.iloc[0] = cumulative.iloc[0]

    negative_count = int((periods < 0).sum())

    # Only floor if explicitly confirmed as a historical revision
    if confirmed_revision:
        periods = periods.clip(lower=0.0)

    return periods, negative_count


def build_project_totals(long_df):
    """
    Collapse the leaf-level WBS EVM time-phase to one cumulative row per
    project and period.

    Leaf-level filtering ensures parent-level rows (which already aggregate
    their children) are excluded, preventing double-counting (Section 3.3.4
    of Chapter 3).

    Args:
        long_df: Long-format frame as produced by ``download_kaggle_data.py``.

    Returns:
        pd.DataFrame: Columns ``project_id``, ``period_date``, ``pv_cum``,
        ``ac_cum``, ``ev_cum`` - one cumulative row per project and period.

    Raises:
        ValueError: If a required source column is missing.
    """
    missing = REQUIRED_SOURCE_COLUMNS - set(long_df.columns)
    if missing:
        raise ValueError(
            "source data is missing required column(s): " + ", ".join(sorted(missing))
        )

    work = long_df.copy()
    work["project_id"] = work["project_id"].astype(str).str.strip()
    work["period_date"] = pd.to_datetime(work["period_date"], errors="coerce")

    # --- Leaf-level filter (Section 3.3.4) ---
    # A leaf-level record has no subordinate WBS code.  Where a WBS code is a
    # strict prefix of another code in the same project (for example "1" above
    # "1.2"), the shorter code is a parent that already aggregates its children,
    # so summing both would double-count.  Parent-level rows are excluded.
    if "wbs_code" in work.columns:
        codes = work["wbs_code"].astype(str)
        has_children = codes.groupby(work["project_id"]).transform(
            lambda series: series.apply(
                lambda code: any(
                    other != code and other.startswith(code + ".")
                    for other in series
                )
            )
        )
        work = work[~has_children]

    # Parent-level rows can also arrive with empty cumulative values; a record
    # without a cumulative figure cannot contribute to a project total.
    work = work.dropna(subset=["pv_cum", "ac_cum", "ev_cum"])

    for column in ("pv_cum", "ac_cum", "ev_cum"):
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)

    # A record without a project or a reporting month cannot be placed on the
    # time axis, so it cannot become a time-phased contract record either.
    work = work[work["project_id"].ne("") & work["period_date"].notna()]

    # Sum LEAF-LEVEL cumulative values only.
    totals = (
        work.groupby(["project_id", "period_date"], as_index=False)[["pv_cum", "ac_cum", "ev_cum"]]
        .sum()
        .sort_values(["project_id", "period_date"])
        .reset_index(drop=True)
    )
    totals.attrs["leaf_records"] = len(work)
    totals.attrs["wbs_lines"] = int(work["wbs_code"].nunique()) if "wbs_code" in work.columns else 0
    totals.attrs["dropped_rows"] = len(long_df) - len(work)
    return totals


def transform_to_contract(long_df, time_period_prefix=TIME_PERIOD_PREFIX, round_to=ROUND_TO):
    """
    Transform leaf-level cumulative EVM data into the derived data contract.

    The derived contract stores CUMULATIVE values so that Rule R9 (cumulative
    monotonicity) can be applied on the project-period view, consistent with
    Chapter 4 Code Block 4.1 and Challenge 6.  Period movements are computed
    separately by the dashboard for visualisation when needed.

    Args:
        long_df: Long-format frame as produced by ``download_kaggle_data.py``.
        time_period_prefix: Prefix for the generated period identifiers.
        round_to: Decimal places for money and percentage columns.

    Returns:
        tuple: ``(cleaned_df, report)`` where ``cleaned_df`` contains exactly
        the contract columns in contract order.

    Raises:
        ValueError: If the source frame is empty or lacks required columns.
    """
    report = CleaningReport(source_records=len(long_df))
    if long_df.empty:
        raise ValueError("source data is empty - run download_kaggle_data.py first")

    totals = build_project_totals(long_df)
    report.dropped_rows = totals.attrs.get("dropped_rows", 0)
    report.wbs_lines = totals.attrs.get("wbs_lines", 0)
    if totals.empty:
        raise ValueError("no usable project/period combinations in the source data")

    frames = []
    for project_id, group in totals.groupby("project_id", sort=True):
        group = group.sort_values("period_date").reset_index(drop=True)
        # Rank months by date so time_period follows the calendar even when a
        # workbook lists its reporting months out of order.
        period_index = pd.Series(range(1, len(group) + 1), index=group.index)

        pmb_budget = (
            pd.to_numeric(group["pv_cum"], errors="coerce").fillna(0.0).clip(lower=0.0)
        )
        actual_cost = (
            pd.to_numeric(group["ac_cum"], errors="coerce").fillna(0.0).clip(lower=0.0)
        )
        revenue_claimed = (
            pd.to_numeric(group["ev_cum"], errors="coerce").fillna(0.0).clip(lower=0.0)
        )

        # The performance measurement baseline is the highest planned value the
        # project reaches, i.e. its planned value at completion.
        baseline = float(pmb_budget.max())
        report.baselines[project_id] = round(baseline, round_to)

        if baseline > 0:
            progress_raw = revenue_claimed.to_numpy(dtype=float) / baseline * 100.0
        else:
            progress_raw = revenue_claimed.to_numpy(dtype=float) * 0.0
        report.progress_clipped += int(((progress_raw < 0) | (progress_raw > 100)).sum())

        frames.append(
            pd.DataFrame(
                {
                    "project_id": project_id,
                    "time_period": [f"{time_period_prefix}{n}" for n in period_index],
                    "pmb_budget": pmb_budget.to_numpy(dtype=float),
                    "actual_cost": actual_cost.to_numpy(dtype=float),
                    "progress_pct": progress_raw,
                    "revenue_claimed": revenue_claimed.to_numpy(dtype=float),
                    "actual_date": group["period_date"].to_numpy(),
                    "baseline_start_date": group["period_date"].iloc[0],
                }
            )
        )

    cleaned = pd.concat(frames, ignore_index=True)
    cleaned = cleaned.sort_values(["project_id", "time_period"]).reset_index(drop=True)

    # Enforce the contract's bounds.
    for column in ("pmb_budget", "actual_cost", "revenue_claimed"):
        cleaned[column] = cleaned[column].clip(lower=0.0)
    cleaned["progress_pct"] = cleaned["progress_pct"].clip(0.0, 100.0)

    for column in ("pmb_budget", "actual_cost", "progress_pct", "revenue_claimed"):
        cleaned[column] = cleaned[column].round(round_to)

    cleaned["actual_date"] = pd.to_datetime(cleaned["actual_date"])
    cleaned["baseline_start_date"] = pd.to_datetime(cleaned["baseline_start_date"])

    # Guard the contract's logical constraint explicitly.
    before = len(cleaned)
    cleaned = cleaned[cleaned["actual_date"] >= cleaned["baseline_start_date"]]
    report.dropped_rows += before - len(cleaned)

    cleaned = cleaned[CONTRACT_COLUMNS]
    report.records = len(cleaned)
    report.projects = int(cleaned["project_id"].nunique())
    report.periods = int(cleaned["time_period"].nunique())
    return cleaned, report


def load_source(path=DEFAULT_SOURCE):
    """
    Load the cumulative EVM source data.

    When the file is missing this triggers ``download_kaggle_data.py`` so the
    two steps can be run independently or as a chain.

    Args:
        path: CSV path holding the long-format EVM data.

    Returns:
        pd.DataFrame | None: The source frame, or None when unavailable.
    """
    if not os.path.exists(path):
        print(f"Source file {path} not found - downloading and extracting first...")
        try:
            from data_quality.preprocess.download import download_and_format_dataset
        except ImportError:
            print("ERROR: download_kaggle_data.py is not importable from this directory.")
            return None
        if download_and_format_dataset(output=path) is None:
            return None

    try:
        return pd.read_csv(path)
    except Exception as exc:
        print(f"ERROR: could not read {path}: {exc}")
        return None


def clean_and_transform_kaggle_data(source=DEFAULT_SOURCE, output=DEFAULT_OUTPUT):
    """
    Load the Kaggle EVM source data, clean it and write the contract-ready CSV.

    Args:
        source: Path to the long-format EVM CSV.
        output: Destination CSV path. Pass None to skip writing.

    Returns:
        pd.DataFrame | None: The cleaned frame, or None when the data could not
        be produced.
    """
    long_df = load_source(source)
    if long_df is None:
        return None

    try:
        cleaned, report = transform_to_contract(long_df)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return None

    is_valid, _, errors = validate_data_contract(cleaned)
    if not is_valid:
        print("ERROR: the cleaned data does not satisfy the data contract:")
        for error in errors:
            print(f"  - {error}")
        return None

    print("\nCleaning report")
    print("-" * 46)
    print(report.describe())
    print("-" * 46)
    print("Data contract validation: PASSED")
    
    # Log aggregation details per Section 3.3.4
    print("\nAggregation Log (Section 3.3.4):")
    print("=" * 60)
    print(f"Source WBS-level records: {report.source_records}")
    print(f"Leaf-level records retained: {report.source_records - report.dropped_rows}")
    print(f"Parent-level records excluded: {report.dropped_rows}")
    print(f"Project-period view rows: {report.records}")
    print("=" * 60)

    if output:
        output_dir = os.path.dirname(output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        cleaned.to_csv(output, index=False)
        print(f"\nSaved dashboard-ready data to {output}")
        print("Next: streamlit run app.py  (and upload the file above)")

    return cleaned


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Clean the Kaggle Project Portfolio EVM data into the dashboard data contract."
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="Long-format EVM CSV to read")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Cleaned CSV to write ('' to skip)")
    args = parser.parse_args()

    cleaned = clean_and_transform_kaggle_data(source=args.source, output=args.output or None)
    if cleaned is None:
        return 1

    print("\nPreview:")
    print(cleaned.head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
