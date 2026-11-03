"""Measured evaluation: every figure the reports quote is computed here.

Detection completeness is scored **per injected defect**, not per record.  The
two differ for a real reason: renaming one record's ``project_name`` breaks the
one-name-per-project rule (R6) for *every* record in that project, so a single
injected defect legitimately produces many findings.  Scoring per record would
either credit the system for cascade findings or punish it for them; scoring per
defect asks the only question that matters - "was the defect I planted found?"
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..engine.validator import Validator
from ..pipeline.runner import DataPipeline
from .impact import impact_quantification


@dataclass
class Evaluation:
    """Every measured result, with nothing hand-entered."""

    dataset: dict = field(default_factory=dict)
    detection: dict = field(default_factory=dict)
    false_positives: dict = field(default_factory=dict)
    multi_mode: dict = field(default_factory=dict)
    performance: dict = field(default_factory=dict)
    dimensions: dict = field(default_factory=dict)
    rules_observed: dict = field(default_factory=dict)
    impact: dict = field(default_factory=dict)


def evaluate(raw: pd.DataFrame, derived: pd.DataFrame, fixtures) -> Evaluation:
    """Run the full measured evaluation.

    Args:
        raw: Real WBS-level dataset.
        derived: Real derived project-level dataset.
        fixtures: Derived test sets from :mod:`data_quality.fixtures.builder`.

    Returns:
        Evaluation: Every measured figure the reports cite.
    """
    import time

    validator = Validator()
    evaluation = Evaluation()

    # -- dataset facts ---------------------------------------------------
    evaluation.dataset = {
        "raw_records": len(raw),
        "derived_records": len(derived),
        "projects": int(raw["project_id"].nunique()),
        "project_ids": sorted(raw["project_id"].unique().tolist()),
        "wbs_codes": int(raw["wbs_code"].astype(str).nunique()),
        "periods": int(raw["period_index"].nunique()),
        "raw_fields": list(raw.columns),
        "derived_fields": list(derived.columns),
    }

    # -- real-data findings (Chapter 6, Table 6.1) ------------------------
    real_result = validator.validate(raw, tier="raw")
    derived_result = validator.validate(derived, tier="derived")
    evaluation.rules_observed = {
        "raw": real_result.findings_by_rule(),
        "derived": derived_result.findings_by_rule(),
    }
    evaluation.dataset["raw_invalid"] = real_result.invalid_records
    evaluation.dataset["raw_findings"] = real_result.counts["total_findings"]
    evaluation.dataset["derived_invalid"] = derived_result.invalid_records
    evaluation.dataset["derived_findings"] = (
        derived_result.counts["total_findings"]
    )

    # -- detection completeness (Section 5.9) ------------------------------
    # Defects are injected one at a time, each into an isolated copy of its
    # record's context (the row, its WBS series, or its project), on the tier
    # whose contract carries the columns the rule reads.  Validating each
    # context separately stops two defects from masking each other, so a
    # correctly implemented rule is never recorded as a miss for a reason
    # unrelated to the rule.
    observed: set[tuple[str, str]] = set()
    validated_records = 0
    produced_findings = 0
    for defect_frame in fixtures.defects:
        result = validator.validate(defect_frame, tier="raw")
        observed |= {(f.record_key, f.rule_id) for f in result.all_findings}
        validated_records += result.total_records
        produced_findings += result.counts["total_findings"]

    frames = [fixtures.ground_truth]
    if fixtures.derived_defects is not None and len(fixtures.derived_defects):
        for defect_frame in fixtures.derived_defects:
            result = validator.validate(defect_frame, tier="derived")
            observed |= {(f.record_key, f.rule_id) for f in result.all_findings}
            validated_records += result.total_records
            produced_findings += result.counts["total_findings"]
        frames.append(fixtures.derived_ground_truth)

    truth = pd.concat(frames, ignore_index=True)
    truth["observed"] = [
        (row.record_key, row.rule_id) in observed for row in truth.itertuples()
    ]
    hits = int(truth["observed"].sum())
    total = int(len(truth))

    per_tier = {}
    for tier_name, subset in truth.groupby("tier"):
        tier_hits = int(subset["observed"].sum())
        per_tier[tier_name] = {
            "injected": int(len(subset)),
            "detected": tier_hits,
            "completeness_pct": round(tier_hits / len(subset) * 100.0, 2),
        }

    evaluation.detection = {
        "injected": total,
        "detected": hits,
        "missed": total - hits,
        "completeness_pct": round(hits / total * 100.0, 2) if total else 0.0,
        "total_records_validated": validated_records,
        "total_findings": produced_findings,
        "by_rule_injected": truth["rule_id"].value_counts().to_dict(),
        "by_rule_detected": truth[truth["observed"]]["rule_id"].value_counts().to_dict(),
        "per_tier": per_tier,
        "missed_detail": truth[~truth["observed"]][
            ["defect_id", "tier", "rule_id", "field", "anomaly_type", "action"]
        ].to_dict("records"),
    }

    # -- false positives (Section 5.10) -----------------------------------
    clean = validator.validate(fixtures.clean, tier="raw")
    flagged = clean.invalid_records
    evaluation.false_positives = {
        "clean_records": clean.total_records,
        "flagged": flagged,
        "rate_pct": round(flagged / max(clean.total_records, 1) * 100.0, 2),
        "by_rule": clean.findings_by_rule(),
    }
    if fixtures.derived_clean is not None and len(fixtures.derived_clean):
        derived_clean = validator.validate(fixtures.derived_clean, tier="derived")
        evaluation.false_positives["derived"] = {
            "clean_records": derived_clean.total_records,
            "flagged": derived_clean.invalid_records,
            "rate_pct": round(
                derived_clean.invalid_records
                / max(derived_clean.total_records, 1) * 100.0,
                2,
            ),
        }

    # -- multi-mode consistency (Section 5.6) ------------------------------
    batch = DataPipeline().process_batch(fixtures.regression, tier="raw")
    incremental = DataPipeline().process_incremental(fixtures.regression, tier="raw")
    same = (
        batch["by_rule"] == incremental["by_rule"]
        and batch["invalid_records"] == incremental["invalid_records"]
    )
    evaluation.multi_mode = {
        "records": batch["total_records"],
        "batch_invalid": batch["invalid_records"],
        "incremental_invalid": incremental["invalid_records"],
        "batch_by_rule": batch["by_rule"],
        "incremental_by_rule": incremental["by_rule"],
        "consistent": bool(same),
        "consistency_pct": 100.0 if same else 0.0,
    }

    # -- performance (Section 5.7) ----------------------------------------
    started = time.perf_counter()
    DataPipeline().process_batch(raw, tier="raw")
    raw_seconds = time.perf_counter() - started

    started = time.perf_counter()
    DataPipeline().process_incremental(fixtures.incremental, tier="raw")
    incr_seconds = time.perf_counter() - started

    evaluation.performance = {
        "batch_records": len(raw),
        "batch_seconds": round(raw_seconds, 3),
        "incremental_records": len(fixtures.incremental),
        "incremental_seconds": round(incr_seconds, 3),
    }

    # -- dimension scores (Table 3.2, Table 6.2) --------------------------
    from ..pipeline.quality import TARGETS, score_dimensions

    raw_scores = score_dimensions(raw, tier="raw")
    derived_scores = score_dimensions(derived, tier="derived")
    evaluation.dimensions = {
        "targets": TARGETS,
        "raw": raw_scores,
        "derived": derived_scores,
        "raw_met": {d: raw_scores[d] >= TARGETS[d] for d in TARGETS},
    }

    # -- impact of detected inconsistencies (Section 3.6.8, Objective 2) ---
    evaluation.impact = impact_quantification(
        derived, derived_result.invalid_record_keys
    )

    return evaluation
