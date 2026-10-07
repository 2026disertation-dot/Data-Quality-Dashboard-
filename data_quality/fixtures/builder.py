"""Synthetic defect fixtures derived from the real dataset (Section 5.2).

Why synthetic defects are necessary
-----------------------------------
The real Kaggle Project Portfolio data is **structurally clean**.  Profiling it
yields zero missing fields, zero duplicate keys, zero format conflicts and zero
out-of-bounds values.  Only the cumulative rule (R9) fires, on 22 decreasing
steps.

That is a genuine finding, but it means the real data cannot exercise R1, R2,
R3, R4, R5, R11 or R12 at all: there is nothing in it for those rules to catch.
Section 5.2 of the research anticipates exactly this, stating that "synthetic
malformed variants were created by deliberately introducing missing fields, type
errors, out-of-bounds values, and logical anomalies into the original dataset",
and it specifies test sets of 500 regression records, 250 labelled anomalies
and 500 clean records.

So this module derives, from real records only:

* a **batch / incremental** split, for dual-mode regression
* a **labelled defect set** with a ground-truth table, for detection completeness
* a **clean sample**, for the false-positive rate

Every synthetic row is a real record with one controlled defect applied, and the
ground truth records exactly what was changed.  Nothing is invented: the values
come from the source dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

#: Sizes from Section 5.2 of the research.
DEFAULT_REGRESSION_SAMPLE = 500
DEFAULT_ANOMALY_COUNT = 250
DEFAULT_CLEAN_SAMPLE = 500


@dataclass
class Fixtures:
    """The derived test sets."""

    batch: pd.DataFrame
    incremental: pd.DataFrame
    defects: pd.DataFrame
    ground_truth: pd.DataFrame
    clean: pd.DataFrame
    regression: pd.DataFrame


def _rng(seed: int = 20240229) -> np.random.Generator:
    """Seeded generator so every run produces identical fixtures."""
    return np.random.default_rng(seed)


def known_defect_keys(raw: pd.DataFrame) -> set[str]:
    """Identify rows that already breach R9, so they can be excluded.

    Args:
        raw: The raw WBS-level frame.

    Returns:
        set: Composite keys already at fault in the source data.
    """
    from ..engine.validator import Validator

    result = Validator().validate(raw, tier="raw")
    return {f.record_key for f in result.findings if f.rule_id == "R9"}


def build_fixtures(
    raw: pd.DataFrame,
    regression_sample: int = DEFAULT_REGRESSION_SAMPLE,
    anomaly_count: int = DEFAULT_ANOMALY_COUNT,
    clean_sample: int = DEFAULT_CLEAN_SAMPLE,
) -> Fixtures:
    """Derive every test set from the real dataset.

    Args:
        raw: The raw WBS-level dataset.
        regression_sample: Records used for the batch/incremental comparison.
        anomaly_count: Labelled defects to inject.
        clean_sample: Clean records used for the false-positive measurement.

    Returns:
        Fixtures: The derived frames plus the ground-truth table.
    """
    frame = raw.copy()
    frame["wbs_code"] = frame["wbs_code"].astype(str)
    frame["period_date"] = pd.to_datetime(frame["period_date"], errors="coerce")

    known = known_defect_keys(frame)
    keys = (
        frame["project_id"].astype(str)
        + "|" + frame["wbs_code"].astype(str)
        + "|" + frame["period_index"].astype(str)
    )
    clean_pool = frame[~keys.isin(known)].reset_index(drop=True)

    size = min(regression_sample, len(frame))
    regression = frame.sample(n=size, random_state=7).reset_index(drop=True)

    clean_n = min(clean_sample, len(clean_pool))
    clean = clean_pool.sample(n=clean_n, random_state=11).reset_index(drop=True)

    defects, truth = _inject_defects(frame, anomaly_count, _rng())

    latest = frame["period_index"].max()
    batch = frame[frame["period_index"] < latest].reset_index(drop=True)
    incremental = frame[frame["period_index"] >= latest].reset_index(drop=True)

    return Fixtures(
        batch=batch,
        incremental=incremental,
        defects=defects,
        ground_truth=truth,
        clean=clean,
        regression=regression,
    )


#: Defect catalogue.  Each entry is (rule_id, field, anomaly_type, action).
#: Cycling through it guarantees every rule that *can* be violated synthetically
#: is represented in the labelled set, so detection completeness is not measured
#: against only the easy cases.
DEFECT_CATALOGUE = [
    ("R1", "project_name", "missing_required_field", "set_null"),
    ("R12", "wbs_description", "missing_wbs_description", "set_empty"),
    ("R2", "period_date", "unexpected_data_type", "set_text"),
    ("R4", "ac_cum", "out_of_bounds_value", "set_negative"),
    ("R4", "pv_cum", "out_of_bounds_value", "set_negative"),
    ("R3", "period_index", "out_of_bounds_value", "set_zero"),
    ("R11", "source_file", "source_file_mismatch", "swap_project"),
    ("R6", "project_name", "inconsistent_project_name", "rename_project"),
    ("R9", "ev_cum", "cumulative_restatement", "reduce_total"),
    ("R9", "ac_cum", "cumulative_restatement", "reduce_total"),
]


def _reducible_positions(
    frame: pd.DataFrame, pristine: pd.DataFrame, field: str
) -> list[int]:
    """Rows whose cumulative total can be visibly undercut.

    A row qualifies when its series has an earlier period reporting a non-zero
    value for ``field``, because that earlier figure is the baseline the
    restatement must fall below.  Computed with a single grouped shift rather
    than a per-row scan, which would be quadratic over 2,727 rows.
    """
    work = pristine[["project_id", "wbs_code", "period_index", field]].copy()
    work = work.sort_values(["project_id", "wbs_code", "period_index"], kind="stable")
    previous = work.groupby(["project_id", "wbs_code"])[field].shift(1)
    eligible = work.index[previous.notna() & (previous > 0)]
    return sorted(int(pristine.index.get_loc(i)) for i in eligible)


def _apply_defect(
    frame: pd.DataFrame,
    pristine: pd.DataFrame,
    position: int,
    field: str,
    action: str,
    rng: np.random.Generator,
) -> None:
    """Apply one controlled defect to one row of ``frame``, in place.

    Args:
        frame: The frame being mutated.
        pristine: The untouched source frame.  Baselines are read from here, not
            from ``frame``: once one row is damaged, a later injection into the
            same series would compute its baseline from the damaged value and
            produce a restatement that no longer falls below anything.
        position: Row index to damage.
        field: Column to damage.
        action: Which defect to apply.
        rng: Seeded generator.
    """
    current = frame.iat[position, frame.columns.get_loc(field)]

    if action == "set_null":
        value = None
    elif action == "set_empty":
        value = ""
    elif action == "set_text":
        value = "not-a-date"
    elif action == "set_negative":
        value = float(rng.uniform(-50000.0, -1.0))
    elif action == "set_zero":
        value = 0
    elif action == "swap_project":
        frame.iat[position, frame.columns.get_loc("source_file")] = (
            "P999 - Wrong Project Workbook.xlsx"
        )
        return
    elif action == "rename_project":
        project = frame.iat[position, frame.columns.get_loc("project_id")]
        frame.iat[position, frame.columns.get_loc(field)] = f"Renamed Project {project}"
        return
    elif action == "reduce_total":
        # Reduced below the value the same series reported at the preceding
        # period, so the fall is guaranteed to be visible to R9.
        series = pristine[
            (pristine["project_id"] == pristine.iat[position, frame.columns.get_loc("project_id")])
            & (pristine["wbs_code"] == pristine.iat[position, frame.columns.get_loc("wbs_code")])
        ].sort_values("period_index")
        earlier = series[
            series["period_index"] < pristine.iat[position, frame.columns.get_loc("period_index")]
        ]
        baseline = float(earlier[field].iloc[-1])
        # Strictly below the preceding period's reported total, so the fall R9
        # looks for is unambiguous.
        value = round(baseline * 0.5, 2)
    else:  # pragma: no cover - the catalogue is closed
        raise ValueError(f"unknown action {action!r}")

    frame.iat[position, frame.columns.get_loc(field)] = value


def _inject_defects(
    frame: pd.DataFrame, count: int, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject labelled defects, recording exactly what was changed.

    Args:
        frame: Real raw records to draw from.
        count: Number of defects to inject.
        rng: Seeded generator.

    Returns:
        tuple: ``(defective_frame, ground_truth)``.
    """
    # Defects are injected *into the full dataset*, not into a standalone frame.
    # A defect sitting alone in its own (project_id, wbs_code) group has no
    # neighbouring period, so the cumulative rules R9 and R14 could never fire on
    # it no matter how correctly they were implemented.  Injecting in place keeps
    # every defective record inside its real series, which is also the realistic
    # scenario: a malformed row arriving inside an established portfolio.
    pristine = frame.reset_index(drop=True).copy()
    defective = pristine.copy()
    # Dates are held as objects so a malformed value can be injected.  A frame
    # read straight from a spreadsheet does carry text dates, so this mirrors
    # the real ingestion shape rather than fabricating one.
    defective["period_date"] = defective["period_date"].astype(object)

    rows: list[dict] = []
    truth_rows: list[dict] = []

    used: set[int] = set()
    for n in range(count):
        rule_id, field, anomaly_type, action = DEFECT_CATALOGUE[n % len(DEFECT_CATALOGUE)]

        if action == "reduce_total":
            # A cumulative restatement is only observable where the series has a
            # preceding period holding a non-zero total.  The first period has no
            # predecessor, and a zero baseline cannot be undercut, so a defect
            # planted there is undetectable by any implementation.  Counting such
            # rows would understate completeness for a reason unrelated to R9.
            candidates = _reducible_positions(defective, pristine, field)
        else:
            candidates = list(range(len(defective)))

        for _attempt in range(128):
            position = int(candidates[int(rng.integers(0, len(candidates)))])
            if position not in used:
                break
        used.add(position)

        before = defective.iloc[position].to_dict()
        _apply_defect(defective, pristine, position, field, action, rng)
        after = defective.iloc[position].to_dict()

        truth_rows.append(
            {
                "defect_id": f"D{n + 1:04d}",
                "row_index": position,
                "record_key": f"{after['project_id']}|{after['wbs_code']}|{after['period_index']}",
                "project_id": after["project_id"],
                "wbs_code": str(after["wbs_code"]),
                "period_index": after["period_index"],
                "field": field,
                "rule_id": rule_id,
                "anomaly_type": anomaly_type,
                "action": action,
                "original_value": before.get(field),
                "defective_value": after.get(field),
            }
        )
        rows.append(after)

    return defective, pd.DataFrame(truth_rows)
