"""Live API tests: Table 4.3 status semantics and the flagged-records table."""

import pandas as pd
import pytest

from dqd.api.server import create_app


@pytest.fixture()
def client(validator):
    return create_app(validator).test_client()


@pytest.fixture()
def good_record(raw_data):
    return raw_data.iloc[[0]].to_dict("records")[0]


def test_health(client):
    assert client.get("/health").status_code == 200


def test_clean_record_accepted_with_200(client, good_record):
    response = client.post("/validate", json=good_record)
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "accepted"
    assert body["total_findings"] == 0


def test_missing_required_field_rejected_with_422(client, good_record):
    bad = dict(good_record, project_name=None)
    response = client.post("/validate", json=bad)
    assert response.status_code == 422
    body = response.get_json()
    assert body["status"] == "rejected"
    assert any(f["rule_id"] == "R1" for f in body["findings"])


def test_unreadable_date_rejected_with_422(client, good_record):
    bad = dict(good_record, period_date="not-a-date")
    response = client.post("/validate", json=bad)
    assert response.status_code == 422
    assert any(f["rule_id"] == "R2" for f in response.get_json()["findings"])


def test_negative_value_quarantined_with_202(client, good_record):
    bad = dict(good_record, ac_cum=-500.0)
    response = client.post("/validate", json=bad)
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "quarantined"
    assert any(f["rule_id"] == "R4" for f in body["findings"])


def test_batch_submission_accepted(client, raw_data):
    records = raw_data.iloc[:5].to_dict("records")
    response = client.post("/validate", json=records)
    assert response.status_code in (200, 202)
    body = response.get_json()
    assert body["batch"] is True
    assert body["records"] == 5


def test_malformed_json_rejected(client):
    response = client.post(
        "/validate", data="not json", content_type="application/json"
    )
    assert response.status_code == 422
    assert response.get_json()["error"] == "malformed_request"


def test_status_does_not_validate(client, good_record):
    """Querying status must not mutate state (Section 4.7)."""
    before = client.get("/status").get_json()
    client.get("/status")
    assert client.get("/status").get_json() == before


def test_flagged_records_are_captured(client, good_record):
    client.post("/validate", json=dict(good_record, ac_cum=-1.0))
    body = client.get("/flagged").get_json()
    assert body["count"] >= 1
    entry = body["flagged_records"][0]
    assert entry["rule_id"] == "R4"
    assert entry["error"] == "out_of_bounds_value"
    assert entry["remediation"]


def test_flagged_can_be_filtered_by_rule(client, good_record):
    client.post("/validate", json=dict(good_record, ac_cum=-1.0))
    client.post("/validate", json=dict(good_record, project_name=None))
    only_r4 = client.get("/flagged?rule=R4").get_json()
    assert all(r["rule_id"] == "R4" for r in only_r4["flagged_records"])


def test_response_time_is_measured(client, good_record):
    """The API reports its own latency rather than asserting a figure."""
    body = client.post("/validate", json=good_record).get_json()
    assert isinstance(body["elapsed_ms"], (int, float))
    assert body["elapsed_ms"] >= 0
