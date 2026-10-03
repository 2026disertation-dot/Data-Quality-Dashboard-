"""
Batch and incremental pipeline (Sections 4.5 and 4.6).

Both modes call the same :class:`~dqd.engine.validator.Validator`.  The only
difference is that incremental mode supplies prior records as history, which is
what lets R9 and the cumulative rules judge a new period against the running
totals that precede it.

That shared object is the architectural claim in Section 4.9: rules are defined
once, so a change to the contract propagates to every mode automatically and the
modes cannot drift apart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..engine.validator import Tier, ValidationResult, Validator
from .metrics import quality_dimensions, quality_score


@dataclass
class PipelineResult:
    """Outcome of one processing run in either mode."""

    mode: str
    tier: Tier
    total_records: int
    valid_records: int
    invalid_records: int
    total_findings: int
    by_rule: dict[str, int]
    by_dimension: dict[str, int]
    dimensions: dict[str, float]
    score: float
    elapsed_seconds: float
    findings: list[dict] = field(default_factory=list)
    processed_data: pd.DataFrame | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "mode": self.mode,
            "tier": self.tier,
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "total_findings": self.total_findings,
            "by_rule": self.by_rule,
            "by_dimension": self.by_dimension,
            "dimensions": self.dimensions,
            "score": self.score,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
        }


class Pipeline:
    """Process records in batch or incremental mode."""

    def __init__(self, validator: Validator | None = None) -> None:
        self.validator = validator or Validator()
        self.history: dict[str, pd.DataFrame] = {}

    # -- batch ------------------------------------------------------------

    def process_batch(self, df: pd.DataFrame, tier: Tier = "raw") -> PipelineResult:
        """Validate a complete dataset in a single pass.

        Batch mode does not pass history: the frame under validation *is* the
        history, so every cross-record rule sees its whole series at once.
        """
        started = time.perf_counter()
        result = self.validator.validate(df, tier=tier, existing=None)
        self.history[tier] = df.copy()
        return self._summarise("batch", tier, result, started, df)

    # -- incremental ------------------------------------------------------

    def process_incremental(
        self,
        df: pd.DataFrame,
        tier: Tier = "raw",
        use_history: bool = True,
    ) -> PipelineResult:
        """Validate newly arriving records against prior history.

        Args:
            df: The new records.
            tier: Contract tier to validate against.
            use_history: When True (the default) the previously processed
                records of the same tier are supplied to the cumulative rules.

        Returns:
            PipelineResult: Counts, findings and scores for the new records
            only.  Findings that belong to historical rows are never
            re-reported, so a repeated submission does not inflate the counts.
        """
        started = time.perf_counter()
        existing = self.history.get(tier) if use_history else None
        result = self.validator.validate(df, tier=tier, existing=existing)

        # Fold the new records into history so the next incremental call has
        # the running totals it needs.
        if existing is None or len(existing) == 0:
            self.history[tier] = df.copy()
        else:
            self.history[tier] = pd.concat([existing, df], ignore_index=True)

        return self._summarise("incremental", tier, result, started, df)

    def reset_history(self) -> None:
        """Forget all prior records."""
        self.history.clear()

    # -- shared -----------------------------------------------------------

    @staticmethod
    def _summarise(
        mode: str,
        tier: Tier,
        result: ValidationResult,
        started: float,
        frame: pd.DataFrame,
    ) -> PipelineResult:
        """Turn a validation result into a pipeline result with scores."""
        counts = result.counts
        dimensions = quality_dimensions(frame, result, tier)
        score = quality_score(dimensions)
        return PipelineResult(
            mode=mode,
            tier=tier,
            total_records=counts["total_records"],
            valid_records=counts["valid_records"],
            invalid_records=counts["invalid_records"],
            total_findings=counts["total_findings"],
            by_rule=result.findings_by_rule(),
            by_dimension=result.findings_by_dimension(),
            dimensions=dimensions,
            score=score,
            elapsed_seconds=time.perf_counter() - started,
            findings=[f.to_dict() for f in result.all_findings],
            processed_data=frame,
        )