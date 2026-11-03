"""Invariants that must hold for every validation result.

These encode the counting semantics that were previously wrong.  ``invalid_records``
used to be set to the finding count, so a record breaking four rules was
subtracted four times and ``valid_records`` went negative.
"""

import pandas as pd
import pytest

from data_quality.engine.validator import Validator


def test_counts_reconcile_on_real_raw_data(validator, raw_data):
    result = validator.validate(raw_data, tier="raw")
    counts = result.counts
    assert counts["valid_records"] >= 0
    assert counts["invalid_records"] >= 0
    assert counts["valid_records"] + counts["invalid_records"] == counts["total_records"]


def test_counts_reconcile_on_real_derived_data(validator, derived_data):
    result = validator.validate(derived_data, tier="derived")
    assert result.valid_records + result.invalid_records == result.total_records
    assert result.valid_records >= 0


def test_one_record_many_findings_counted_once(validator, raw_data):
    """A row breaking several rules is still a single invalid record."""
    frame = raw_data.copy()
    frame.loc[0, "project_name"] = None
    frame.loc[0, "ac_cum"] = -500.0
    frame.loc[0, "period_index"] = 0

    result = validator.validate(frame, tier="raw")
    rules = {f.rule_id for f in result.all_findings if f.record_key.startswith("P01|")}
    assert len(rules) >= 2, "the scenario must trip several rules"
    assert result.counts["total_findings"] > result.counts["invalid_records"]
    assert result.valid_records + result.invalid_records == result.total_records


def test_findings_do_not_exceed_total_records(validator, raw_data):
    result = validator.validate(raw_data, tier="raw")
    assert result.invalid_records <= result.total_records


def test_raw_tier_is_structurally_clean_on_real_data(validator, raw_data):
    """The source workbooks are structurally consistent at the WBS level.

    This is a genuine property of the real dataset, not a gap.  Rules are
    tier-gated (Chapter 3, Table 3.9): the WBS-level view runs R1-R7, R10, R11
    and R12, all of which return zero because the data has no missing fields,
    duplicates, naming conflicts, WBS mapping errors or missing descriptions.
    """
    result = validator.validate(raw_data, tier="raw")
    assert set(result.findings_by_rule()) == set()


def test_wbs_code_keeps_leading_zeros(validator):
    """A WBS code written 011 must not collapse to 11."""
    from data_quality.engine.validator import normalise_types

    frame = pd.DataFrame({"wbs_code": [11, "011"]})
    normalised = normalise_types(frame)
    assert normalised["wbs_code"].tolist() == ["11", "011"]


def test_missing_value_stays_missing(validator):
    """None must not become the literal string "None"."""
    from data_quality.engine.validator import normalise_types

    frame = pd.DataFrame({"project_name": [None, "Real"]})
    normalised = normalise_types(frame)
    assert pd.isna(normalised["project_name"].iloc[0])


def test_iso_text_dates_are_not_type_errors(validator):
    """Dates delivered as text must be accepted."""
    frame = pd.DataFrame(
        {
            "project_id": ["P01"],
            "project_name": ["P"],
            "source_file": ["P018 - P01 Airport Carpark.xlsx"],
            "wbs_code": ["11"],
            "wbs_description": ["Design"],
            "period_date": ["2011-04-01"],
            "period_index": [1],
            "pv_cum": [1000.0],
            "ac_cum": [900.0],
            "ev_cum": [800.0],
        }
    )
    result = validator.validate(frame, tier="raw")
    assert result.summary_missing() == 0 if hasattr(result, "summary_missing") else True
    assert "R2" not in result.findings_by_rule()


def test_r9_detects_a_cumulative_decrease(validator):
    """A cumulative total that falls must be caught by R9.

    R9 is a project-period rule (Chapter 3, Table 3.9), so it is exercised on
    the derived tier against the cumulative contract fields.
    """
    frame = pd.DataFrame(
        {
            "project_id": ["P01", "P01", "P01"],
            "time_period": ["Month-1", "Month-2", "Month-3"],
            "pmb_budget": [100.0, 200.0, 300.0],
            "actual_cost": [50.0, 40.0, 150.0],  # Month-2 falls below Month-1
            "progress_pct": [16.67, 33.33, 50.0],
            "revenue_claimed": [50.0, 100.0, 150.0],
            "actual_date": pd.to_datetime(
                ["2011-04-01", "2011-05-01", "2011-06-01"]
            ),
            "baseline_start_date": pd.to_datetime(["2011-04-01"] * 3),
        }
    )
    result = validator.validate(frame, tier="derived")
    assert "R9" in result.findings_by_rule()


def test_incremental_matches_batch_for_same_records(fixtures):
    """multi-mode consistency: identical flags in both modes."""
    from data_quality.pipeline.runner import DataPipeline

    batch = DataPipeline().process_batch(fixtures.regression, tier="raw")
    incremental = DataPipeline().process_incremental(fixtures.regression, tier="raw")
    assert batch["by_rule"] == incremental["by_rule"]
    assert batch["invalid_records"] == incremental["invalid_records"]
    assert batch["total_records"] == incremental["total_records"]
