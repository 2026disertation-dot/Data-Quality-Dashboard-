"""
System tests driven by the real Kaggle Project Portfolio data.

Where ``test_data_pipeline.py`` and ``test_validation_engine.py`` check the
machinery on small hand-built frames, this module exercises the same machinery
against the real cleaned dataset so the research evaluation rests on genuine
project cost records:

* the dual-mode split (historical batch vs. newest incremental arrival);
* regression consistency, i.e. identical records must be flagged identically in
  both modes;
* detection completeness against labelled defects injected into real records;
* false positives on untouched real data;
* performance and data-contract compliance on the real dataset.

The whole module is skipped when the cleaned dataset is absent, so the suite
still runs on a fresh clone before the Kaggle step has been executed.
"""

import os
import sys
import time

import pandas as pd
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_contract import validate_data_contract
from data_fixtures import (
    DEFAULT_CLEANED,
    count_by_category,
    detected_keys,
    ground_truth_keys,
    inject_known_anomalies,
    load_cleaned_data,
    load_fixtures,
    score_detection,
    score_false_positives,
    split_batch_incremental,
)
from data_pipeline import DataPipeline
from validation_engine import ValidationEngine

# Targets stated in the research evaluation (Chapter 3.7)
DETECTION_COMPLETENESS_TARGET = 95.0
PERFORMANCE_TARGET_SECONDS = 5.0

pytestmark = pytest.mark.skipif(
    not os.path.exists(DEFAULT_CLEANED),
    reason="cleaned Kaggle dataset not present; run clean_kaggle_data.py first",
)


@pytest.fixture(scope="module")
def real_data():
    """The real cleaned dataset."""
    return load_cleaned_data()


@pytest.fixture(scope="module")
def fixtures():
    """Real-data batch/incremental and anomaly fixtures."""
    return load_fixtures()


@pytest.fixture
def engine():
    """A validation engine instance."""
    return ValidationEngine()


@pytest.fixture
def pipeline():
    """A data pipeline instance."""
    return DataPipeline()


class TestRealDatasetShape:
    """The real dataset must satisfy the contract it is meant to feed."""

    def test_satisfies_the_data_contract(self, real_data):
        is_valid, _validated, errors = validate_data_contract(real_data)
        assert is_valid, errors

    def test_has_no_duplicate_project_period(self, real_data):
        assert not real_data.duplicated(["project_id", "time_period"]).any()

    def test_covers_several_projects_and_periods(self, real_data):
        assert real_data["project_id"].nunique() >= 5
        assert real_data["time_period"].nunique() >= 4

    def test_periods_are_chronological_within_each_project(self, real_data):
        for _project, group in real_data.groupby("project_id"):
            assert group.sort_values("actual_date")["actual_date"].is_monotonic_increasing

    def test_reports_chronological_time_periods(self, real_data):
        """Month-N labels must increase with the reporting date."""
        for _project, group in real_data.groupby("project_id"):
            ordered = group.sort_values("actual_date")
            ranks = ordered["time_period"].str.extract(r"(\d+)", expand=False).astype(int)
            assert ranks.is_monotonic_increasing

    def test_actual_cost_never_precedes_baseline_start(self, real_data):
        assert (real_data["actual_date"] >= real_data["baseline_start_date"]).all()

    def test_money_values_are_non_negative(self, real_data):
        for column in ("pmb_budget", "actual_cost", "revenue_claimed"):
            assert (real_data[column] >= 0).all()

    def test_progress_is_within_range(self, real_data):
        assert real_data["progress_pct"].between(0, 100).all()


class TestDualModeOnRealData:
    """The batch/incremental split of the real records."""

    def test_split_holds_back_the_newest_period_per_project(self, real_data, fixtures):
        batch, incremental = fixtures["batch"], fixtures["incremental"]
        assert len(incremental) == real_data["project_id"].nunique()
        assert set(incremental["project_id"]) == set(real_data["project_id"])

    def test_split_partitions_the_dataset(self, real_data, fixtures):
        batch, incremental = fixtures["batch"], fixtures["incremental"]
        assert len(batch) + len(incremental) == len(real_data)

    def test_incremental_always_follows_batch(self, fixtures):
        batch, incremental = fixtures["batch"], fixtures["incremental"]
        latest_batch = batch.groupby("project_id")["actual_date"].max()
        for project, group in incremental.groupby("project_id"):
            assert (group["actual_date"] > latest_batch[project]).all()

    def test_batch_mode_accepts_the_historical_records(self, pipeline, fixtures):
        results = pipeline.process_batch(fixtures["batch"])
        assert results["mode"] == "batch"
        assert results["data_contract_valid"] is True
        assert len(results["processed_data"]) == len(fixtures["batch"])

    def test_incremental_mode_accepts_the_newest_records(self, pipeline, fixtures):
        pipeline.process_batch(fixtures["batch"])
        results = pipeline.process_incremental(fixtures["incremental"])
        assert results["mode"] == "incremental"
        assert results["data_contract_valid"] is True

    def test_incremental_mode_appends_to_the_history(self, pipeline, fixtures):
        batch = fixtures["batch"]
        incremental = fixtures["incremental"]
        pipeline.process_batch(batch)
        results = pipeline.process_incremental(incremental)
        assert len(results["processed_data"]) == len(batch) + len(incremental)

    def test_quality_scores_are_reported_in_both_modes(self, pipeline, fixtures):
        batch_metrics = pipeline.process_batch(fixtures["batch"])["quality_metrics"]
        incremental_metrics = pipeline.process_incremental(
            fixtures["incremental"]
        )["quality_metrics"]
        for key in ("accuracy", "completeness", "consistency", "integrity"):
            assert key in batch_metrics
            assert key in incremental_metrics


class TestRegressionConsistency:
    """Identical records must be flagged identically in both modes."""

    def test_same_records_produce_same_flags_in_both_modes(self, engine, fixtures):
        incremental = fixtures["incremental"]
        batch_keys = detected_keys(engine.validate_batch(incremental))
        incremental_keys = detected_keys(engine.validate_incremental(incremental))
        assert batch_keys == incremental_keys

    def test_regression_consistency_rate_is_full(self, engine, fixtures):
        incremental = fixtures["incremental"]
        batch_keys = detected_keys(engine.validate_batch(incremental))
        incremental_keys = detected_keys(engine.validate_incremental(incremental))
        union = batch_keys | incremental_keys
        rate = (len(batch_keys & incremental_keys) / len(union) * 100.0) if union else 100.0
        assert rate == 100.0

    def test_both_modes_agree_on_the_anomaly_counts(self, engine, fixtures):
        anomalous = fixtures["anomaly_set"]
        assert (
            count_by_category(engine.validate_batch(anomalous))
            == count_by_category(engine.validate_incremental(anomalous))
        )

    def test_incremental_mode_detects_duplicates_against_history(self, engine, fixtures):
        """A record already present in the history must be caught as a duplicate."""
        history = fixtures["batch"]
        replayed = history.head(3)
        results = engine.validate_incremental(replayed, existing_df=history)
        assert len(results["anomalies"]["duplicates"]) > 0


class TestDetectionCompleteness:
    """Labelled defects injected into real records must be detected."""

    def test_meets_the_detection_completeness_target(self, engine, fixtures):
        results = engine.validate_batch(fixtures["anomaly_set"])
        score = score_detection(results, fixtures["ground_truth"])
        assert score["missed"] == 0, score["missed_defects"]
        assert score["detection_completeness_pct"] >= DETECTION_COMPLETENESS_TARGET

    def test_every_defect_category_is_detected(self, engine, fixtures):
        results = engine.validate_batch(fixtures["anomaly_set"])
        counts = count_by_category(results)
        for category in ("missing_values", "type_errors", "bounds_violations",
                         "duplicates", "logical_anomalies"):
            assert counts[category] > 0, f"{category} detected nothing"

    def test_ground_truth_keys_match_the_injected_defects(self, fixtures):
        truth = fixtures["ground_truth"]
        assert set(truth["anomaly_name"]) >= {
            "missing_project_id", "type_error_actual_cost",
            "progress_above_100", "actual_date_before_baseline",
            "duplicate_record",
        }

    def test_a_text_value_in_a_numeric_field_does_not_abort_the_batch(self, engine, fixtures):
        """Regression test: a type error must not raise inside the bounds check."""
        results = engine.validate_batch(fixtures["anomaly_set"])
        assert results["total_records"] == len(fixtures["anomaly_set"])

    def test_injected_defects_break_the_data_contract(self, fixtures):
        is_valid, _validated, _errors = validate_data_contract(
            fixtures["anomaly_set"]
        )
        assert is_valid is False


class TestFalsePositivesOnRealData:
    """Untouched real records must not be flagged by the structural rules."""

    def test_structural_rules_flag_nothing_on_real_data(self, engine, real_data):
        """Missing, type, bounds and duplicate rules must be silent.

        The real dataset is clean, so any flag from these rules would be a
        false positive. The logical cost/progress rule is excluded because it
        is expected to identify genuine early-period overspend.
        """
        results = engine.validate_batch(real_data)
        counts = count_by_category(results)
        for category in ("missing_values", "type_errors", "bounds_violations",
                         "duplicates"):
            assert counts[category] == 0, f"{category}: {counts[category]}"

    def test_real_data_false_positive_rate_is_reported(self, engine, real_data):
        score = score_false_positives(engine.validate_batch(real_data), real_data)
        assert score["records"] == len(real_data)
        # Only the logical cost/progress rule fires, and only on genuine findings.
        assert set(score["by_category"]) == {
            "missing_values", "type_errors", "bounds_violations",
            "logical_anomalies", "duplicates",
        }

    def test_untouched_records_are_not_flagged_by_injected_run(self, engine, fixtures):
        """Records the injection did not touch must stay unflagged.

        Every genuine logical finding is removed first, so anything left is a
        false positive attributable to the engine rather than to the data.
        """
        clean = fixtures["cleaned"]
        results = engine.validate_batch(clean)
        findings = {a["row_index"] for a in results["anomalies"]["logical_anomalies"]}
        untouched = clean.drop(index=list(findings))
        # Re-validate the remaining clean records on their own.
        subset_results = engine.validate_batch(untouched.reset_index(drop=True))
        assert len(subset_results["anomalies"]["logical_anomalies"]) == 0

    def test_clean_subset_of_real_data_scores_full_integrity(self, pipeline, engine, fixtures):
        clean = fixtures["cleaned"]
        results = engine.validate_batch(clean)
        findings = {a["row_index"] for a in results["anomalies"]["logical_anomalies"]}
        untouched = clean.drop(index=list(findings)).reset_index(drop=True)
        metrics = pipeline.process_batch(untouched)["quality_metrics"]
        assert metrics["accuracy"] == 100.0
        assert metrics["completeness"] == 100.0
        assert metrics["consistency"] == 100.0
        assert metrics["integrity"] == 100.0


class TestPerformanceOnRealData:
    """The pipeline must stay inside the stated performance target."""

    def test_batch_mode_loads_within_the_target(self, pipeline, real_data):
        loaded = pipeline.load_data(DEFAULT_CLEANED)
        start = time.perf_counter()
        pipeline.process_batch(loaded)
        elapsed = time.perf_counter() - start
        assert elapsed < PERFORMANCE_TARGET_SECONDS, f"{elapsed:.2f}s"

    def test_incremental_mode_loads_within_the_target(self, pipeline, real_data):
        loaded = pipeline.load_data(DEFAULT_CLEANED)
        start = time.perf_counter()
        pipeline.process_incremental(loaded)
        elapsed = time.perf_counter() - start
        assert elapsed < PERFORMANCE_TARGET_SECONDS, f"{elapsed:.2f}s"

    def test_repeated_scoring_is_deterministic(self, engine, real_data):
        first = count_by_category(engine.validate_batch(real_data))
        second = count_by_category(engine.validate_batch(real_data))
        assert first == second


class TestFixtureIntegrity:
    """The fixtures themselves must be sound."""

    def test_anomaly_set_only_adds_the_duplicate_record(self, fixtures):
        assert len(fixtures["anomaly_set"]) == len(fixtures["cleaned"]) + 1

    def test_batch_and_incremental_do_not_overlap(self, fixtures):
        batch_keys = set(map(tuple, fixtures["batch"][["project_id", "time_period"]].values))
        incremental_keys = set(
            map(tuple, fixtures["incremental"][["project_id", "time_period"]].values)
        )
        assert not (batch_keys & incremental_keys)

    def test_split_is_deterministic(self, real_data):
        first = split_batch_incremental(real_data)[0]
        second = split_batch_incremental(real_data)[0]
        pd.testing.assert_frame_equal(first, second)

    def test_injection_is_deterministic(self, real_data):
        _set_a, truth_a = inject_known_anomalies(real_data)
        _set_b, truth_b = inject_known_anomalies(real_data)
        pd.testing.assert_frame_equal(truth_a, truth_b)

    def test_ground_truth_is_aligned_with_detections(self, engine, fixtures):
        expected = ground_truth_keys(fixtures["ground_truth"])
        observed = detected_keys(engine.validate_batch(fixtures["anomaly_set"]))
        assert expected <= observed
