"""
Quality dimension scores (Table 3.2).

Each dimension is operationalised as a bounded percentage so the four are
comparable and always land inside [0, 100].  The operational definitions match
Table 3.2:

Completeness
    Share of required field values that are present.
Consistency
    Share of records whose composite key is unique.
Accuracy
    Share of values inside their legitimate range.
Integrity
    Share of records satisfying the logical constraints.

A composite overall score is deliberately *not* reported as the headline.
Averaging the four hides the difference between a missing value and a broken
constraint, which is the distinction a practitioner acts on.
"""

from __future__ import annotations

import pandas as pd

from ..contracts.raw import RAW_CUMULATIVE_COLUMNS, RAW_KEY
from ..engine.validator import Validator, normalise_types

#: Target thresholds from Table 3.2.
TARGETS = {
    "completeness": 98.0,
    "consistency": 99.0,
    "accuracy": 97.0,
    "integrity": 90.0,
}

WEIGHTS = {
    "completeness": 0.30,
    "consistency": 0.25,
    "accuracy": 0.25,
    "integrity": 0.20,
}


def _pct(numerator: float, denominator: float) -> float:
    """Return a bounded percentage, treating an empty frame as perfect."""
    if denominator <= 0:
        return 100.0
    return round(max(0.0, min(100.0, (numerator / denominator) * 100.0)), 2)


def score_dimensions(
    df: pd.DataFrame, tier: str = "raw", required: list[str] | None = None
) -> dict[str, float]:
    """Compute the four dimension scores for a frame.

    Args:
        df: Frame to score.
        tier: Contract tier, used to pick the right key and money columns.
        required: Required field names for the completeness check.

    Returns:
        dict: The four dimension scores plus ``overall``.
    """
    frame = normalise_types(df)
    total_rows = len(frame)

    if total_rows == 0:
        return {d: 100.0 for d in TARGETS} | {"overall": 100.0}

    # -- completeness ----------------------------------------------------
    if required is None:
        required = _required_for(tier)
    present = [c for c in required if c in frame.columns]
    if present:
        cells = total_rows * len(present)
        filled = int(frame[present].notna().sum().sum())
        # A text field holding only whitespace is as absent as a null.
        blank_text = sum(
            int(frame[c].astype(str).str.strip().eq("").sum()) for c in present
        )
        completeness = _pct(filled - blank_text, cells)
    else:
        completeness = 0.0

    # -- consistency -----------------------------------------------------
    key = [c for c in (RAW_KEY if tier == "raw" else ["project_id", "time_period"]) if c in frame.columns]
    if len(key) == 2:
        duplicates = int(frame.duplicated(subset=key).sum())
        consistency = _pct(total_rows - duplicates, total_rows)
    else:
        consistency = 100.0

    # -- accuracy --------------------------------------------------------
    money = _money_columns(tier, frame)
    if money:
        in_range = 0
        for column in money:
            values = pd.to_numeric(frame[column], errors="coerce")
            in_range += int((values >= 0).sum())
        accuracy = _pct(in_range, total_rows * len(money))
    else:
        accuracy = 100.0

    # -- integrity -------------------------------------------------------
    result = Validator().validate(df, tier=tier)
    integrity = _pct(total_rows - result.invalid_records, total_rows)

    scores = {
        "completeness": completeness,
        "consistency": consistency,
        "accuracy": accuracy,
        "integrity": integrity,
    }
    scores["overall"] = round(
        sum(scores[d] * WEIGHTS[d] for d in WEIGHTS), 2
    )
    return scores


def _required_for(tier: str) -> list[str]:
    from ..engine.validator import DERIVED_REQUIRED, RAW_REQUIRED

    return RAW_REQUIRED if tier == "raw" else DERIVED_REQUIRED


def _money_columns(tier: str, frame: pd.DataFrame) -> list[str]:
    if tier == "raw":
        return [c for c in RAW_CUMULATIVE_COLUMNS if c in frame.columns]
    return [
        c for c in ("pmb_budget", "actual_cost", "revenue_claimed") if c in frame.columns
    ]