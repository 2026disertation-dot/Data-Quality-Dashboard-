"""Measured evaluation must match the targets the research sets.

Every assertion here is on a *measured* value produced by
:func:`dqd.reporting.evaluation.evaluate`.  If a figure is wrong the test fails;
nothing here restates a number that was typed in by hand.
"""

import pytest

#: Targets from Sections 5.7, 5.9 and 5.10.
DETECTION_TARGET = 95.0
FALSE_POSITIVE_TARGET = 5.0
PERFORMANCE_TARGET_SECONDS = 5.0


def test_dataset_facts_match_the_real_files(evaluation, raw_data, derived_data):
    dataset = evaluation.dataset
    assert dataset["raw_records"] == len(raw_data) == 2727
    assert dataset["derived_records"] == len(derived_data) == 76
    assert dataset["projects"] == raw_data["project_id"].nunique() == 8
    assert dataset["wbs_codes"] == raw_data["wbs_code"].astype(str).nunique() == 82
    assert dataset["periods"] == raw_data["period_index"].nunique() == 14


def test_raw_contract_has_the_ten_specified_fields(evaluation):
    assert len(evaluation.dataset["raw_fields"]) == 10
    assert {
        "project_id", "project_name", "source_file", "wbs_code",
        "wbs_description", "period_date", "period_index",
        "pv_cum", "ac_cum", "ev_cum",
    } <= set(evaluation.dataset["raw_fields"])


def test_derived_contract_has_the_eight_specified_fields(evaluation):
    assert len(evaluation.dataset["derived_fields"]) == 8


def test_detection_completeness_meets_target(evaluation):
    detection = evaluation.detection
    assert detection["injected"] == 250
    assert detection["completeness_pct"] >= DETECTION_TARGET
    assert detection["detected"] + detection["missed"] == detection["injected"]


def test_every_injected_rule_is_exercised(evaluation):
    """No rule may be absent from the labelled set."""
    assert len(evaluation.detection["by_rule_injected"]) >= 8


def test_false_positive_rate_meets_target(evaluation):
    fp = evaluation.false_positives
    assert fp["clean_records"] == 500
    assert fp["rate_pct"] <= FALSE_POSITIVE_TARGET


def test_dual_mode_consistency_is_total(evaluation):
    assert evaluation.dual_mode["consistent"] is True
    assert evaluation.dual_mode["consistency_pct"] == 100.0
    assert evaluation.dual_mode["batch_invalid"] == evaluation.dual_mode["incremental_invalid"]


def test_batch_performance_meets_target(evaluation):
    assert evaluation.performance["batch_seconds"] < PERFORMANCE_TARGET_SECONDS


def test_incremental_performance_meets_target(evaluation):
    assert evaluation.performance["incremental_seconds"] < PERFORMANCE_TARGET_SECONDS


def test_all_four_dimensions_met_on_raw(evaluation):
    """The real dataset is structurally clean, so all four should pass."""
    met = evaluation.dimensions["raw_met"]
    assert all(met.values()), f"dimensions not met: {met}"


def test_dimension_scores_are_bounded(evaluation):
    for value in evaluation.dimensions["raw"].values():
        assert 0.0 <= value <= 100.0


def test_real_data_findsings_are_r9_and_r14_only(evaluation):
    """The genuine defects, honestly reported.

    The source workbooks are structurally consistent, so only the cumulative
    rule fires on the raw tier, and only the progress rule on the derived tier.
    """
    assert set(evaluation.rules_observed["raw"]) == {"R9"}
    assert set(evaluation.rules_observed["derived"]) == {"R14"}
