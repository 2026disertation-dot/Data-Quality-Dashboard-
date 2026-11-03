"""Synthetic defect fixtures derived from the real dataset (Section 5.2).

Why synthetic defects are necessary
-----------------------------------
The real Project Portfolio data is **structurally clean** at the WBS level: the
raw-tier rules (R1-R7, R10-R12) all return zero findings.  On the derived
(project-period) tier only R14 and a single R9 fire on real data.  That is a
genuine finding, but it means the real data cannot exercise the other rules at
all.

Section 5.2 of the research anticipates exactly this: synthetic malformed
variants are created by deliberately introducing missing fields, type errors,
out-of-bounds values and logical anomalies into the original dataset.  Table
3.10 specifies the ground-truth protocol, and §5.8 evaluates detection
completeness against **20 defects per rule x 14 rules = 280 defects**.

Isolation: one defect, one context
----------------------------------
Each labelled defect is injected into an **isolated copy of its record's
context** - the single row, the row's WBS series, or the row's project,
depending on what the rule reads.  Validating one defect at a time is what makes
the ground truth honest: if two defects were injected into one shared frame they
could mask or overwrite each other (two rules writing the same field, or two
adjacent periods each being "reduced" so neither final value falls below the
other), and a correctly implemented rule would then be recorded as a miss for a
reason unrelated to the rule.  Isolating each defect removes that artefact.

Two tiers, two rule sets
------------------------
Rules are tier-gated (Chapter 3 Table 3.9): the WBS-level view runs R1-R7, R10,
R11 and R12 (10 rules); the project-period view runs R8, R9, R13 and R14 (4
rules).  Defects are therefore injected on the tier whose contract carries the
columns the rule reads:

* **raw**     - 10 rules x 20 = 200 defects, injected into real WBS records;
* **derived** - 4 rules x 20 = 80 defects, injected into real project-period
  records.

Every synthetic row is a real record with one controlled defect applied, and the
ground truth records exactly what was changed.  Nothing is invented: the values
come from the source dataset.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: Sizes from Table 3.10 of the research (Chapter 3).
DEFAULT_REGRESSION_SAMPLE = 400
DEFAULT_CLEAN_SAMPLE = 200

#: Defects injected per rule.  14 rules x 20 = 280 labelled anomalies (§5.8).
ANOMALIES_PER_RULE = 20

#: Retained for callers that quote the headline figure.
DEFAULT_ANOMALY_COUNT = ANOMALIES_PER_RULE * 14


@dataclass
class Fixtures:
    """The derived test sets.

    Defect sets are lists of isolated per-defect frames rather than one shared
    frame; see the module docstring for why.
    """

    batch: pd.DataFrame
    incremental: pd.DataFrame
    regression: pd.DataFrame
    clean: pd.DataFrame
    defects: list[pd.DataFrame] = field(default_factory=list)
    ground_truth: pd.DataFrame = field(default_factory=pd.DataFrame)
    derived_defects: list[pd.DataFrame] = field(default_factory=list)
    derived_ground_truth: pd.DataFrame = field(default_factory=pd.DataFrame)
    derived_clean: pd.DataFrame | None = None


def _rng(seed: int = 42) -> np.random.Generator:
    """Seeded generator so every run produces identical fixtures."""
    return np.random.default_rng(seed)


def known_defect_keys(raw: pd.DataFrame) -> set[str]:
    """Identify rows already at fault on the raw tier, so they can be excluded.

    Args:
        raw: The raw WBS-level frame.

    Returns:
        set: Composite keys already carrying a raw-tier finding.
    """
    from ..engine.validator import Validator

    result = Validator().validate(raw, tier="raw")
    return {f.record_key for f in result.all_findings}


def known_derived_defects(derived: pd.DataFrame) -> set[tuple[str, str]]:
    """Identify (record_key, rule_id) pairs already at fault on the derived tier.

    A row already failing a rule cannot testify that an injected defect of that
    same rule was detected, so those pairs are excluded from the candidate pool.

    Args:
        derived: The real project-period frame.

    Returns:
        set: ``(record_key, rule_id)`` pairs already reported.
    """
    from ..engine.validator import Validator

    result = Validator().validate(derived, tier="derived")
    return {(f.record_key, f.rule_id) for f in result.all_findings}


def build_fixtures(
    raw: pd.DataFrame,
    derived: pd.DataFrame | None = None,
    regression_sample: int = DEFAULT_REGRESSION_SAMPLE,
    clean_sample: int = DEFAULT_CLEAN_SAMPLE,
) -> Fixtures:
    """Derive every test set from the real dataset.

    Args:
        raw: The raw WBS-level dataset.
        derived: The project-period dataset.  When supplied, the derived-tier
            defect set and clean sample are built too; when omitted the derived
            fields are left empty so callers that only need the raw tier keep
            working.
        regression_sample: Records used for the batch/incremental comparison.
        clean_sample: Clean raw records used for the false-positive measurement.

    Returns:
        Fixtures: The derived frames plus the ground-truth tables.
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

    contexts, truth = _inject_defects(frame, ANOMALIES_PER_RULE, _rng())

    latest = frame["period_index"].max()
    batch = frame[frame["period_index"] < latest].reset_index(drop=True)
    incremental = frame[frame["period_index"] >= latest].reset_index(drop=True)

    derived_contexts: list[pd.DataFrame] = []
    derived_truth = pd.DataFrame()
    derived_clean = None
    if derived is not None and len(derived):
        derived_frame = derived.copy()
        for column in ("actual_date", "baseline_start_date"):
            if column in derived_frame.columns:
                derived_frame[column] = pd.to_datetime(
                    derived_frame[column], errors="coerce"
                )
        derived_contexts, derived_truth = _inject_derived_defects(
            derived_frame, ANOMALIES_PER_RULE, _rng(seed=43)
        )
        at_fault = {key for key, _rule in known_derived_defects(derived_frame)}
        keep = ~derived_frame.apply(
            lambda row: f"{row['project_id']}|{row['time_period']}" in at_fault,
            axis=1,
        )
        derived_clean = derived_frame[keep].reset_index(drop=True)

    return Fixtures(
        batch=batch,
        incremental=incremental,
        regression=regression,
        clean=clean,
        defects=contexts,
        ground_truth=truth,
        derived_defects=derived_contexts,
        derived_ground_truth=derived_truth,
        derived_clean=derived_clean,
    )


# --------------------------------------------------------------------------
# Raw tier (WBS-level): R1-R7, R10, R11, R12 - 10 rules.
# --------------------------------------------------------------------------

#: Raw-tier defect catalogue.  Each entry is
#: ``(rule_id, field, anomaly_type, action)``.
RAW_DEFECT_CATALOGUE = [
    ("R1",  "project_name",    "missing_required_field",       "set_null"),
    ("R2",  "period_date",     "unexpected_data_type",         "set_text"),
    ("R3",  "period_index",    "out_of_bounds_value",          "set_zero"),
    ("R4",  "ac_cum",          "out_of_bounds_value",          "set_negative"),
    ("R5",  "wbs_code",        "duplicate_record",             "create_duplicate"),
    ("R6",  "project_name",    "inconsistent_project_name",    "rename_project"),
    ("R7",  "wbs_description", "inconsistent_wbs_description", "rename_description"),
    ("R10", "period_date",     "date_outside_window",          "set_future_date"),
    ("R11", "source_file",     "source_file_mismatch",         "swap_project"),
    ("R12", "wbs_description", "missing_wbs_description",      "set_empty"),
]

#: The context a raw rule needs: the row alone, its WBS series, or its whole
#: project.  Context is what the rule reads, so judging it against anything less
#: would make some defects undetectable by construction.
RAW_CONTEXT = {
    "R1": "row", "R2": "row", "R3": "row", "R4": "row", "R12": "row",
    "R5": "project", "R6": "project", "R11": "project",
    "R7": "series", "R10": "series",
}

# Backwards-compatible alias (the raw catalogue was previously just
# ``DEFECT_CATALOGUE``).
DEFECT_CATALOGUE = RAW_DEFECT_CATALOGUE


def _apply_defect(
    frame: pd.DataFrame,
    pristine: pd.DataFrame,
    position: int,
    field: str,
    action: str,
    rng: np.random.Generator,
) -> None:
    """Apply one controlled raw-tier defect to one row of ``frame``, in place.

    Args:
        frame: The context frame being mutated.
        pristine: The untouched context.  Baselines are read from here, not from
            ``frame``, so a defect is computed against the real value.
        position: Row index to damage.
        field: Column to damage.
        action: Which defect to apply.
        rng: Seeded generator.
    """
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
    elif action == "rename_description":
        # Give this row a description that conflicts with another row sharing
        # the same (project_id, wbs_code), triggering R7.
        project = frame.iat[position, frame.columns.get_loc("project_id")]
        wbs_code = frame.iat[position, frame.columns.get_loc("wbs_code")]
        frame.iat[position, frame.columns.get_loc(field)] = (
            f"Alternate description for {wbs_code} ({project})"
        )
        return
    elif action == "create_duplicate":
        # Make this row share its composite key with another row in the same
        # project and period (different wbs_code), triggering R5.
        pid = frame.iat[position, frame.columns.get_loc("project_id")]
        pidx = frame.iat[position, frame.columns.get_loc("period_index")]
        wbs_code = frame.iat[position, frame.columns.get_loc("wbs_code")]
        peers = frame[
            (frame["project_id"] == pid)
            & (frame["period_index"] == pidx)
            & (frame["wbs_code"] != wbs_code)
        ]
        if len(peers):
            frame.iat[position, frame.columns.get_loc(field)] = peers.iloc[0]["wbs_code"]
        return
    elif action == "set_future_date":
        # Set period_date beyond the series' latest date, triggering R10.
        pid = frame.iat[position, frame.columns.get_loc("project_id")]
        wbs = frame.iat[position, frame.columns.get_loc("wbs_code")]
        series = pristine[
            (pristine["project_id"] == pid) & (pristine["wbs_code"] == wbs)
        ]
        max_date = pd.to_datetime(series["period_date"]).max()
        frame.iat[position, frame.columns.get_loc(field)] = (
            max_date + pd.Timedelta(days=365)
        )
        return
    else:  # pragma: no cover - the catalogue is closed
        raise ValueError(f"unknown action {action!r}")

    frame.iat[position, frame.columns.get_loc(field)] = value


def _raw_candidates(rule_id: str, context: pd.DataFrame) -> list[int]:
    """Positions in ``context`` where ``rule_id`` can actually be triggered."""
    if rule_id == "R5":
        sizes = context.groupby("period_index")["wbs_code"].transform("size")
        return [int(i) for i in context.index[sizes >= 2]]
    if rule_id == "R10":
        latest = context["period_index"].max()
        return [int(i) for i in context.index[context["period_index"] < latest]]
    if rule_id == "R7":
        sizes = context.groupby("wbs_code")["period_index"].transform("size")
        return [int(i) for i in context.index[sizes >= 2]]
    return [int(i) for i in context.index]


def _inject_defects(
    frame: pd.DataFrame, per_rule: int, rng: np.random.Generator
) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    """Inject labelled raw-tier defects, one isolated context per defect.

    Returns:
        tuple: ``(context_frames, ground_truth)``.
    """
    pristine = frame.reset_index(drop=True).copy()
    pristine["wbs_code"] = pristine["wbs_code"].astype(str)
    pristine["period_date"] = pd.to_datetime(pristine["period_date"], errors="coerce")
    projects = pristine["project_id"].dropna().unique().tolist()

    contexts: list[pd.DataFrame] = []
    truth_rows: list[dict] = []

    for rule_id, field, anomaly_type, action in RAW_DEFECT_CATALOGUE:
        scope = RAW_CONTEXT[rule_id]
        for _ in range(per_rule):
            if scope == "row":
                context = pristine.iloc[[int(rng.integers(0, len(pristine)))]]
            elif scope == "series":
                project = projects[int(rng.integers(0, len(projects)))]
                subset = pristine[pristine["project_id"] == project]
                code = subset["wbs_code"].unique()[
                    int(rng.integers(0, subset["wbs_code"].nunique()))
                ]
                context = subset[subset["wbs_code"] == code]
            else:  # project
                project = projects[int(rng.integers(0, len(projects)))]
                context = pristine[pristine["project_id"] == project]
            context = context.reset_index(drop=True)

            candidates = _raw_candidates(rule_id, context)
            position = int(candidates[int(rng.integers(0, len(candidates)))])

            defect_frame = context.copy()
            defect_frame["period_date"] = defect_frame["period_date"].astype(object)
            _apply_defect(defect_frame, context, position, field, action, rng)
            after = defect_frame.iloc[position].to_dict()

            truth_rows.append(
                {
                    "defect_id": f"D{len(truth_rows) + 1:04d}",
                    "tier": "raw",
                    "record_key": (
                        f"{after['project_id']}|{after['wbs_code']}|"
                        f"{after['period_index']}"
                    ),
                    "project_id": after["project_id"],
                    "field": field,
                    "rule_id": rule_id,
                    "anomaly_type": anomaly_type,
                    "action": action,
                    "original_value": context.iloc[position][field]
                    if field in context.columns else None,
                    "defective_value": after.get(field),
                }
            )
            contexts.append(defect_frame)

    return contexts, pd.DataFrame(truth_rows)


# --------------------------------------------------------------------------
# Derived tier (project-period): R8, R9, R13, R14 - 4 rules.
# --------------------------------------------------------------------------

#: Derived-tier defect catalogue, on the cumulative project-period contract.
DERIVED_DEFECT_CATALOGUE = [
    ("R8",  "actual_date", "date_ordering_violation", "set_date_back"),
    ("R9",  "actual_cost", "cumulative_decrease",     "reduce_actual"),
    ("R13", "actual_cost", "budget_overrun",          "overrun_budget"),
    ("R14", "actual_cost", "progress_spend_mismatch", "outrun_progress"),
]

#: R8 and R9 need the project's period sequence; R13 and R14 are per-record.
DERIVED_CONTEXT = {"R8": "project", "R9": "project", "R13": "row", "R14": "row"}


def _derived_prev(pristine: pd.DataFrame, field: str) -> pd.Series:
    """Return each row's previous-period value for ``field``, by project."""
    order = _natural_order(pristine["time_period"])
    work = pristine.assign(_order=order).sort_values(
        ["project_id", "_order"], kind="stable"
    )
    return work.groupby("project_id")[field].shift(1)


def _natural_order(periods: pd.Series) -> list[tuple]:
    """Natural sort keys so ``Month-10`` follows ``Month-2``."""
    keys = []
    for label in periods:
        text = str(label)
        prefix, separator, number = text.rpartition("-")
        keys.append((prefix, int(number), "") if separator and number.isdigit()
                    else (text, 0, ""))
    return keys


def _derived_candidates(action: str, pristine: pd.DataFrame) -> list[int]:
    """Positions eligible for a given derived-tier defect."""
    prev_date = pd.to_datetime(_derived_prev(pristine, "actual_date"), errors="coerce")
    prev_actual = pd.to_numeric(_derived_prev(pristine, "actual_cost"), errors="coerce")
    budget = pd.to_numeric(pristine["pmb_budget"], errors="coerce")
    progress = pd.to_numeric(pristine["progress_pct"], errors="coerce")

    if action == "set_date_back":
        mask = prev_date.notna()
    elif action == "reduce_actual":
        mask = prev_actual > 0
    elif action == "overrun_budget":
        mask = budget > 0
    elif action == "outrun_progress":
        mask = (budget > 0) & (progress > 0)
    else:  # pragma: no cover - the catalogue is closed
        raise ValueError(f"unknown action {action!r}")

    return [int(i) for i in pristine.index[mask.fillna(False)]]


def _apply_derived_defect(
    frame: pd.DataFrame,
    pristine: pd.DataFrame,
    position: int,
    field: str,
    action: str,
) -> None:
    """Apply one controlled derived-tier defect to one row of ``frame``, in place."""
    if action == "set_date_back":
        prev_date = _derived_prev(pristine, "actual_date").loc[position]
        frame.iat[position, frame.columns.get_loc(field)] = (
            pd.to_datetime(prev_date) - pd.Timedelta(days=1)
        )
        return

    budget = float(pd.to_numeric(pristine.iat[position, pristine.columns.get_loc("pmb_budget")]))
    progress = float(
        pd.to_numeric(pristine.iat[position, pristine.columns.get_loc("progress_pct")])
    )

    if action == "reduce_actual":
        prev_actual = float(_derived_prev(pristine, "actual_cost").loc[position])
        value = round(prev_actual * 0.5, 2)
    elif action == "overrun_budget":
        # Strictly above the 3x threshold R13 enforces.
        value = round(budget * 3.5, 2)
    elif action == "outrun_progress":
        # Above the expected spend plus the 20% tolerance R14 enforces, while
        # staying below the 3x that R13 enforces so the defect is attributable
        # to R14.
        expected = budget * (progress / 100.0)
        value = round(expected * 1.5, 2)
    else:  # pragma: no cover - the catalogue is closed
        raise ValueError(f"unknown action {action!r}")

    frame.iat[position, frame.columns.get_loc(field)] = value


def _inject_derived_defects(
    derived: pd.DataFrame, per_rule: int, rng: np.random.Generator
) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    """Inject labelled derived-tier defects, one isolated context per defect."""
    pristine = derived.reset_index(drop=True).copy()
    pristine["actual_date"] = pd.to_datetime(pristine["actual_date"], errors="coerce")
    at_fault = known_derived_defects(pristine)
    projects = pristine["project_id"].dropna().unique().tolist()

    contexts: list[pd.DataFrame] = []
    truth_rows: list[dict] = []

    for rule_id, field, anomaly_type, action in DERIVED_DEFECT_CATALOGUE:
        injected = 0
        attempts = 0
        while injected < per_rule and attempts < per_rule * 20:
            attempts += 1
            if DERIVED_CONTEXT[rule_id] == "row":
                context = pristine.iloc[[int(rng.integers(0, len(pristine)))]]
            else:
                project = projects[int(rng.integers(0, len(projects)))]
                context = pristine[pristine["project_id"] == project]
            context = context.reset_index(drop=True)

            candidates = _derived_candidates(action, context)
            if not candidates:
                continue
            position = int(candidates[int(rng.integers(0, len(candidates)))])

            row = context.iloc[position]
            if (f"{row['project_id']}|{row['time_period']}", rule_id) in at_fault:
                continue

            defect_frame = context.copy()
            defect_frame["actual_date"] = defect_frame["actual_date"].astype(object)
            _apply_derived_defect(defect_frame, context, position, field, action)
            after = defect_frame.iloc[position].to_dict()

            truth_rows.append(
                {
                    "defect_id": f"X{injected + 1:04d}-{rule_id}",
                    "tier": "derived",
                    "record_key": f"{after['project_id']}|{after['time_period']}",
                    "project_id": after["project_id"],
                    "field": field,
                    "rule_id": rule_id,
                    "anomaly_type": anomaly_type,
                    "action": action,
                    "original_value": row.get(field),
                    "defective_value": after.get(field),
                }
            )
            contexts.append(defect_frame)
            injected += 1

    return contexts, pd.DataFrame(truth_rows)
