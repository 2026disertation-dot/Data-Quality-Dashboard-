"""
Finding records and the shared vocabulary used across both contract tiers.

A *finding* is a single detected defect.  Every rule emits findings through the
same :class:`Finding` shape so that the batch engine, the incremental engine and
the live API can all return, serialise and count defects identically.

Counting semantics
------------------
Three counts are reported and they are **not** interchangeable:

``total_findings``
    Number of findings/events.  One record breaking four rules yields four
    findings.
``invalid_records``
    Number of *unique records* carrying at least one finding.
``valid_records``
    Total records minus the unique invalid records.

Deriving ``invalid_records`` from the finding count is what previously produced
negative valid counts (31 findings across 8 records reported as ``8 - 31``), so
the distinction is enforced here and asserted by the test suite.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

#: Data quality dimension assigned to each rule, per Table 3.2.
DIMENSIONS = ("completeness", "consistency", "accuracy", "integrity")

#: Severity attached to each rule, per Table 4.3.
#:
#: Severity is High where the defect prevents meaningful validation (R1, R2,
#: R12 - structural failures) or directly corrupts cumulative variance (R8, R9);
#: Medium otherwise.  Severity orders findings for display (see
#: :func:`_most_severe_finding`); it does not decide the HTTP outcome on its own.
#: Only the structural rules (R1, R2, R12) reject the record with 422; every
#: other finding, including the domain rules R8 and R9 whose severity is High,
#: quarantines the record with 202 (see the API section, Table 4.4).
RULE_SEVERITY = {
    "R1": "high",
    "R2": "high",
    "R3": "medium",
    "R4": "medium",
    "R5": "medium",
    "R6": "medium",
    "R7": "medium",
    "R8": "high",
    "R9": "high",
    "R10": "medium",
    "R11": "medium",
    "R12": "high",
    "R13": "medium",
    "R14": "medium",
}


def rule_severity(rule_id: str) -> str:
    """Return the severity declared for a rule in Table 4.3."""
    return RULE_SEVERITY.get(rule_id, "medium")


@dataclass(frozen=True)
class Finding:
    """
    One detected data quality defect.

    Attributes:
        rule_id: Stable rule identifier from Table 4.2 (e.g. ``"R9"``).
        dimension: Data quality dimension the rule belongs to.
        record_key: Composite key of the offending record, as a string.
        field: Column implicated, or ``"multiple"`` for a whole-record rule.
        severity: ``high``, ``medium`` or ``low``.
        description: Human-readable explanation of what is wrong.
        remediation: Suggested corrective action.
        detail: Optional structured payload for the API response.
    """

    rule_id: str
    dimension: str
    record_key: str
    field: str
    severity: str
    description: str
    remediation: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return asdict(self)


def count_invalid_records(findings: Sequence[Finding]) -> int:
    """
    Count the unique records that carry at least one finding.

    Args:
        findings: Findings to attribute to records.

    Returns:
        int: Number of distinct records referenced.
    """
    return len({f.record_key for f in findings})


def summarise_counts(findings: Iterable[Finding], total_records: int) -> dict[str, int]:
    """
    Build the record-count summary for a validation result.

    Args:
        findings: Findings produced by the engine.
        total_records: Number of records validated.

    Returns:
        dict: ``total_records``, ``invalid_records``, ``valid_records`` and
        ``total_findings``.  The counts are clamped so ``valid_records`` can
        never be negative and the two always sum to the total.
    """
    findings = list(findings)
    invalid = count_invalid_records(findings)
    invalid = min(invalid, total_records)
    return {
        "total_records": total_records,
        "invalid_records": invalid,
        "valid_records": total_records - invalid,
        "total_findings": len(findings),
    }