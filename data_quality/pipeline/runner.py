"""
The pipeline: batch and incremental modes over one validator.

Dual-mode consistency is enforced structurally rather than by convention.
:class:`DataPipeline` holds a single :class:`~dqd.engine.validator.Validator`
instance and every mode routes through it, so a record cannot be accepted in one
mode and rejected in another.  The regression test in
``tests/test_dual_mode.py`` asserts this rather than assuming it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd

from ..engine.validator import ValidationResult, Validator
from .quality import TARGETS, score_dimensions

Mode = Literal["batch", "incremental"]


class DataPipeline:
    """Validate records in batch or incremental mode."""

    def __init__(self) -> None:
        self.validator = Validator()
        self.mode: Mode | None = None
        #: Records accepted so far, used as history for incremental R9/R13/R14.
        self.store: pd.DataFrame | None = None
        self.history: list[dict] = []

    # -- batch ------------------------------------------------------------

    def process_batch(self, df: pd.DataFrame, tier: str = "raw") -> dict:
        """Validate a complete dataset in one pass.

        Args:
            df: The full dataset.
            tier: ``"raw"`` or ``"derived"``.

        Returns:
            dict: Result payload including counts, scores and findings.
        """
        self.mode = "batch"
        result = self.validator.validate(df, tier=tier)
        payload = self._payload(result, tier, mode="batch")
        payload["dimensions"] = score_dimensions(df, tier=tier)
        self.store = df.copy()
        self.history.append(self._history_entry(payload))
        return payload

    # -- incremental ------------------------------------------------------

    def process_incremental(
        self,
        new_records: pd.DataFrame,
        tier: str = "raw",
        existing: pd.DataFrame | None = None,
    ) -> dict:
        """Validate newly arriving records against the same contract.

        Prior records are supplied as history so the cumulative rules (R9, R13,
        R14) judge the project's running position rather than a single period in
        isolation.  Only findings landing on the new rows are returned.

        Args:
            new_records: Newly arrived records.
            tier: ``"raw"`` or ``"derived"``.
            existing: Prior records of the same tier.  Defaults to whatever the
                pipeline has already seen.

        Returns:
            dict: Result payload including counts, scores and findings.
        """
        self.mode = "incremental"
        history = existing if existing is not None else self.store

        if history is not None and tier == "derived" and "time_period" in new_records:
            # A derived frame carries period *movements*, so a later arrival is
            # a new period rather than a restatement of an old one.
            history = None

        result = self.validator.validate(new_records, tier=tier, existing=history)
        payload = self._payload(result, tier, mode="incremental")
        payload["dimensions"] = score_dimensions(new_records, tier=tier)
        payload["used_history"] = history is not None and len(history) > 0

        if self.store is None:
            self.store = new_records.copy()
        elif len(new_records):
            self.store = pd.concat([self.store, new_records], ignore_index=True)

        self.history.append(self._history_entry(payload))
        return payload

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _payload(result: ValidationResult, tier: str, mode: Mode) -> dict:
        """Assemble the result payload shared by both modes."""
        counts = result.counts
        return {
            "mode": mode,
            "tier": tier,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            **counts,
            "by_rule": result.findings_by_rule(),
            "by_dimension": result.findings_by_dimension(),
            "targets": TARGETS,
            "findings": [f.to_dict() for f in result.all_findings],
        }

    def _history_entry(self, payload: dict) -> dict:
        return {
            "timestamp": payload["timestamp"],
            "mode": payload["mode"],
            "tier": payload["tier"],
            "records": payload["total_records"],
            "invalid_records": payload["invalid_records"],
            "overall": payload["dimensions"]["overall"],
        }