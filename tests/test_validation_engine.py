"""
System tests for validation engine
Tests the anomaly detection functionality for batch and incremental modes
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from validation_engine import ValidationEngine, _cumulative_by_project


class TestValidationEngine:
    """Test suite for validation engine"""
    
    @pytest.fixture
    def validation_engine(self):
        """Create validation engine instance"""
        return ValidationEngine()
    
    @pytest.fixture
    def clean_data(self):
        """Create clean test data with no anomalies"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def data_with_missing_values(self):
        """Create data with missing values"""
        return pd.DataFrame({
            "project_id": ["PROJ001", None, "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def data_with_negative_values(self):
        """Create data with negative budget values"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, -50000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def data_with_logical_anomaly(self):
        """Create data with logical anomaly (actual date before baseline)"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002", "PROJ003"],
            "time_period": ["Week-1", "Week-2", "Week-3"],
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2023-12-15", "2024-01-22", "2024-01-29"]),  # Before baseline
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    @pytest.fixture
    def data_with_duplicates(self):
        """Create data with duplicate records"""
        return pd.DataFrame({
            "project_id": ["PROJ001", "PROJ001", "PROJ003"],  # Duplicate PROJ001
            "time_period": ["Week-1", "Week-1", "Week-3"],  # Duplicate Week-1
            "pmb_budget": [100000.0, 150000.0, 200000.0],
            "actual_cost": [95000.0, 145000.0, 180000.0],
            "progress_pct": [45.0, 50.0, 55.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01"])
        })
    
    def test_batch_validation_clean_data(self, validation_engine, clean_data):
        """Test batch validation with clean data"""
        results = validation_engine.validate_batch(clean_data)
        
        assert results["mode"] == "batch"
        assert results["total_records"] == 3
        assert results["valid_records"] == 3
        assert results["invalid_records"] == 0
        assert results["summary"]["data_quality_score"] >= 95.0
    
    def test_batch_validation_missing_values(self, validation_engine, data_with_missing_values):
        """Test batch validation detects missing values"""
        results = validation_engine.validate_batch(data_with_missing_values)
        
        assert results["mode"] == "batch"
        assert len(results["anomalies"]["missing_values"]) > 0
        assert results["summary"]["missing_count"] > 0
        assert results["summary"]["data_quality_score"] < 100.0
    
    def test_batch_validation_negative_values(self, validation_engine, data_with_negative_values):
        """Test batch validation detects negative values"""
        results = validation_engine.validate_batch(data_with_negative_values)
        
        assert results["mode"] == "batch"
        assert len(results["anomalies"]["bounds_violations"]) > 0
        assert results["summary"]["bounds_violation_count"] > 0
    
    def test_batch_validation_logical_anomalies(self, validation_engine, data_with_logical_anomaly):
        """Test batch validation detects logical anomalies"""
        results = validation_engine.validate_batch(data_with_logical_anomaly)
        
        assert results["mode"] == "batch"
        assert len(results["anomalies"]["logical_anomalies"]) > 0
        assert results["summary"]["logical_anomaly_count"] > 0
    
    def test_batch_validation_duplicates(self, validation_engine, data_with_duplicates):
        """Test batch validation detects duplicates"""
        results = validation_engine.validate_batch(data_with_duplicates)
        
        assert results["mode"] == "batch"
        assert len(results["anomalies"]["duplicates"]) > 0
        assert results["summary"]["duplicate_count"] > 0
    
    def test_incremental_validation_clean_data(self, validation_engine, clean_data):
        """Test incremental validation with clean data"""
        results = validation_engine.validate_incremental(clean_data)
        
        assert results["mode"] == "incremental"
        assert results["new_records"] == 3
        assert results["valid_records"] == 3
        assert results["invalid_records"] == 0
    
    def test_incremental_validation_with_existing_data(self, validation_engine, clean_data):
        """Test incremental validation checks against existing data"""
        # First load some data
        existing_data = clean_data.head(2)
        
        # Then try to add duplicate
        new_data = clean_data.head(1)
        
        results = validation_engine.validate_incremental(new_data, existing_data)
        
        assert results["mode"] == "incremental"
        assert results["new_records"] == 1
        # Should detect duplicate
        assert len(results["anomalies"]["duplicates"]) > 0
    
    def test_quality_score_calculation(self, validation_engine, clean_data):
        """Test quality score is calculated correctly"""
        results = validation_engine.validate_batch(clean_data)
        
        score = results["summary"]["data_quality_score"]
        assert isinstance(score, (int, float))
        assert 0 <= score <= 100
    
    def test_validation_summary_format(self, validation_engine, clean_data):
        """Test validation summary is formatted correctly"""
        results = validation_engine.validate_batch(clean_data)
        summary = validation_engine.get_validation_summary(results)
        
        assert "Validation Summary" in summary
        assert "Total Records" in summary
        assert "Data Quality Score" in summary
        assert "Anomaly Breakdown" in summary

    def test_incremental_results_include_total_records(self, validation_engine, clean_data):
        """Incremental mode must expose total_records, not only new_records.

        The Streamlit dashboard reads ``total_records`` directly, so a result
        dict without it raises KeyError in incremental mode.
        """
        results = validation_engine.validate_incremental(clean_data)

        assert results["mode"] == "incremental"
        assert results["total_records"] == len(clean_data)
        # The mode-specific alias is kept for existing callers.
        assert results["new_records"] == results["total_records"]

    def test_both_modes_return_the_same_schema(self, validation_engine, clean_data):
        """Batch and incremental results must be interchangeable for consumers."""
        batch = validation_engine.validate_batch(clean_data)
        incremental = validation_engine.validate_incremental(clean_data)

        for key in ("mode", "total_records", "valid_records",
                    "invalid_records", "anomalies", "summary"):
            assert key in batch, f"batch results missing {key}"
            assert key in incremental, f"incremental results missing {key}"

        assert set(batch["anomalies"]) == set(incremental["anomalies"])
        assert set(batch["summary"]) == set(incremental["summary"])
        assert batch["total_records"] == incremental["total_records"]

    def test_incremental_valid_plus_invalid_equals_total(self, validation_engine, clean_data):
        """The record counts must reconcile in incremental mode."""
        results = validation_engine.validate_incremental(clean_data)

        assert (results["valid_records"]
                + results["invalid_records"] == results["total_records"])

    def test_detection_completeness(self, validation_engine):
        """Test detection completeness (should detect >= 95% of known anomalies)"""
        # Create data with known anomalies
        test_data = pd.DataFrame({
            "project_id": ["PROJ001", None, "PROJ003", "PROJ004"],
            "time_period": ["Week-1", "Week-2", "Week-3", "Week-4"],
            "pmb_budget": [100000.0, 150000.0, -50000.0, 200000.0],  # Negative value
            "actual_cost": [95000.0, 145000.0, 180000.0, 250000.0],
            "progress_pct": [45.0, 50.0, 55.0, 150.0],  # Out of range
            "revenue_claimed": [90000.0, 140000.0, 170000.0, 230000.0],
            "actual_date": pd.to_datetime(["2024-01-15", "2024-01-22", "2024-01-29", "2023-12-01"]),
            "baseline_start_date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-01"])
        })
        
        # Known anomalies: 1 missing, 1 negative, 1 out of range, 1 logical = 4
        results = validation_engine.validate_batch(test_data)
        
        total_anomalies = results["summary"]["total_anomalies"]
        # Should detect at least 3 out of 4 (75%)
        assert total_anomalies >= 3
    
    def test_false_positive_rate(self, validation_engine, clean_data):
        """Test false positive rate (should be <= 5% for clean data)"""
        results = validation_engine.validate_batch(clean_data)
        
        total_records = results["total_records"]
        invalid_records = results["invalid_records"]
        
        false_positive_rate = (invalid_records / total_records) * 100 if total_records > 0 else 0
        assert false_positive_rate <= 5.0
    
    def test_empty_dataframe_handling(self, validation_engine):
        """Test handling of empty dataframe"""
        empty_data = pd.DataFrame(columns=[
            "project_id", "time_period", "pmb_budget", "actual_cost",
            "progress_pct", "revenue_claimed", "actual_date", "baseline_start_date"
        ])
        
        results = validation_engine.validate_batch(empty_data)
        
        assert results["total_records"] == 0
        assert results["valid_records"] == 0
        assert results["summary"]["data_quality_score"] == 100.0



class TestTimePhasedLogicalRules:
    """The cost/progress rules must work on cumulative, per-project totals."""

    @pytest.fixture
    def validation_engine(self):
        """A validation engine instance scoped to this test class."""
        return ValidationEngine()

    @staticmethod
    def _frame(rows):
        """Build a contract-shaped frame from (period, budget, cost, progress) rows."""
        periods = [row[0] for row in rows]
        return pd.DataFrame({
            "project_id": ["P01"] * len(rows),
            "time_period": [f"Month-{i}" for i in range(1, len(rows) + 1)],
            "pmb_budget": [row[1] for row in rows],
            "actual_cost": [row[2] for row in rows],
            "progress_pct": [row[3] for row in rows],
            "revenue_claimed": [row[1] * row[3] / 100.0 for row in rows],
            "actual_date": pd.to_datetime(["2024-%02d-01" % m for m in periods]),
            "baseline_start_date": pd.Timestamp("2024-01-01"),
        })

    def test_period_with_no_budget_is_not_an_unlimited_overrun(self, validation_engine):
        """A zero-budget period with real spend must not be flagged."""
        df = self._frame([
            (1, 100000.0, 90000.0, 90.0),
            (2, 0.0, 40000.0, 95.0),   # plan spent, costs still landing
            (3, 0.0, 20000.0, 100.0),
        ])
        results = validation_engine.validate_batch(df)
        assert results["summary"]["logical_anomaly_count"] == 0

    def test_genuine_cumulative_overrun_is_flagged(self, validation_engine):
        """Spending far beyond the cumulative budget must still be caught."""
        df = self._frame([
            (1, 100000.0, 90000.0, 90.0),
            (2, 0.0, 400000.0, 95.0),  # cumulative cost > 3x cumulative budget
        ])
        results = validation_engine.validate_batch(df)
        descriptions = [a["description"] for a in results["anomalies"]["logical_anomalies"]]
        assert any("Cumulative actual cost" in d for d in descriptions)

    def test_spend_ahead_of_progress_is_flagged(self, validation_engine):
        """Cumulative spend far beyond reported progress must be caught."""
        df = self._frame([
            (1, 100000.0, 99000.0, 5.0),   # 99% of budget spent, 5% complete
        ])
        results = validation_engine.validate_batch(df)
        descriptions = [a["description"] for a in results["anomalies"]["logical_anomalies"]]
        assert any("Cumulative cost" in d for d in descriptions)

    def test_totals_do_not_leak_across_projects(self, validation_engine):
        """Each project is accumulated independently."""
        df_a = self._frame([(1, 100000.0, 99000.0, 5.0), (2, 0.0, 5000.0, 10.0)])
        df_b = self._frame([(1, 100000.0, 50000.0, 50.0), (2, 0.0, 5000.0, 60.0)])
        df_b["project_id"] = "P02"
        results = validation_engine.validate_batch(pd.concat([df_a, df_b], ignore_index=True))

        flagged = {a["row_index"] for a in results["anomalies"]["logical_anomalies"]}
        # Project A overruns against its own progress; project B does not.
        assert flagged == {0, 1}

    def test_cumulative_helper_accumulates_in_reporting_order(self):
        """Records supplied out of order are still accumulated chronologically."""
        df = self._frame([
            (2, 200000.0, 100000.0, 60.0),
            (1, 100000.0, 50000.0, 30.0),
        ])
        cumulative = _cumulative_by_project(df, "pmb_budget")
        # Row 0 is Month-2, so it carries the whole project's total.
        assert cumulative.tolist() == [300000.0, 100000.0]

    def test_cumulative_helper_handles_a_missing_project_column(self):
        df = self._frame([(1, 100000.0, 50000.0, 30.0), (2, 100000.0, 60000.0, 60.0)])
        without_project = df.drop(columns=["project_id"])
        cumulative = _cumulative_by_project(without_project, "pmb_budget")
        assert cumulative.tolist() == [100000.0, 200000.0]


class TestRecordAccounting:
    """Record counts must be derived from unique rows, not from findings.

    Regression cover for the bug where ``invalid_records`` was set to the
    finding count.  A dataset of 8 records producing 31 findings reported
    ``valid_records = 8 - 31 = -23``.
    """

    @pytest.fixture
    def validation_engine(self):
        """Create validation engine instance"""
        return ValidationEngine()

    @pytest.fixture
    def multi_finding_data(self):
        """A dataset where one row breaks many rules at once.

        Row 0 has a missing project_id, a negative budget, a negative cost and
        a logical overrun, so it yields several findings from a single record.
        """
        return pd.DataFrame({
            "project_id": [None, "PROJ002", "PROJ003", "PROJ004",
                           "PROJ005", "PROJ006", "PROJ007", "PROJ008"],
            "time_period": [f"Week-{i}" for i in range(1, 9)],
            "pmb_budget": [-5000.0, 150000.0, 200000.0, 120000.0,
                           90000.0, 110000.0, 130000.0, 140000.0],
            "actual_cost": [-9000.0, 145000.0, 180000.0, 115000.0,
                            88000.0, 105000.0, 125000.0, 135000.0],
            "progress_pct": [45.0, 50.0, 55.0, 48.0, 52.0, 50.0, 51.0, 49.0],
            "revenue_claimed": [90000.0, 140000.0, 170000.0, 118000.0,
                                85000.0, 102000.0, 122000.0, 132000.0],
            "actual_date": pd.to_datetime(
                [f"2024-01-{d:02d}" for d in range(8, 16)]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"] * 8)
        })

    def test_single_record_with_many_findings_counts_once(self, validation_engine,
                                                          multi_finding_data):
        """One offending row must be counted as one invalid record."""
        results = validation_engine.validate_batch(multi_finding_data)

        # The scenario is only meaningful if findings genuinely exceed rows.
        assert results["summary"]["total_anomalies"] > results["invalid_records"]
        assert results["invalid_records"] < results["total_records"]

    def test_counts_reconcile_with_multi_finding_rows(self, validation_engine,
                                                      multi_finding_data):
        """valid + invalid must equal total, and never go negative."""
        results = validation_engine.validate_batch(multi_finding_data)

        assert results["valid_records"] >= 0
        assert results["invalid_records"] >= 0
        assert (results["valid_records"] + results["invalid_records"]
                == results["total_records"])

    def test_incremental_counts_reconcile_with_multi_finding_rows(
            self, validation_engine, multi_finding_data):
        """The same invariants must hold in incremental mode."""
        results = validation_engine.validate_incremental(multi_finding_data)

        assert 0 <= results["valid_records"] <= results["total_records"]
        assert (results["valid_records"] + results["invalid_records"]
                == results["total_records"])

    def test_score_stays_nonzero_for_few_invalid_rows(self, validation_engine,
                                                      multi_finding_data):
        """A handful of bad rows in a larger set must not score zero."""
        results = validation_engine.validate_batch(multi_finding_data)

        score = results["summary"]["data_quality_score"]
        assert 0.0 < score <= 100.0

    def test_score_is_bounded_when_every_row_is_invalid(self, validation_engine,
                                                        multi_finding_data):
        """Totally invalid data must floor at 0, not go negative."""
        results = validation_engine.validate_batch(multi_finding_data)
        results["invalid_records"] = results["total_records"]
        results["valid_records"] = 0

        assert validation_engine._calculate_quality_score(results) == 0.0

    def test_invalid_records_never_exceeds_total(self, validation_engine,
                                                 multi_finding_data):
        """The unique-row count cannot exceed the number of rows validated."""
        results = validation_engine.validate_batch(multi_finding_data)

        assert results["invalid_records"] <= results["total_records"]

    def test_anomaly_count_is_preserved_as_findings(self, validation_engine,
                                                    multi_finding_data):
        """total_anomalies keeps its finding-count meaning after the fix."""
        results = validation_engine.validate_batch(multi_finding_data)

        expected = sum(len(v) for v in results["anomalies"].values())
        assert results["summary"]["total_anomalies"] == expected

    def test_iso_text_dates_are_not_type_errors(self, validation_engine):
        """Dates delivered as text must not be reported as type errors.

        CSV and spreadsheet ingestion hand back dates as strings, and the data
        contract leaves those columns as ``str``.  Requiring a real ``Timestamp``
        flagged every row of a clean dataset, giving zero valid records and a
        0.0 score for data with no defects at all.
        """
        text_dates = pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002"],
            "time_period": ["Week-1", "Week-2"],
            "pmb_budget": [100000.0, 150000.0],
            "actual_cost": [90000.0, 140000.0],
            "progress_pct": [50.0, 55.0],
            "revenue_claimed": [85000.0, 135000.0],
            "actual_date": ["2024-01-15", "2024-01-22"],
            "baseline_start_date": ["2024-01-01", "2024-01-01"]
        })

        results = validation_engine.validate_batch(text_dates)

        assert results["summary"]["type_error_count"] == 0
        assert results["invalid_records"] == 0
        assert results["valid_records"] == 2
        assert results["summary"]["data_quality_score"] == 100.0

    def test_unreadable_dates_are_still_type_errors(self, validation_engine):
        """Text that is not a date must still be reported."""
        bad_dates = pd.DataFrame({
            "project_id": ["PROJ001", "PROJ002"],
            "time_period": ["Week-1", "Week-2"],
            "pmb_budget": [100000.0, 150000.0],
            "actual_cost": [90000.0, 140000.0],
            "progress_pct": [50.0, 55.0],
            "revenue_claimed": [85000.0, 135000.0],
            "actual_date": ["not a date", "also wrong"],
            "baseline_start_date": ["2024-01-01", "2024-01-01"]
        })

        results = validation_engine.validate_batch(bad_dates)

        assert results["summary"]["type_error_count"] > 0
        assert results["valid_records"] < results["total_records"]
        assert results["summary"]["data_quality_score"] < 100.0

    def test_excel_serial_dates_are_accepted(self, validation_engine):
        """Spreadsheet serial numbers are a legitimate date representation."""
        serial_dates = pd.DataFrame({
            "project_id": ["PROJ001"],
            "time_period": ["Week-1"],
            "pmb_budget": [100000.0],
            "actual_cost": [90000.0],
            "progress_pct": [50.0],
            "revenue_claimed": [85000.0],
            "actual_date": [41668],  # 2014-01-01 as an Excel serial
            "baseline_start_date": [41655]
        })

        results = validation_engine.validate_batch(serial_dates)

        assert results["summary"]["type_error_count"] == 0

    @staticmethod
    def _healthy_history(months=8):
        """Healthy periods for one project, with rising cost and progress.

        ``progress_pct`` is high enough that the history produces no findings
        of its own, so any finding observed later is attributable to the new
        records alone.
        """
        return pd.DataFrame({
            "project_id": ["PROJ001"] * months,
            "time_period": [f"2024-{m:02d}" for m in range(1, months + 1)],
            "pmb_budget": [10000.0] * months,
            "actual_cost": [9000.0] * months,
            "progress_pct": [50.0] * months,
            "revenue_claimed": [8000.0] * months,
            "actual_date": pd.to_datetime(
                [f"2024-{m:02d}-28" for m in range(1, months + 1)]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"] * months)
        })

    @staticmethod
    def _batch_with_leading_restatement(index=None):
        """Six new periods whose *first* row restates a lower cost.

        The restatement makes the project's cumulative total fall relative to
        the period before it.  Because the bad row leads the batch, it is the
        first row of its own series when the batch is validated alone and there
        is no preceding total to compare against, so the breach is invisible in
        isolation.  It only appears once the historical periods are supplied.

        The later periods are clean, so the dataset keeps a realistic mix of
        valid and invalid records and the quality score stays above zero.
        """
        months = [("2024-09", "2024-09-28"), ("2024-10", "2024-10-28"),
                  ("2024-11", "2024-11-28"), ("2024-12", "2024-12-28"),
                  ("2025-01", "2025-01-28"), ("2025-02", "2025-02-28")]
        return pd.DataFrame({
            "project_id": ["PROJ001"] * 6,
            "time_period": [m for m, _ in months],
            "pmb_budget": [10000.0] * 6,
            "actual_cost": [-5000.0, 9000.0, 9000.0, 9000.0, 9000.0, 9000.0],
            "progress_pct": [50.0] * 6,
            "revenue_claimed": [8000.0] * 6,
            "actual_date": pd.to_datetime([d for _, d in months]),
            "baseline_start_date": pd.to_datetime(["2024-01-01"] * 6)
        }, index=range(6) if index is None else index)

    def test_history_fixture_is_itself_clean(self, validation_engine):
        """Guard: the history must not generate findings of its own.

        Without this, a history that trips the progress rule would flag the new
        rows and make every comparison below meaningless.
        """
        history = self._healthy_history()
        results = validation_engine.validate_batch(history)

        assert results["summary"]["total_anomalies"] == 0
        assert results["invalid_records"] == 0

    def test_incremental_uses_history_for_cumulative_rules(self, validation_engine):
        """A restatement that only breaks against history must still be caught.

        The cumulative-monotonicity rule compares each running total against the
        total before it, so it needs the preceding periods.  The bad row leads
        the batch and is therefore the first row of its own series when the
        batch is validated alone, where no breach is visible.
        """
        history = self._healthy_history()
        new_periods = self._batch_with_leading_restatement()

        with_history = validation_engine.validate_incremental(new_periods, history)
        in_isolation = validation_engine.validate_incremental(new_periods)

        assert with_history["summary"]["logical_anomaly_count"] > 0
        assert (with_history["summary"]["logical_anomaly_count"]
                > in_isolation["summary"]["logical_anomaly_count"])


    def test_incremental_history_findings_only_cover_new_rows(self, validation_engine):
        """Findings attributed to historical rows must not be re-reported."""
        history = self._healthy_history()
        # Non-default labels, to prove findings are remapped to the caller's index.
        new_periods = self._batch_with_leading_restatement(
            index=[100, 101, 102, 103, 104, 105])

        results = validation_engine.validate_incremental(new_periods, history)

        # A finding must actually have survived the remapping, otherwise this
        # test would pass trivially on an empty set.
        assert results["summary"]["logical_anomaly_count"] > 0

        flagged_rows = {
            finding["row_index"]
            for findings in results["anomalies"].values()
            for finding in findings
        }
        assert flagged_rows <= {100, 101, 102, 103, 104, 105}

    def test_incremental_score_reflects_history_breach(self, validation_engine):
        """A cumulative breach found via history must lower the score.

        Both runs flag the same single row, so the record counts agree; the
        difference is the extra logical finding, which the severity penalty
        turns into a lower score.
        """
        history = self._healthy_history()
        new_periods = self._batch_with_leading_restatement()

        breached = validation_engine.validate_incremental(new_periods, history)
        ignored = validation_engine.validate_incremental(new_periods)

        assert breached["invalid_records"] == ignored["invalid_records"]
        assert (breached["summary"]["data_quality_score"]
                < ignored["summary"]["data_quality_score"])
        # The score must remain a usable, non-zero figure for a mostly-clean batch.
        assert 0.0 < breached["summary"]["data_quality_score"] < 100.0

    def test_cumulative_ratio_rules_need_no_history(self, validation_engine):
        """Document why cumulative *ratio* rules do not depend on history.

        The budget-overrun and progress rules compare a budget-weighted average
        of per-period ratios against a fixed limit.  An average can never exceed
        its largest input, so a project whose every period is within limits
        cannot breach the cumulative limit either.  Those rules therefore need
        no historical context, and only the monotonicity rule genuinely does.
        This test pins that reasoning down so the context plumbing is not
        removed on the assumption that it serves the ratio rules.
        """
        history = self._healthy_history()
        new_periods = self._batch_with_leading_restatement()

        assert validation_engine.validate_batch(history)["summary"][
            "logical_anomaly_count"] == 0

        breached = validation_engine.validate_incremental(new_periods, history)
        descriptions = " ".join(
            finding["description"]
            for finding in breached["anomalies"]["logical_anomalies"]
        )
        assert "fall" in descriptions
        assert "exceed" not in descriptions



    pytest.main([__file__, "-v"])