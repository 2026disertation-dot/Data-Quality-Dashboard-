"""
Live Flask API exposing the validation engine (Section 4.7).

Three endpoints, deliberately separate so that querying never triggers
validation:

``POST /validate``
    Accept one record or a batch, validate synchronously against the *same*
    contract object the batch engine uses, and return a structured verdict.
``GET /status``
    Return submission counters without validating anything.
``GET /flagged``
    Return the flagged-records table without re-running validation.

HTTP status semantics (Table 4.3)
---------------------------------
``200``  the record is clean and may be written to the validated dataset
``422``  the record is rejected: a required field is missing or a value cannot
         be read as its declared type.  These are *malformed submissions* and
         should never enter the dataset.
``202``  the record is quarantined: it is well-formed but breaks a rule, so it
         is stored and flagged for review rather than rejected outright.

The split matters for an integrating system.  A 422 means "fix your client"; a
202 means "your payload was accepted, a human should look at it".

The API holds no validation logic of its own.  It converts JSON to a frame and
calls the same :class:`~dqd.engine.validator.Validator` that batch and
incremental mode use, which is what makes the dual-mode consistency claim in
Chapter 4 true rather than aspirational.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from flask import Flask, jsonify, request

from ..engine.findings import Finding
from ..engine.validator import Validator

#: Findings that mean "reject" (HTTP 422) rather than "quarantine" (HTTP 202).
REJECT_RULES = {"R1", "R2"}

#: Rule id to machine-readable error code (used in the flagged table).
ERROR_CODES = {
    "R1": "missing_required_field",
    "R2": "unexpected_data_type",
    "R3": "period_index_out_of_range",
    "R4": "out_of_bounds_value",
    "R5": "duplicate_record",
    "R6": "inconsistent_project_name",
    "R7": "inconsistent_wbs_description",
    "R8": "date_ordering_violation",
    "R9": "cumulative_decrease",
    "R10": "date_outside_window",
    "R11": "source_file_mismatch",
    "R12": "missing_wbs_description",
    "R13": "budget_overrun",
    "R14": "progress_mismatch",
}


def create_app(validator: Validator | None = None) -> Flask:
    """
    Build the Flask application.

    Args:
        validator: Validator to use.  A fresh one is created when omitted;
            tests inject their own so the outcome log can be isolated.

    Returns:
        Flask: The configured application.
    """
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    validator = validator or Validator()

    # Outcome log.  Held in memory because the study evaluates the API under
    # controlled submissions rather than as a deployed service; a real
    # deployment would write to a durable store.
    log: dict[str, Any] = {
        "total_submitted": 0,
        "accepted": 0,
        "rejected": 0,
        "quarantined": 0,
        "flagged_records": [],
    }

    @app.post("/validate")
    def validate():
        """Validate a submitted record or batch of records."""
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({
                "status": "rejected",
                "error": "malformed_request",
                "message": "Request body must be valid JSON",
            }), 422

        tier = request.args.get("tier", "raw")
        if tier not in ("raw", "derived"):
            return jsonify({
                "status": "rejected",
                "error": "unknown_tier",
                "message": f"Unknown tier '{tier}'; expected raw or derived",
            }), 422

        records = _extract_records(payload)
        if records is None:
            return jsonify({
                "status": "rejected",
                "error": "empty_submission",
                "message": "Submit a record object or a non-empty list",
            }), 422

        history = _history_from_payload(payload)

        try:
            frame = pd.DataFrame(records)
        except Exception as exc:  # pragma: no cover - defensive
            return jsonify({
                "status": "rejected",
                "error": "unreadable_submission",
                "message": str(exc),
            }), 422

        result = validator.validate(frame, tier=tier, existing=history)

        verdict, status_code = _classify(result.all_findings, len(records))
        log["total_submitted"] += len(records)
        log[verdict] += len(records)

        timestamp = datetime.now(timezone.utc).isoformat()
        for finding in result.all_findings:
            log["flagged_records"].append({
                "timestamp": timestamp,
                "tier": tier,
                "rule_id": finding.rule_id,
                "record_key": finding.record_key,
                "field": finding.field,
                "severity": finding.severity,
                "error": ERROR_CODES.get(finding.rule_id, "validation_failure"),
                "message": finding.description,
                "remediation": finding.remediation,
            })

        return jsonify({
            "status": verdict,
            "tier": tier,
            "records_submitted": len(records),
            "counts": result.counts,
            "by_rule": result.findings_by_rule(),
            "findings": [f.to_dict() for f in result.all_findings],
        }), status_code

    @app.get("/status")
    def status():
        """Return submission counters. Performs no validation."""
        return jsonify({
            "total_submitted": log["total_submitted"],
            "accepted": log["accepted"],
            "rejected": log["rejected"],
            "quarantined": log["quarantined"],
            "flagged_count": len(log["flagged_records"]),
        })

    @app.get("/flagged")
    def flagged():
        """Return the flagged-records table. Performs no validation."""
        return jsonify({"flagged_records": log["flagged_records"]})

    @app.get("/health")
    def health():
        """Liveness probe used by the test harness."""
        return jsonify({"status": "ok"})

    return app


def _extract_records(payload) -> list | None:
    """Pull the record list out of the three accepted payload shapes.

    A bare object, a bare list, or ``{"records": [...], "existing": [...]}``.
    The third shape lets a caller supply prior records so the cumulative rules
    see the same context incremental mode does.
    """
    if isinstance(payload, dict) and "records" in payload:
        records = payload["records"]
    elif isinstance(payload, list):
        records = payload
    else:
        records = [payload]

    if not isinstance(records, list) or not records:
        return None
    return records


def _history_from_payload(payload) -> pd.DataFrame | None:
    """Extract optional prior records supplied alongside a submission."""
    if isinstance(payload, dict) and payload.get("existing"):
        try:
            return pd.DataFrame(payload["existing"])
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _classify(findings: list[Finding], submitted: int) -> tuple[str, int]:
    """Map findings onto the Table 4.3 verdict and HTTP status.

    A single malformed field rejects the whole submission (422).  Otherwise any
    rule breach quarantines it (202).  A clean submission is accepted (200).
    """
    if not findings:
        return "accepted", 200
    if any(f.rule_id in REJECT_RULES for f in findings):
        return "rejected", 422
    return "quarantined", 202


#: Module-level app for ``flask run`` and WSGI servers.
app = create_app()