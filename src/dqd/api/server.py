"""
Live validation API (Section 4.7).

Three endpoints, deliberately separated so that querying never mutates state:

``POST /validate``
    Validate a record or batch against the same contract objects the batch
    engine uses.
``GET /status``
    Return counters without triggering validation.
``GET /flagged``
    Return the flagged-records table without re-validating.

HTTP semantics follow Table 4.3:

======  =======================================  ==========
Status  Meaning                                  Action
======  =======================================  ==========
200     Clean record                             accepted
422     Missing field or unexpected datatype     rejected
202     Out-of-bounds value or logical anomaly   quarantined
======  =======================================  ==========

A single submission can trip several rules.  The response reports the *most
severe* outcome, because a record missing a required field cannot be
meaningfully quarantined - it has to be rejected first.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request

from ..engine.validator import Validator

#: Severity order used to pick the reported outcome of a multi-rule failure.
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

#: Rule ids that mean "reject outright" rather than "quarantine".
_REJECT_RULES = {"R1", "R2", "R12"}

#: Rule id to machine-readable error code (Table 4.3 response body).
ERROR_CODES = {
    "R1": "missing_required_field",
    "R2": "unexpected_data_type",
    "R3": "out_of_bounds_value",
    "R4": "out_of_bounds_value",
    "R5": "duplicate_record",
    "R6": "inconsistent_project_name",
    "R7": "inconsistent_wbs_description",
    "R8": "date_ordering_violation",
    "R9": "cumulative_restatement",
    "R10": "date_outside_window",
    "R11": "source_file_mismatch",
    "R12": "missing_wbs_description",
    "R13": "budget_overrun",
    "R14": "progress_mismatch",
}


def create_app(validator: Validator | None = None) -> Flask:
    """Build the Flask application.

    Args:
        validator: Validator instance.  A default is created when omitted, but
            passing the *same* instance the batch engine uses is what guarantees
            the API and batch modes cannot diverge.

    Returns:
        Flask: The configured application.
    """
    app = Flask(__name__)
    app.config["VALIDATOR"] = validator or Validator()
    app.config["COUNTERS"] = {
        "total_submitted": 0,
        "accepted": 0,
        "rejected": 0,
        "quarantined": 0,
    }
    app.config["FLAGGED"] = []

    @app.route("/validate", methods=["POST"])
    def validate():
        """Validate a submitted record or batch against the shared contract."""
        started = time.perf_counter()
        payload = request.get_json(silent=True)

        if payload is None:
            return _error(
                "malformed_request", "Request body must be valid JSON", 422, started
            )

        tier = request.args.get("tier", "raw")
        records, is_list = _as_frame(payload)
        if records is None:
            return _error(
                "malformed_request",
                "Body must be a record object or a list of records",
                422,
                started,
            )

        result = app.config["VALIDATOR"].validate(records, tier=tier)
        findings = result.all_findings
        outcome, status_code = _classify(findings)

        counters = app.config["COUNTERS"]
        counters["total_submitted"] += len(records)
        counters[outcome] = counters.get(outcome, 0) + len(records)

        for finding in findings:
            app.config["FLAGGED"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "tier": tier,
                    "record_key": finding.record_key,
                    "rule_id": finding.rule_id,
                    "field": finding.field,
                    "severity": finding.severity,
                    "error": ERROR_CODES.get(finding.rule_id, "validation_failure"),
                    "description": finding.description,
                    "remediation": finding.remediation,
                }
            )

        return (
            jsonify(
                {
                    "status": outcome,
                    "tier": tier,
                    "records": len(records),
                    "batch": is_list,
                    "valid_records": result.valid_records,
                    "invalid_records": result.invalid_records,
                    "total_findings": len(findings),
                    "findings": [f.to_dict() for f in findings],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            ),
            status_code,
        )

    @app.route("/status", methods=["GET"])
    def status():
        """Return validation counters.  Read-only by construction."""
        return jsonify(
            {**app.config["COUNTERS"], "flagged_rows": len(app.config["FLAGGED"])}
        )

    @app.route("/flagged", methods=["GET"])
    def flagged():
        """Return the flagged-records table, optionally filtered by rule."""
        rule = request.args.get("rule")
        rows = app.config["FLAGGED"]
        if rule:
            rows = [r for r in rows if r["rule_id"] == rule]
        return jsonify({"count": len(rows), "flagged_records": rows})

    @app.route("/health", methods=["GET"])
    def health():
        """Liveness probe."""
        return jsonify({"status": "ok"})

    return app


def _as_frame(payload: Any):
    """Turn a JSON body into a DataFrame, reporting whether it was a list."""
    import pandas as pd

    if isinstance(payload, list):
        if not payload or not all(isinstance(r, dict) for r in payload):
            return None, True
        return pd.DataFrame(payload), True
    if isinstance(payload, dict):
        inner = payload.get("records")
        if isinstance(inner, list):
            return (pd.DataFrame(inner), True) if inner else (None, True)
        return pd.DataFrame([payload]), False
    return None, False


def _classify(findings) -> tuple[str, int]:
    """Return the most severe outcome and its HTTP status.

    Args:
        findings: All findings for the submission.

    Returns:
        tuple: ``(outcome, status_code)`` where outcome is ``accepted``,
        ``rejected`` or ``quarantined``.
    """
    if not findings:
        return "accepted", 200

    worst = min(findings, key=lambda f: (_SEVERITY_RANK.get(f.severity, 9), f.rule_id))
    if worst.rule_id in _REJECT_RULES:
        return "rejected", 422
    return "quarantined", 202


def _error(code: str, message: str, status: int, started: float):
    """Return a structured error response with a consistent shape."""
    return (
        jsonify(
            {
                "status": "rejected",
                "error": code,
                "message": message,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        ),
        status,
    )
