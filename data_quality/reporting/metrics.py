"""
Evaluation metrics for Chapter 3, Section 3.6.4.

This module implements the formal definitions of detection completeness,
false positive rate, and precision as specified in the research design.

Metrics are computed against ground truth constructed per Section 3.6.3,
which comprises two strata:
1. Adjudicated naturally occurring violations
2. Synthetic defects injected with fixed random seed (42)
"""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ConfusionMatrix:
    """Confusion matrix components per Table 3.11."""
    tp: int = 0  # True positive: defective record correctly flagged
    fn: int = 0  # False negative: defective record not flagged
    fp: int = 0  # False positive: clean record incorrectly flagged
    tn: int = 0  # True negative: clean record correctly not flagged

    def total(self) -> int:
        """Total records evaluated."""
        return self.tp + self.fn + self.fp + self.tn

    def total_defective(self) -> int:
        """Total defective records in ground truth."""
        return self.tp + self.fn

    def total_clean(self) -> int:
        """Total clean records in ground truth."""
        return self.fp + self.tn


def detection_completeness(cm: ConfusionMatrix) -> float:
    """
    Detection completeness (recall/sensitivity) per Section 3.6.4.
    
    Measures the proportion of defective records correctly flagged.
    
    Formula: TP / (TP + FN)
    
    Args:
        cm: Confusion matrix with TP, FN, FP, TN counts.
    
    Returns:
        float: Detection completeness as a percentage (0-100).
               Returns 100.0 when no defective records exist.
    """
    defective = cm.total_defective()
    if defective == 0:
        return 100.0
    return (cm.tp / defective) * 100.0


def false_positive_rate(cm: ConfusionMatrix) -> float:
    """
    False positive rate per Section 3.6.4.
    
    Measures the proportion of clean records incorrectly flagged.
    
    Formula: FP / (FP + TN)
    
    Args:
        cm: Confusion matrix with TP, FN, FP, TN counts.
    
    Returns:
        float: False positive rate as a percentage (0-100).
               Returns 0.0 when no clean records exist.
    """
    clean = cm.total_clean()
    if clean == 0:
        return 0.0
    return (cm.fp / clean) * 100.0


def precision(cm: ConfusionMatrix) -> float:
    """
    Precision per Section 3.6.4.
    
    Supplementary measure combining detection performance and false-positive
    performance. Guards against over-flagging.
    
    Formula: TP / (TP + FP)
    
    Args:
        cm: Confusion matrix with TP, FN, FP, TN counts.
    
    Returns:
        float: Precision as a percentage (0-100).
               Returns 100.0 when no records were flagged.
    """
    flagged = cm.tp + cm.fp
    if flagged == 0:
        return 100.0
    return (cm.tp / flagged) * 100.0


@dataclass
class RuleMetrics:
    """Per-rule evaluation metrics."""
    rule_id: str
    confusion_matrix: ConfusionMatrix
    detection_completeness: float
    false_positive_rate: float
    precision: float


def compute_rule_metrics(
    rule_id: str,
    true_positives: int,
    false_negatives: int,
    false_positives: int,
    true_negatives: int,
) -> RuleMetrics:
    """
    Compute evaluation metrics for a single rule.
    
    Args:
        rule_id: Rule identifier (e.g., "R1", "R9").
        true_positives: Count of defective records correctly flagged.
        false_negatives: Count of defective records not flagged.
        false_positives: Count of clean records incorrectly flagged.
        true_negatives: Count of clean records correctly not flagged.
    
    Returns:
        RuleMetrics: Computed metrics for the rule.
    """
    cm = ConfusionMatrix(
        tp=true_positives,
        fn=false_negatives,
        fp=false_positives,
        tn=true_negatives,
    )
    return RuleMetrics(
        rule_id=rule_id,
        confusion_matrix=cm,
        detection_completeness=detection_completeness(cm),
        false_positive_rate=false_positive_rate(cm),
        precision=precision(cm),
    )


def aggregate_metrics(rule_metrics_list: List[RuleMetrics]) -> RuleMetrics:
    """
    Aggregate metrics across rules using micro-averaging per Section 3.6.4.
    
    Micro-averaging sums TP, FN, FP, TN across rules before computing metrics,
    weighting each rule by the volume of records to which it applies.
    
    Args:
        rule_metrics_list: List of per-rule metrics.
    
    Returns:
        RuleMetrics: Aggregated metrics with rule_id="AGGREGATE".
    """
    total_cm = ConfusionMatrix(
        tp=sum(m.confusion_matrix.tp for m in rule_metrics_list),
        fn=sum(m.confusion_matrix.fn for m in rule_metrics_list),
        fp=sum(m.confusion_matrix.fp for m in rule_metrics_list),
        tn=sum(m.confusion_matrix.tn for m in rule_metrics_list),
    )
    return RuleMetrics(
        rule_id="AGGREGATE",
        confusion_matrix=total_cm,
        detection_completeness=detection_completeness(total_cm),
        false_positive_rate=false_positive_rate(total_cm),
        precision=precision(total_cm),
    )


@dataclass
class LatencyMetrics:
    """Latency measurement per Table 3.11."""
    mean_ms: float
    median_ms: float
    p95_ms: float
    batch_size: int
    mode: str  # "batch", "incremental", or "api"
    repetitions: int


def format_metrics_report(rule_metrics: List[RuleMetrics]) -> str:
    """
    Format evaluation metrics as a readable report.
    
    Args:
        rule_metrics: List of per-rule metrics.
    
    Returns:
        str: Formatted report with per-rule and aggregate metrics.
    """
    lines = [
        "Evaluation Metrics Report (Chapter 3, Section 3.6.4)",
        "=" * 70,
        "",
        "Per-Rule Metrics:",
        "-" * 70,
        f"{'Rule':<8} {'TP':>6} {'FN':>6} {'FP':>6} {'TN':>6} "
        f"{'Detection %':>12} {'FPR %':>10} {'Precision %':>12}",
        "-" * 70,
    ]
    
    for m in sorted(rule_metrics, key=lambda x: x.rule_id):
        if m.rule_id == "AGGREGATE":
            continue
        lines.append(
            f"{m.rule_id:<8} {m.confusion_matrix.tp:>6} "
            f"{m.confusion_matrix.fn:>6} {m.confusion_matrix.fp:>6} "
            f"{m.confusion_matrix.tn:>6} {m.detection_completeness:>11.2f}% "
            f"{m.false_positive_rate:>9.2f}% {m.precision:>11.2f}%"
        )
    
    # Add aggregate row
    agg = aggregate_metrics(rule_metrics)
    lines.append("-" * 70)
    lines.append(
        f"{agg.rule_id:<8} {agg.confusion_matrix.tp:>6} "
        f"{agg.confusion_matrix.fn:>6} {agg.confusion_matrix.fp:>6} "
        f"{agg.confusion_matrix.tn:>6} {agg.detection_completeness:>11.2f}% "
        f"{agg.false_positive_rate:>9.2f}% {agg.precision:>11.2f}%"
    )
    lines.append("=" * 70)
    
    return "\n".join(lines)
