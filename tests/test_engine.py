"""Invariants that must hold for every validation result.

These encode the counting semantics that were previously wrong.  ``invalid_records``
used to be set to the finding count, so a record breaking four rules was
subtracted four times and ``valid_records`` went negative.
"""

import pandas as pd
import pytest

from dqd.engine.validator import Validator


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


def test_r9_is_the_only_rule_firing_on_clean_real_data(validator, raw_data):
    """The source workbooks are structurally consistent.

    This is a genuine property of the real dataset, not a gap: R5, R6, R7, R11
    and R12 all return zero because the data has no duplicates, naming
    conflicts, WBS mapping errors or missing descriptions.
    """
    result = validator.validate(raw_data, tier="raw")
    assert set(result.findings_by_rule()) == {"R9"}


def test_wbs_code_keeps_leading_zeros(validator):
    """A WBS code written 011 must not collapse to 11."""
    from dqd.engine.validator import normalise_types

    frame = pd.DataFrame({"wbs_code": [11, "011"]})
    normalised = normalise_types(frame)
    assert normalised["wbs_code"].tolist() == ["11", "011"]


def test_missing_value_stays_missing(validator):
    """None must not become the literal string "None"."""
    from dqd.engine.validator import normalise_types

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


def test_r9_detects_a_restatement(validator, raw_data):
    """Halving a cumulative total must be caught by R9."""
    frame = raw_data.copy()
    frame["wbs_code"] = frame["wbs_code"].astype(str)
    target = frame.loc[(frame["project_id"] == "P01") & (frame["wbs_code"] == "11")]
    position = target.index[1]
    frame.loc[position, "ev_cum"] = float(frame.loc[position, "ev_cum"]) * 0.5

    result = validator.validate(frame, tier="raw")
    assert "R9" in result.findings_by_rule()


def test_incremental_matches_batch_for_same_records(fixtures):
    """Dual-mode consistency: identical flags in both modes."""
    from dqd.pipeline.runner import DataPipeline

    batch = DataPipeline().process_batch(fixtures.regression, tier="raw")
    incremental = DataPipeline().process_incremental(fixtures.regression, tier="raw")
    assert batch["by_rule"] == incremental["by_rule"]
    assert batch["invalid_records"] == incremental["invalid_records"]
    assert batch["total_records"] == incremental["total_records"]
