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

Standalone synthetic set (``data/synthetic/``)
----------------------------------------------
The labelled set above measures *detection* against defects planted in real
rows, but it cannot claim that every rule fires - R10 and R13, for instance,
need shapes the real series do not contain.  :func:`write_synthetic_data`
therefore also derives a small from-scratch set whose only job is to make every
rule R1-R14 fire at least once, together with a ground-truth CSV of the exact
findings each planted defect must produce.  The README reports it as its own
section, next to the original and cleaned Kaggle data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Standalone synthetic set: every rule, end to end (data/synthetic/)
# ---------------------------------------------------------------------------

#: File names of the standalone synthetic set.
SYNTHETIC_RAW_NAME = "synthetic_original_data.csv"
SYNTHETIC_DERIVED_NAME = "synthetic_cleaned_data.csv"
SYNTHETIC_TRUTH_NAME = "synthetic_ground_truth.csv"

#: Every rule id the engine defines; coverage is measured against this list.
ALL_RULE_IDS = [f"R{i}" for i in range(1, 15)]

_RAW_COLUMNS = [
    "project_id", "project_name", "source_file", "wbs_code",
    "wbs_description", "period_date", "period_index", "pv_cum", "ac_cum",
    "ev_cum",
]

_DERIVED_COLUMNS = [
    "project_id", "time_period", "pmb_budget", "actual_cost",
    "progress_pct", "revenue_claimed", "actual_date", "baseline_start_date",
]

#: Reporting dates shared by every three-period synthetic raw series.
_DATES = ["2024-01-31", "2024-02-29", "2024-03-31"]


def synthetic_directory() -> Path:
    """The repository's ``data/synthetic/`` folder."""
    return Path(__file__).resolve().parents[2] / "data" / "synthetic"


def build_synthetic_raw() -> tuple[pd.DataFrame, list[dict]]:
    """Build the synthetic raw tier, on which R1-R12 all fire.

    Each project is one controlled experiment:

    * P01 - untouched control: two clean series producing no finding at all
    * P02 - R9: earned value restated downwards at period 2
    * P03 - R10: period 2's date mistyped a decade forward, beyond every
      later report; R8: the series' date order broken as a consequence
    * P04 - R6: one row of the project carries a second name
    * P05 - R7: one row of the series carries a second description;
      R12: another row's description emptied
    * P06 - R4: negative ac_cum; R1: empty project_name; R5: an exact
      duplicate of the first row
    * P07 - R3: period_index 0; R2: a period_date nothing can parse
    * P08 - R11: source_file naming a project that does not exist

    Every other property stays well-formed, so anything the engine reports is
    attributable to a planted defect rather than to an accident of the fixture.

    Returns:
        tuple: ``(frame, planted)`` - each planted entry records the row a
        defect sits on and the finding it must produce.
    """
    rows: list[dict] = []
    planted: list[dict] = []

    def add(project_id: str, project_name: str, source_file: str,
            wbs_code: str, wbs_description: str, period_date, period_index,
            pv, ac, ev) -> int:
        rows.append({
            "project_id": project_id,
            "project_name": project_name,
            "source_file": source_file,
            "wbs_code": wbs_code,
            "wbs_description": wbs_description,
            "period_date": period_date,
            "period_index": period_index,
            "pv_cum": pv,
            "ac_cum": ac,
            "ev_cum": ev,
        })
        return len(rows) - 1

    def expect(row_index: int, rule_id: str, field: str,
               anomaly_type: str) -> None:
        planted.append({
            "tier": "raw",
            "row_index": row_index,
            "rule_id": rule_id,
            "field": field,
            "anomaly_type": anomaly_type,
        })

    def series(project: str, name: str, source: str, wbs: str,
               description: str, dates: list[str], periods: list[int],
               pv: list, ac: list, ev: list) -> list[int]:
        return [
            add(project, name, source, wbs, description,
                dates[i], periods[i], pv[i], ac[i], ev[i])
            for i in range(len(periods))
        ]

    # P01 - the control: two clean series over the shared dates.
    for wbs, description, pv, ac, ev in [
        ("9001", "Control works",
         [1000, 2000, 3000], [800, 1600, 2400], [900, 1800, 2700]),
        ("9002", "Enabling works",
         [500, 1000, 1500], [400, 800, 1200], [450, 900, 1350]),
    ]:
        series("P01", "Synthetic Control Project",
               "P01 - Synthetic Control.xlsx", wbs, description,
               _DATES, [1, 2, 3], pv, ac, ev)

    # P02 - R9: earned value falls below the total it reported last period.
    idx = series("P02", "Synthetic Restatement Project",
                 "P02 - Synthetic Restatement.xlsx", "9101", "Earthworks",
                 _DATES, [1, 2, 3], [1500, 3000, 4500],
                 [1000, 2000, 3000], [5000, 4800, 5200])
    expect(idx[1], "R9", "ev_cum", "cumulative_restatement")

    # P03 - R10: period 2 mistyped a decade forward, beyond every later
    # report in its own series; R8: period 3 then precedes period 2.
    idx = series(
        "P03", "Synthetic Date Project", "P03 - Synthetic Dates.xlsx",
        "9201", "Piling",
        ["2024-01-31", "2031-12-31", "2024-03-31"], [1, 2, 3],
        [1000, 2000, 3000], [900, 1800, 2700], [950, 1900, 2850])
    expect(idx[1], "R10", "period_date", "date_beyond_window")
    expect(idx[2], "R8", "period_date", "date_out_of_order")

    # P04 - R6: period 2 renames the project, so all three rows conflict.
    idx = []
    for i in range(3):
        idx.append(add(
            "P04",
            "Synthetic Rename Project (v2)" if i == 1
            else "Synthetic Rename Project",
            "P04 - Synthetic Rename.xlsx", "9301", "Piling",
            _DATES[i], i + 1,
            [1000, 2000, 3000][i], [800, 1600, 2400][i], [900, 1800, 2700][i]))
    expect(idx[1], "R6", "project_name", "inconsistent_project_name")

    # P05 - R7: period 2 carries a second description; R12: period 3's
    # description is emptied (which R1 also reads as a missing field).
    descriptions = ["Structural works", "Structural works - revised", ""]
    idx = []
    for i in range(3):
        idx.append(add(
            "P05", "Synthetic Consistency Project",
            "P05 - Synthetic Consistency.xlsx", "9401", descriptions[i],
            _DATES[i], i + 1,
            [1000, 2000, 3000][i], [700, 1400, 2100][i], [900, 1800, 2700][i]))
    expect(idx[1], "R7", "wbs_description", "inconsistent_wbs_description")
    expect(idx[2], "R12", "wbs_description", "missing_wbs_description")

    # P06 - R4, R1 and R5 in one project.  The appended row is an exact copy
    # of the first, so both copies share one composite key for R5 to flag.
    first = add("P06", "Synthetic Defects Project",
                "P06 - Synthetic Defects.xlsx", "9501", "Concrete works",
                "2024-01-31", 1, 2000, 1500, 1800)
    negative = add("P06", "Synthetic Defects Project",
                   "P06 - Synthetic Defects.xlsx", "9501", "Concrete works",
                   "2024-02-29", 2, 4000, -500, 3600)
    unnamed = add("P06", "",
                  "P06 - Synthetic Defects.xlsx", "9501", "Concrete works",
                  "2024-03-31", 3, 6000, 4500, 5400)
    rows.append(dict(rows[first]))
    expect(negative, "R4", "ac_cum", "out_of_bounds_value")
    expect(unnamed, "R1", "project_name", "missing_required_field")
    expect(first, "R5", "project_id, wbs_code, period_index", "duplicate_key")

    # P07 - R3: period_index 0; R2: a period_date nothing can parse.
    broken_period = add(
        "P07", "Synthetic Type Project", "P07 - Synthetic Types.xlsx",
        "9601", "Drainage", "2024-01-31", 0, 1000, 500, 700)
    broken_date = add(
        "P07", "Synthetic Type Project", "P07 - Synthetic Types.xlsx",
        "9601", "Drainage", "not-a-date", 1, 2000, 1000, 1400)
    add(
        "P07", "Synthetic Type Project", "P07 - Synthetic Types.xlsx",
        "9601", "Drainage", "2024-03-31", 2, 3000, 1500, 2100)
    expect(broken_period, "R3", "period_index", "out_of_bounds_value")
    expect(broken_date, "R2", "period_date", "unexpected_data_type")

    # P08 - R11: period 1 arrived under a workbook naming another project.
    idx = []
    for i in range(3):
        idx.append(add(
            "P08", "Synthetic Attribution Project",
            "P999 - Wrong Project Workbook.xlsx" if i == 0
            else "P08 - Synthetic Attribution.xlsx",
            "9701", "Steelwork", _DATES[i], i + 1,
            [1000, 2000, 3000][i], [600, 1200, 1800][i],
            [800, 1600, 2400][i]))
    expect(idx[0], "R11", "source_file", "source_file_mismatch")

    return pd.DataFrame(rows, columns=_RAW_COLUMNS), planted


def build_synthetic_derived() -> tuple[pd.DataFrame, list[dict]]:
    """Build the synthetic derived tier, on which R8, R13 and R14 all fire.

    * P01 - untouched control; no rule fires
    * P02 - R13: cumulative actual cost past 3x cumulative budget at periods
      2 and 3, with the R14 overrun the same spend guarantees
    * P03 - R14 alone: spend outruns progress without breaching R13
    * P04 - derived R8: period 1's actual_date precedes the baseline

    Money columns are period movements and stay non-decreasing, so every
    finding is attributable to a planted defect.

    Returns:
        tuple: ``(frame, planted)``, as :func:`build_synthetic_raw`.
    """
    rows: list[dict] = []
    planted: list[dict] = []

    def add(project_id: str, time_period: str, budget, actual, progress,
            revenue, actual_date: str, baseline: str) -> int:
        rows.append({
            "project_id": project_id,
            "time_period": time_period,
            "pmb_budget": budget,
            "actual_cost": actual,
            "progress_pct": progress,
            "revenue_claimed": revenue,
            "actual_date": actual_date,
            "baseline_start_date": baseline,
        })
        return len(rows) - 1

    def expect(row_index: int, rule_id: str, field: str,
               anomaly_type: str) -> None:
        planted.append({
            "tier": "derived",
            "row_index": row_index,
            "rule_id": rule_id,
            "field": field,
            "anomaly_type": anomaly_type,
        })

    # P01 - the control: steady spend with progress ahead of the spend ratio.
    for i in range(3):
        add("P01", f"Month-{i + 1}", 100, [50, 60, 70][i], [10, 20, 30][i],
            [40, 80, 120][i], f"2024-{i + 1:02d}-01", "2024-01-01")

    # P02 - R13: actual cost runs past three times the budget from period 2,
    # and that same spend is many times the progress reported (R14).
    idx = []
    for i in range(3):
        idx.append(add("P02", f"Month-{i + 1}", 100, [50, 1000, 1100][i],
                       [10, 20, 30][i], [40, 80, 120][i],
                       f"2024-{i + 1:02d}-01", "2024-01-01"))
    expect(idx[1], "R13", "actual_cost", "budget_overrun")
    expect(idx[2], "R13", "actual_cost", "budget_overrun")
    expect(idx[1], "R14", "progress_pct", "progress_mismatch")
    expect(idx[2], "R14", "progress_pct", "progress_mismatch")

    # P03 - R14 alone: the spend ratio is 100% against single-digit progress,
    # yet cumulative cost stays far below three times cumulative budget.
    idx = []
    for i, (actual, progress) in enumerate([(100, 10), (110, 20)]):
        idx.append(add("P03", f"Month-{i + 1}", 100, actual, progress,
                       [50, 100][i], f"2024-{i + 1:02d}-01", "2024-01-01"))
    expect(idx[0], "R14", "progress_pct", "progress_mismatch")
    expect(idx[1], "R14", "progress_pct", "progress_mismatch")

    # P04 - derived R8: period 1 reported before the project's baseline start.
    first = add("P04", "Month-1", 100, 10, 10, 30, "2023-12-01", "2024-01-01")
    add("P04", "Month-2", 100, 20, 20, 60, "2024-02-01", "2024-01-01")
    expect(first, "R8", "actual_date", "baseline_date_violation")

    return pd.DataFrame(rows, columns=_DERIVED_COLUMNS), planted


def write_synthetic_data(directory: Path | None = None) -> dict[str, Path]:
    """Materialise the standalone synthetic set as CSV files.

    The ground truth is keyed *after* the files are written, by reading them
    back through the same normalisation the validator applies.  The recorded
    ``record_key`` values therefore match the findings the engine will produce
    rather than a hand-rolled approximation of them - leading-zero wbs codes,
    coerced dates and CSV type inference are all on the path from writer to
    reader, and each one could silently desynchronise a hand-built key.

    Args:
        directory: Target folder; defaults to ``data/synthetic/``.

    Returns:
        dict: Absolute path of each written file, keyed by role.
    """
    from ..contracts.derived import DERIVED_KEY
    from ..contracts.raw import RAW_KEY
    from ..engine.rules import record_key
    from ..engine.validator import normalise_types

    directory = Path(directory) if directory is not None else synthetic_directory()
    directory.mkdir(parents=True, exist_ok=True)

    raw, raw_planted = build_synthetic_raw()
    derived, derived_planted = build_synthetic_derived()

    paths = {
        "raw": directory / SYNTHETIC_RAW_NAME,
        "derived": directory / SYNTHETIC_DERIVED_NAME,
        "ground_truth": directory / SYNTHETIC_TRUTH_NAME,
    }
    raw.to_csv(paths["raw"], index=False)
    derived.to_csv(paths["derived"], index=False)

    frames = {
        "raw": normalise_types(pd.read_csv(paths["raw"])),
        "derived": normalise_types(pd.read_csv(paths["derived"])),
    }
    keys = {"raw": list(RAW_KEY), "derived": list(DERIVED_KEY)}

    truth_rows = []
    for n, entry in enumerate(raw_planted + derived_planted, start=1):
        frame = frames[entry["tier"]]
        row = frame.iloc[entry["row_index"]]
        truth_rows.append({
            "defect_id": f"S{n:03d}",
            "tier": entry["tier"],
            "record_key": record_key(row, keys[entry["tier"]]),
            "rule_id": entry["rule_id"],
            "field": entry["field"],
            "anomaly_type": entry["anomaly_type"],
        })
    pd.DataFrame(truth_rows, columns=[
        "defect_id", "tier", "record_key", "rule_id", "field", "anomaly_type",
    ]).to_csv(paths["ground_truth"], index=False)
    return paths


def ensure_synthetic_data(directory: Path | None = None) -> Path:
    """Write the synthetic set if it is not already on disk.

    Reporting code calls this before measuring, so a fresh clone produces the
    files on first run while an existing set is left untouched.

    Args:
        directory: Target folder; defaults to ``data/synthetic/``.

    Returns:
        Path: The folder holding the set.
    """
    directory = Path(directory) if directory is not None else synthetic_directory()
    required = (SYNTHETIC_RAW_NAME, SYNTHETIC_DERIVED_NAME, SYNTHETIC_TRUTH_NAME)
    if not all((directory / name).is_file() for name in required):
        write_synthetic_data(directory)
    return directory
