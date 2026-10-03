"""
Test fixtures built from the real Kaggle Project Portfolio data.

The dashboard's evidence base is the cleaned Project Portfolio Dataset
(``data/kaggle_cleaned_data.csv``), so the system tests are driven from that
real data rather than from synthetic records. This module derives the test
material the research evaluation calls for:

* a **batch/incremental split** of the real records, so dual-mode behaviour and
  regression consistency can be measured on genuine cost data. The split is
  chronological: the newest reporting period of every project is held back as
  the *incremental* arrival, and everything before it is the *batch* history;
* an **anomaly test set** built by injecting a controlled, labelled set of data
  defects into otherwise real records, together with the ground truth needed to
  measure detection completeness and false positives. Ground truth is required
  because real records are clean by construction, so the defects cannot come
  from the source dataset itself;
* **measurement helpers** that score the validation engine's output against
  that ground truth.

No values are invented: the records are the real ones, and only the labelled
defects are synthetic, which keeps them clearly attributable in the results.

Usage::

    python data_fixtures.py
    python data_fixtures.py --cleaned data/kaggle_cleaned_data.csv
"""

import argparse
import os

import numpy as np
import pandas as pd

from dqd.legacy.contract import get_contract_specification

# Real, cleaned dataset produced by dqd/preprocess/clean.py
DEFAULT_CLEANED = os.path.join("data", "kaggle_cleaned_data.csv")

# Derived fixtures
DEFAULT_BATCH = os.path.join("data", "kaggle_batch_data.csv")
DEFAULT_INCREMENTAL = os.path.join("data", "kaggle_incremental_data.csv")
DEFAULT_ANOMALY_SET = os.path.join("data", "kaggle_anomaly_test_set.csv")
DEFAULT_GROUND_TRUTH = os.path.join("data", "kaggle_anomaly_ground_truth.csv")

# Number of trailing reporting periods per project held back as incremental
DEFAULT_HOLDOUT = 1

# Random seed for the (deterministic) defect placement
DEFAULT_SEED = 42

# Text sentinel injected into numeric fields to create a genuine type error.
# It must not be one of pandas' default NA tokens, otherwise it would be read
# back as a null and reported as a missing value instead of a type error.
TYPE_ERROR_SENTINEL = "not_a_number"

# Catalogue of injectable defects. Each entry maps a defect name to the
# validation-engine category, field and anomaly type that should detect it.
ANOMALY_CATALOGUE = {
    "missing_project_id": ("missing_values", "project_id", "missing_value"),
    "missing_pmb_budget": ("missing_values", "pmb_budget", "missing_value"),
    "missing_actual_cost": ("missing_values", "actual_cost", "missing_value"),
    "type_error_actual_cost": ("type_errors", "actual_cost", "type_error"),
    "type_error_progress_pct": ("type_errors", "progress_pct", "type_error"),
    "progress_above_100": ("bounds_violations", "progress_pct", "bounds_violation"),
    "negative_actual_cost": ("bounds_violations", "actual_cost", "bounds_violation"),
    "negative_pmb_budget": ("bounds_violations", "pmb_budget", "bounds_violation"),
    "actual_date_before_baseline": (
        "logical_anomalies", "multiple", "logical_anomaly"
    ),
    "duplicate_record": ("duplicates", "project_id, time_period", "duplicate"),
}

# Defects that can only be found by comparing a record against *other* records
# of the same project, rather than by inspecting the record on its own.  They
# are held apart from ANOMALY_CATALOGUE because each one has to be placed
# against a neighbouring reporting period, which needs the project ordering.
CROSS_RECORD_CATALOGUE = {
    "negative_period_movement": ("logical_anomalies", "multiple", "logical_anomaly"),
    "spend_ahead_of_progress": ("logical_anomalies", "multiple", "logical_anomaly"),
}


def load_cleaned_data(path=DEFAULT_CLEANED):
    """
    Load the real cleaned dataset with the contract's date columns parsed.

    Args:
        path: Path to the cleaned CSV.

    Returns:
        pd.DataFrame: The dataset, or None when it cannot be loaded.
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


def split_batch_incremental(cleaned, holdout=DEFAULT_HOLDOUT):
    """
    Split real records into a batch history and a later incremental arrival.

    The split is chronological within each project: the final ``holdout``
    reporting periods become the incremental set, representing the newest cost
    records to have arrived, and the remaining periods form the batch history.

    Args:
        cleaned: Cleaned dataset.
        holdout: Number of trailing periods per project to hold back.

    Returns:
        tuple: ``(batch, incremental)`` DataFrames.
    """
    if holdout < 1:
        raise ValueError("holdout must be at least 1 reporting period")

    frame = cleaned.copy()
    frame = frame.sort_values(["project_id", "actual_date"], kind="stable")
    # Rank each project's periods newest-last so the tail can be held back.
    frame["_period_rank"] = frame.groupby("project_id").cumcount()
    totals = frame.groupby("project_id")["_period_rank"].transform("max")
    frame["_is_incremental"] = frame["_period_rank"] > (totals - holdout)

    batch = frame[~frame["_is_incremental"]].drop(
        columns=["_period_rank", "_is_incremental"]
    ).reset_index(drop=True)
    incremental = frame[frame["_is_incremental"]].drop(
        columns=["_period_rank", "_is_incremental"]
    ).reset_index(drop=True)
    return batch, incremental



def _inject_cross_record_defects(frame, rng, record):
    """
    Inject defects that can only be found by comparing records to each other.

    These two defects are the substantive test of the fourth research question.
    Neither can be seen by inspecting a record in isolation: a cumulative cost
    series has to be walked in reporting order, and a cost-to-progress ratio has
    to be compared against every earlier period of the same project.  A
    whole-column formula such as ``MIN()`` or ``COUNTBLANK()`` cannot surface
    either, which is exactly the limitation the comparison is meant to quantify.

    The mutations are applied in place:

    * ``ac_cum_decrease`` makes one period's cumulative cost fall below the
      previous period's, breaking monotonicity for that project's series.
    * ``spend_ahead_of_progress`` pushes one period's cumulative cost far enough
      above the cumulative budget that it outruns the reported progress.

    Args:
        frame: The frame to mutate in place.
        rng: Seeded random generator for deterministic placement.
        record: Callback used to add a ground-truth row.
    """
    ordered = frame.sort_values(["project_id", "actual_date"], kind="stable")

    # Only projects with at least three periods give a usable interior position:
    # a defect has to sit between two other periods to be a *cross-record* one.
    candidates = [
        group.index.tolist()
        for _, group in ordered.groupby("project_id")
        if len(group) >= 3
    ]
    if not candidates:
        return

    # --- A period carrying a negative cost movement. The running total of the
    # project falls as a result, which is only visible once the series has been
    # accumulated in reporting order.
    target = candidates[int(rng.integers(len(candidates)))]
    position = target[1 + int(rng.integers(len(target) - 2))]
    prior_cost = float(frame.loc[target[target.index(position) - 1], "actual_cost"])
    if pd.notna(prior_cost) and prior_cost > 0:
        # Large enough to push the project's cumulative total below the previous
        # one, which is the signature the monotonicity rule looks for.
        frame.loc[position, "actual_cost"] = -round(prior_cost * 1.5, 2)
        record(position, "negative_period_movement")

    # --- Cumulative spend running ahead of reported progress.
    target = candidates[int(rng.integers(len(candidates)))]
    position = target[1 + int(rng.integers(len(target) - 2))]
    budget = float(frame.loc[position, "pmb_budget"])
    if budget > 0:
        # A period cost large enough that cumulative cost exceeds the cumulative
        # budget by more than the progress tolerance the engine allows.
        frame.loc[position, "actual_cost"] = round(budget * 50.0, 2)
        frame.loc[position, "revenue_claimed"] = round(budget * 2.0, 2)
        record(position, "spend_ahead_of_progress")


def inject_known_anomalies(cleaned, seed=DEFAULT_SEED):
    """
    Inject a labelled set of data defects into real records.

    Every defect is recorded in the ground truth with the row index, the defect
    name and the validation-engine key (category, field, anomaly type) that
    should detect it. The records themselves remain the real project cost
    records; only the injected defect is synthetic, which keeps each expected
    detection attributable.

    Args:
        cleaned: Cleaned dataset to build the test set from.
        seed: Seed for deterministic defect placement.

    Returns:
        tuple: ``(anomaly_set, ground_truth)``. ``ground_truth`` has the columns
        ``row_index``, ``anomaly_name``, ``category``, ``field``,
        ``anomaly_type`` and ``detected_by_engine``.

    Raises:
        ValueError: If the dataset is too small to host the catalogue.
    """
    frame = cleaned.copy().reset_index(drop=True)
    required = list(get_contract_specification()["required_fields"])
    total_rows = len(frame)
    scalar_defects = [n for n in sorted(ANOMALY_CATALOGUE) if n != "duplicate_record"]
    defect_count = len(scalar_defects)
    if total_rows <= defect_count * 2:
        raise ValueError(
            f"need more than {defect_count * 2} records to host every defect "
            f"twice, got {total_rows}"
        )

    rng = np.random.default_rng(seed)
    truth = []

    def record(row_index, name):
        catalogue = CROSS_RECORD_CATALOGUE if name in CROSS_RECORD_CATALOGUE \
            else ANOMALY_CATALOGUE
        category, field, anomaly_type = catalogue[name]
        truth.append({
            "row_index": int(row_index),
            "anomaly_name": name,
            "category": category,
            "field": field,
            "anomaly_type": anomaly_type,
            "detected_by_engine": True,
        })

    # Spread the defects across distinct records so each detection is unambiguous.
    targets = rng.choice(total_rows, size=defect_count, replace=False)
    targets = sorted(int(index) for index in targets)

    for row_index, name in zip(targets, scalar_defects):
        if name.startswith("missing_"):
            frame.loc[row_index, name[len("missing_"):]] = np.nan
        elif name.startswith("type_error_"):
            field = name[len("type_error_"):]
            # A real dirty CSV import yields an object column holding text.
            # The sentinel deliberately avoids pandas' default NA tokens
            # ("n/a", "NA", ...), which would survive as a null rather than as
            # a type error and be reported by the missing-value check instead.
            frame[field] = frame[field].astype(object)
            frame.loc[row_index, field] = TYPE_ERROR_SENTINEL
        elif name == "progress_above_100":
            frame.loc[row_index, "progress_pct"] = 150.0
        elif name.startswith("negative_"):
            frame.loc[row_index, name[len("negative_"):]] = -5000.0
        elif name == "actual_date_before_baseline":
            frame.loc[row_index, "actual_date"] = (
                frame.loc[row_index, "baseline_start_date"] - pd.Timedelta(days=7)
            )
        record(row_index, name)

    _inject_cross_record_defects(frame, rng, record)

    # One duplicated record. The duplicate check reports *both* copies, because
    # either half of the pair could be the erroneous one, so both are recorded.
    original = int(rng.choice(total_rows))
    frame = pd.concat([frame, frame.iloc[[original]].copy()], ignore_index=True)
    for index in (original, len(frame) - 1):
        record(index, "duplicate_record")

    ground_truth = pd.DataFrame(truth)
    return frame[required], ground_truth


def detected_keys(validation_results):
    """
    Reduce validation output to a set of comparable detection keys.

    Args:
        validation_results: Output of ``validate_batch`` / ``validate_incremental``.

    Returns:
        set: ``(row_index, field, anomaly_type)`` tuples.
    """
    keys = set()
    anomalies = validation_results.get("anomalies", {})
    for entries in anomalies.values():
        for entry in entries or []:
            keys.add((
                entry.get("row_index"),
                entry.get("field"),
                entry.get("anomaly_type"),
            ))
    return keys


def ground_truth_keys(ground_truth):
    """Return the set of detection keys implied by a ground truth table."""
    return {
        (row.row_index, row.field, row.anomaly_type)
        for row in ground_truth.itertuples()
    }


def count_by_category(validation_results):
    """Return the number of anomalies reported per validation category."""
    anomalies = validation_results.get("anomalies", {})
    return {name: len(entries or []) for name, entries in anomalies.items()}


def score_detection(validation_results, ground_truth):
    """
    Score detection completeness against a ground truth table.

    Detection completeness is the proportion of injected defects that the
    validation engine actually reported, which is the measure the research
    targets at 95% or above.

    Args:
        validation_results: Validation output for the anomaly test set.
        ground_truth: Ground truth table produced by :func:`inject_known_anomalies`.

    Returns:
        dict: Injected/detected counts, the completeness percentage and the
        defects that were missed.
    """
    expected = ground_truth_keys(ground_truth)
    observed = detected_keys(validation_results)
    detected = expected & observed
    missed = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    injected = len(expected)
    completeness = (len(detected) / injected * 100.0) if injected else 0.0
    return {
        "injected": injected,
        "detected": len(detected),
        "missed": len(missed),
        "missed_defects": missed,
        # Flags that no injected defect explains. Some are genuine findings in
        # the real records, and injected defects can also cascade into the
        # cumulative cost/progress rule, so these are reported rather than
        # scored.
        "unexpected_flags": len(unexpected),
        "detection_completeness_pct": round(completeness, 2),
    }


def score_false_positives(validation_results, clean_df):
    """
    Score the flags raised on data that carries no injected defect.

    On the real dataset every flag is a genuine finding rather than a false
    positive, so the per-category counts are reported as well as the overall
    rate. That distinction matters: the progress/cost rule is expected to fire
    on real projects that genuinely overspend early, and those records are
    correctly identified rather than incorrectly flagged.

    Args:
        validation_results: Validation output for the untouched clean data.
        clean_df: The clean data that was validated.

    Returns:
        dict: Record count, total flags, the flag rate and the per-category
        breakdown.
    """
    counts = count_by_category(validation_results)
    total_flags = sum(counts.values())
    records = len(clean_df)
    return {
        "records": records,
        "flags": total_flags,
        "flagged_records_pct": round(total_flags / records * 100.0, 2) if records else 0.0,
        "by_category": counts,
    }


def load_fixtures(cleaned_path=DEFAULT_CLEANED, holdout=DEFAULT_HOLDOUT,
                  seed=DEFAULT_SEED):
    """
    Build the fixtures in memory for use by the system tests.

    The in-memory frames are the authoritative form of the fixtures. The CSV
    exports produced by :func:`build_fixtures` are for inspection and manual
    use: a genuine type error turns its whole column into text when pandas
    re-reads the file (exactly as a real dirty CSV behaves), which would make
    the ground truth ambiguous. Building in memory keeps every injected defect
    isolated to the single record it was placed on.

    Args:
        cleaned_path: Source dataset.
        holdout: Trailing periods per project held back as incremental.
        seed: Seed for defect placement.

    Returns:
        dict | None: Keys ``cleaned``, ``batch``, ``incremental``,
        ``anomaly_set`` and ``ground_truth``, or None when unavailable.
    """
    cleaned = load_cleaned_data(cleaned_path)
    if cleaned is None:
        return None
    batch, incremental = split_batch_incremental(cleaned, holdout=holdout)
    anomaly_set, ground_truth = inject_known_anomalies(cleaned, seed=seed)
    return {
        "cleaned": cleaned,
        "batch": batch,
        "incremental": incremental,
        "anomaly_set": anomaly_set,
        "ground_truth": ground_truth,
    }


def build_fixtures(cleaned_path=DEFAULT_CLEANED, holdout=DEFAULT_HOLDOUT, seed=DEFAULT_SEED):
    """
    Build and persist every real-data fixture.

    Args:
        cleaned_path: Source dataset.
        holdout: Trailing periods per project held back as incremental.
        seed: Seed for defect placement.

    Returns:
        dict | None: The built fixtures, or None when the source is unavailable.
    """
    cleaned = load_cleaned_data(cleaned_path)
    if cleaned is None:
        return None

    batch, incremental = split_batch_incremental(cleaned, holdout=holdout)
    anomaly_set, ground_truth = inject_known_anomalies(cleaned, seed=seed)

    for path in (DEFAULT_BATCH, DEFAULT_INCREMENTAL, DEFAULT_ANOMALY_SET,
                 DEFAULT_GROUND_TRUTH):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    batch.to_csv(DEFAULT_BATCH, index=False)
    incremental.to_csv(DEFAULT_INCREMENTAL, index=False)
    anomaly_set.to_csv(DEFAULT_ANOMALY_SET, index=False)
    ground_truth.to_csv(DEFAULT_GROUND_TRUTH, index=False)

    print(f"Batch (historical) records    : {len(batch)}")
    print(f"Incremental (newest) records  : {len(incremental)}")
    print(f"Anomaly test set records      : {len(anomaly_set)}")
    print(f"Labelled defects              : {len(ground_truth)}")
    for path in (DEFAULT_BATCH, DEFAULT_INCREMENTAL, DEFAULT_ANOMALY_SET,
                 DEFAULT_GROUND_TRUTH):
        print(f"  wrote {path}")
    return {
        "cleaned": cleaned,
        "batch": batch,
        "incremental": incremental,
        "anomaly_set": anomaly_set,
        "ground_truth": ground_truth,
    }


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Build real-data test fixtures from the cleaned Kaggle dataset."
    )
    parser.add_argument("--cleaned", default=DEFAULT_CLEANED,
                        help="Cleaned Kaggle dataset to build fixtures from")
    parser.add_argument("--holdout", type=int, default=DEFAULT_HOLDOUT,
                        help="Trailing periods per project held back as incremental")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="Seed for deterministic defect placement")
    args = parser.parse_args()

    if build_fixtures(cleaned_path=args.cleaned, holdout=args.holdout,
                      seed=args.seed) is None:
        return 1
    print("\nNext: python -m dqd.reporting.run_pipeline   (runs the full evidence chain)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
