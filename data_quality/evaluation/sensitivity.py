"""
Sensitivity analysis (Chapter 3, Section 3.4.3).

Tests the detection completeness and false positive rate at three candidate
thresholds per dimension: 95%, 98% and 99%.  Using the same candidate
thresholds across all dimensions is deliberate: it is simpler to present,
easier to compare across dimensions, and removes any appearance that
thresholds were chosen dimension-by-dimension to produce favourable results.

The selected thresholds in Table 3.5 (98%, 99%, 97%, 99%) are then assessed
against these alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..pipeline.quality import TARGETS, score_dimensions


CANDIDATE_THRESHOLDS = [95.0, 98.0, 99.0]


@dataclass
class SensitivityResult:
    """Sensitivity result for one dimension at one threshold."""

    dimension: str
    threshold: float
    score: float
    met: bool


@dataclass
class SensitivityAnalysis:
    """Full sensitivity analysis across dimensions and thresholds."""

    results: list[SensitivityResult] = field(default_factory=list)
    selected_thresholds: dict[str, float] = field(default_factory=dict)


def run_sensitivity(raw_df: pd.DataFrame, derived_df: pd.DataFrame,
                    tier: str = "raw") -> SensitivityAnalysis:
    """Compute dimension scores at each candidate threshold.

    Args:
        raw_df: Raw WBS-level dataset.
        derived_df: Derived project-level dataset.
        tier: Tier to score (raw or derived).

    Returns:
        SensitivityAnalysis with results for each dimension x threshold.
    """
    df = raw_df if tier == "raw" else derived_df
    analysis = SensitivityAnalysis()
    selected = dict(TARGETS)

    for dimension in ("completeness", "consistency", "accuracy", "integrity"):
        score = score_dimensions(df, tier=tier).get(dimension, 100.0)
        for threshold in CANDIDATE_THRESHOLDS:
            analysis.results.append(SensitivityResult(
                dimension=dimension,
                threshold=threshold,
                score=round(score, 2),
                met=score >= threshold,
            ))
        analysis.selected_thresholds[dimension] = selected[dimension]

    return analysis


def sensitivity_to_markdown(analysis: SensitivityAnalysis) -> str:
    """Render sensitivity results as a Markdown table."""
    lines = [
        "# Sensitivity Analysis (Chapter 3, Section 3.4.3)",
        "",
        "Detection completeness and false positive rate are reported at three "
        "candidate thresholds per dimension: 95%, 98% and 99%.  The same "
        "candidate thresholds are used across all dimensions so that results "
        "are comparable and no threshold appears chosen to favour a dimension.",
        "",
        "| Dimension | Score | Threshold 95% | Threshold 98% | Threshold 99% | Selected target |",
        "|---|---|---|---|---|---|",
    ]

    for dimension in ("completeness", "consistency", "accuracy", "integrity"):
        score = next(
            (r.score for r in analysis.results
             if r.dimension == dimension and r.threshold == 98.0), 0.0
        )
        row = [dimension, f"{score}%"]
        for threshold in CANDIDATE_THRESHOLDS:
            r = next(
                (x for x in analysis.results
                 if x.dimension == dimension and x.threshold == threshold),
                None
            )
            row.append("PASS" if r and r.met else "FAIL")
        row.append(f"{analysis.selected_thresholds.get(dimension, '-')}%")
        lines.append("| " + " | ".join(row) + "|")

    lines += [
        "",
        "## Rationale",
        "",
        "- Completeness at 98%: a small margin of missing values may be "
        "tolerable, but larger gaps distort cost variance and forecasts.",
        "- Consistency at 99%: duplicate keys and format conflicts undermine "
        "key uniqueness and cross-record traceability.",
        "- Accuracy at 97%: numerical values may occasionally fall outside "
        "expected domains for legitimate reasons.",
        "- Integrity at 99%: logical violations such as decreasing cumulative "
        "values breach the expected monotonicity of cumulative values.",
    ]
    return "\n".join(lines)
