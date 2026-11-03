"""
Live validation API (Section 4.6).

Four endpoints, deliberately separated so that querying never mutates state:

POST /validate
    Validate a record or batch against the same contract objects used by the
    batch engine.

GET /status
    Return validation counters without triggering validation.

GET /flagged
    Return the flagged-records log without re-validating.

GET /health
    Return a liveness indicator.

HTTP semantics follow Table 4.3:

======  =====================================  ===========
Status  Meaning                                Action
======  =====================================  ===========
200     Clean record or batch                  accepted
422     Structural validation failure          rejected
202     Domain anomaly requiring review        quarantined
======  =====================================  ===========

A single submission may generate several findings. The response reports the
most severe outcome. Structural failures are rejected because the record
cannot be meaningfully validated; domain anomalies are quarantined for review.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, make_response, request

from ..engine.validator import Validator

#: Severity order used to identify the most severe finding.
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

#: Rules that render a record structurally unusable and therefore rejected.
_REJECT_RULES = {"R1", "R2", "R12"}

#: Machine-readable error identifiers for RFC 9457 responses.
ERROR_CODES = {
    "R1": "missing_required_field",
    "R2": "unexpected_data_type",
    "R3": "invalid_period_index",
    "R4": "value_outside_permitted_range",
    "R5": "duplicate_composite_key",
    "R6": "inconsistent_project_name",
    "R7": "inconsistent_wbs_description",
    "R8": "date_ordering_violation",
    "R9": "cumulative_decrease",
    "R10": "date_outside_project_window",
    "R11": "source_file_mismatch",
    "R12": "missing_wbs_description",
    "R13": "budget_overrun",
    "R14": "progress_mismatch",
}

#: Concise human-readable titles for RFC 9457 responses.
RULE_TITLES = {
    "R1": "Required field missing",
    "R2": "Unexpected data type",
    "R3": "Invalid period index",
    "R4": "Value outside permitted range",
    "R5": "Duplicate composite key",
    "R6": "Inconsistent project name",
    "R7": "Inconsistent WBS description",
    "R8": "Out-of-order period date",
    "R9": "Cumulative value decreased",
    "R10": "Date outside project window",
    "R11": "Source file mismatch",
    "R12": "Missing WBS description",
    "R13": "Budget overrun",
    "R14": "Spend outruns reported progress",
}

BASE_ERROR_URL = "https://data-quality-dashboard.example/errors"


def problem_details(
    status: int,
    problem_type: str,
    title: str,
    detail: str,
    rule: str | None = None,
    record_key: str | dict | None = None,
):
    """Serialise an error response conforming to RFC 9457."""
    body = {
        "type": problem_type,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": "/validate",
    }

    if rule is not None:
        body["rule"] = rule

    if record_key is not None:
        body["record_key"] = record_key

    response = make_response(body, status)
    response.headers["Content-Type"] = "application/problem+json"
    return response


def create_app(validator: Validator | None = None) -> Flask:
    """Build the Flask application."""
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
                status=422,
                code="malformed_request",
                title="Malformed request",
                detail="Request body must contain valid JSON.",
            )

        tier = request.args.get("tier", "raw")
        records, is_batch = _as_frame(payload)

        if records is None:
            return _error(
                status=422,
                code="malformed_request",
                title="Malformed request",
                detail="Request body must be a record object or a list of record objects.",
            )

        result = app.config["VALIDATOR"].validate(records, tier=tier)
        findings = result.all_findings
        outcome, status_code = _classify(findings)

        counters = app.config["COUNTERS"]
        counters["total_submitted"] += len(records)
        counters[outcome] += len(records)

        for finding in findings:
            app.config["FLAGGED"].append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "tier": tier,
                    "record_key": finding.record_key,
                    "rule_id": finding.rule_id,
                    "field": finding.field,
                    "severity": finding.severity,
                    "error": ERROR_CODES.get(
                        finding.rule_id, "validation_failure"
                    ),
                    "description": finding.description,
                    "remediation": finding.remediation,
                }
            )

        response_body = {
            "status": outcome,
            "tier": tier,
            "records": len(records),
            "batch": is_batch,
            "valid_records": result.valid_records,
            "invalid_records": result.invalid_records,
            "total_findings": len(findings),
            "findings": [finding.to_dict() for finding in findings],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }

        if findings:
            most_severe = _most_severe_finding(findings)
            response_body.update(
                {
                    "type": f"{BASE_ERROR_URL}/{most_severe.rule_id.lower()}",
                    "title": RULE_TITLES.get(
                        most_severe.rule_id, "Validation failed"
                    ),
                    "detail": most_severe.description,
                    "instance": "/validate",
                    "rule": most_severe.rule_id,
                    "record_key": most_severe.record_key,
                }
            )

        response = make_response(response_body, status_code)

        if findings:
            response.headers["Content-Type"] = "application/problem+json"

        return response

    @app.route("/status", methods=["GET"])
    def status():
        """Return validation counters without mutating state."""
        return jsonify(
            {
                **app.config["COUNTERS"],
                "flagged_rows": len(app.config["FLAGGED"]),
            }
        )

    @app.route("/flagged", methods=["GET"])
    def flagged():
        """Return the flagged-records log, optionally filtered by rule."""
        rule_id = request.args.get("rule")
        rows = app.config["FLAGGED"]

        if rule_id:
            rows = [row for row in rows if row["rule_id"] == rule_id]

        return jsonify(
            {
                "count": len(rows),
                "flagged_records": rows,
            }
        )

    @app.route("/health", methods=["GET"])
    def health():
        """Return a liveness indicator."""
        return jsonify({"status": "ok"})

    return app


def _as_frame(payload: Any):
    """Convert a JSON payload into a DataFrame."""
    import pandas as pd

    if isinstance(payload, list):
        if not payload or not all(isinstance(row, dict) for row in payload):
            return None, True

        return pd.DataFrame(payload), True

    if isinstance(payload, dict):
        records = payload.get("records")

        if isinstance(records, list):
            if not records:
                return None, True

            return pd.DataFrame(records), True

        return pd.DataFrame([payload]), False

    return None, False


def _most_severe_finding(findings):
    """Return the most severe finding for response classification."""
    return min(
        findings,
        key=lambda finding: (
            _SEVERITY_RANK.get(finding.severity, 9),
            finding.rule_id,
        ),
    )


def _classify(findings) -> tuple[str, int]:
    """Classify a submission as accepted, rejected, or quarantined."""
    if not findings:
        return "accepted", 200

    most_severe = _most_severe_finding(findings)

    if most_severe.rule_id in _REJECT_RULES:
        return "rejected", 422

    return "quarantined", 202


def _error(
    status: int,
    code: str,
    title: str,
    detail: str,
):
    """Return an RFC 9457 response for a malformed request."""
    return problem_details(
        status=status,
        problem_type=f"{BASE_ERROR_URL}/{code}",
        title=title,
        detail=detail,
        rule=code,
        record_key=None,
    )
