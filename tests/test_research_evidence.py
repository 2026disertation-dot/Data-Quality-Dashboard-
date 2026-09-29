"""
System tests for the profiling, comparison and figure modules.

These cover the three modules that produce the research evidence:

* ``profiling`` - the measured anomaly-category table that replaces the
  hand-entered profiling figures in the write-up;
* ``spreadsheet_baseline`` - the honest like-for-like baseline used to answer the
  fourth research question;
* ``generate_figures`` - the figure set exported for the write-up.

The tests assert that the measured numbers are internally consistent, that the
tables cover every contract field, and that the figures are produced from the
real data rather than from placeholders.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data_contract import get_contract_specification
from data_fixtures import load_fixtures
from generate_figures import (build_all_figures, figure_dimension_scores,
                              figure_planned_vs_actual, figure_pipeline_workflow)
from profiling import (ANOMALY_CATEGORY_ORDER, anomaly_category_table,
                       duplicate_key_counts, format_conflict_counts,
                       load_cleaned_data, profile_frame, project_summary,
                       summary_statistics_table, to_markdown)
from spreadsheet_baseline import (build_comparison_table, column_aggregate_findings,
                                  run_spreadsheet_checks, score_engine,
                                  score_findings)
from validation_engine import ValidationEngine


@pytest.fixture(scope="module")
def real_data():
    """The real cleaned Kaggle dataset."""
    df = load_cleaned_data()
    if df is None:
        pytest.skip("real cleaned dataset is not available")
    return df


@pytest.fixture(scope="module")
def real_fixtures():
    """The real-data test fixtures."""
    fixtures = load_fixtures()
    if fixtures is None:
        pytest.skip("real-data fixtures are not available")
    return fixtures


class TestProfiling:
    """The profiling tables must describe the real data accurately."""

    def test_profile_covers_every_contract_field(self, real_data):
        profile = profile_frame(real_data)
        assert set(profile.index) == set(get_contract_specification()["required_fields"])

    def test_profile_reports_no_missing_values_on_clean_data(self, real_data):
        profile = profile_frame(real_data)
        assert profile["missing"].sum() == 0
        assert profile["missing_pct"].sum() == 0.0

    def test_profile_detects_a_format_conflict(self, real_data):
        # A dirty import makes the whole column text, which is exactly what a
        # real file with one bad cell looks like once pandas re-reads it.
        dirty = real_data.copy()
        dirty["actual_cost"] = dirty["actual_cost"].astype(object)
        dirty.loc[dirty.index[0], "actual_cost"] = "not_a_number"
        assert len(format_conflict_counts(dirty)) == 1
        assert profile_frame(dirty)["format_conflicts"].sum() == 1

    def test_duplicate_keys_are_counted_when_present(self, real_data):
        duplicated = pd.concat([real_data, real_data.head(1)], ignore_index=True)
        rows, groups, key_columns = duplicate_key_counts(duplicated)
        assert key_columns == ["project_id", "time_period"]
        assert rows == 2
        assert groups == 1

    def test_clean_data_has_no_duplicate_keys(self, real_data):
        rows, _, _ = duplicate_key_counts(real_data)
        assert rows == 0

    def test_category_table_covers_every_category(self, real_data):
        results = ValidationEngine().validate_batch(real_data)
        table = anomaly_category_table(real_data, results)
        assert list(table["category"]) == ANOMALY_CATEGORY_ORDER
        assert (table["records_affected"] >= 0).all()
        assert (table["pct_of_total"] >= 0).all()

    def test_category_table_attributes_to_a_real_project(self, real_data):
        results = ValidationEngine().validate_batch(real_data)
        table = anomaly_category_table(real_data, results)
        known = set(real_data["project_id"].astype(str))
        named = {value for value in table["most_affected_project"] if value != "-"}
        assert named <= known

    def test_project_summary_totals_reconcile(self, real_data):
        summary = project_summary(real_data)
        assert len(summary) == real_data["project_id"].nunique()
        expected = real_data.groupby("project_id")["actual_cost"].sum()
        for row in summary.itertuples():
            assert row.total_actual_cost == pytest.approx(expected[row.project_id], abs=0.01)

    def test_summary_statistics_cover_the_numeric_fields(self, real_data):
        stats = summary_statistics_table(real_data)
        assert set(stats.index) == {
            "pmb_budget", "actual_cost", "progress_pct", "revenue_claimed"}
        assert (stats["count"] == len(real_data)).all()

    def test_markdown_renders_a_header_and_rows(self, real_data):
        lines = to_markdown(project_summary(real_data)).splitlines()
        assert lines[0].startswith("| project_id")
        assert set(lines[1]) <= {"|", "-", " "}
        assert len(lines) > 2

    def test_markdown_handles_an_empty_frame(self):
        assert to_markdown(pd.DataFrame()) == "_no rows_"


class TestSpreadsheetBaseline:
    """The comparison must be measured, and must not flatter the dashboard."""

    def test_checks_run_and_return_findings(self, real_fixtures):
        findings, seconds = run_spreadsheet_checks(real_fixtures["anomaly_set"])
        assert isinstance(findings, list)
        assert seconds > 0
        assert findings, "the anomaly test set should produce findings"

    def test_every_defect_is_detected_by_the_engine(self, real_fixtures):
        results = ValidationEngine().validate_batch(real_fixtures["anomaly_set"])
        scores = score_engine(results, real_fixtures["ground_truth"])
        assert scores["detected"] == scores["expected"]

    def test_sheet_scores_are_measured_not_assumed(self, real_fixtures):
        findings, _ = run_spreadsheet_checks(real_fixtures["anomaly_set"])
        scores = score_findings(findings, real_fixtures["ground_truth"])
        assert scores["expected"] == len(real_fixtures["ground_truth"])
        assert 0 <= scores["detected_pct"] <= 100.0

    def test_attribution_never_exceeds_detection(self, real_fixtures):
        findings, _ = run_spreadsheet_checks(real_fixtures["anomaly_set"])
        scores = score_findings(findings, real_fixtures["ground_truth"])
        assert scores["attributed"] <= scores["detected"]

    def test_column_aggregates_cannot_attribute_a_record(self, real_fixtures):
        """A COUNTIF over the key implicates rows but names none.

        This is the structural weakness the comparison rests on, so it is
        asserted directly rather than inferred from the totals.
        """
        findings = column_aggregate_findings(real_fixtures["anomaly_set"])
        duplicates = [f for f in findings if f["category"] == "duplicates"]
        assert duplicates, "the duplicated record should trip COUNTIF"
        for finding in duplicates:
            assert finding["attributed_rows"] == set()
            assert finding["implicated_rows"], "COUNTIF should still implicate the rows"

    def test_engine_attributes_everything_it_detects(self, real_fixtures):
        results = ValidationEngine().validate_batch(real_fixtures["anomaly_set"])
        scores = score_engine(results, real_fixtures["ground_truth"])
        assert scores["attributed"] == scores["detected"]

    def test_comparison_table_pairs_every_scored_class(self, real_fixtures):
        results = ValidationEngine().validate_batch(real_fixtures["anomaly_set"])
        findings, _ = run_spreadsheet_checks(real_fixtures["anomaly_set"])
        table = build_comparison_table(
            score_engine(results, real_fixtures["ground_truth"]),
            score_findings(findings, real_fixtures["ground_truth"]),
        )
        assert not table.empty
        assert (table["defects"] > 0).all()
        # The dashboard cannot be credited with detecting less than the baseline.
        assert (table["dashboard_detected_pct"]
                >= table["sheet_detected_pct"]).all()


class TestFigures:
    """The figure set must render from the real data."""

    def test_dimension_figure_contains_one_bar_per_dimension(self, real_data):
        from data_pipeline import DataPipeline

        metrics = DataPipeline().process_batch(real_data)["quality_metrics"]
        figure = figure_dimension_scores(metrics)
        assert len(figure.data) == 1
        assert len(figure.data[0].x) == 4

    def test_planned_versus_actual_figure_uses_the_real_records(self, real_data):
        figure = figure_planned_vs_actual(real_data)
        # One planned and one actual trace per project.
        assert len(figure.data) == real_data["project_id"].nunique() * 2

    def test_workflow_figure_reports_fixture_sizes(self, real_fixtures):
        figure = figure_pipeline_workflow(real_fixtures)
        labels = " ".join(figure.data[1].text)
        assert str(len(real_fixtures["batch"])) in labels
        assert str(len(real_fixtures["incremental"])) in labels

    def test_figures_are_written_to_disk(self, real_data, real_fixtures, tmp_path):
        """The whole set exports without raising, proving it is complete."""
        from run_pipeline import (DETECTION_COMPLETENESS_TARGET,
                                  FALSE_POSITIVE_TARGET,
                                  PERFORMANCE_TARGET_SECONDS, measure)

        evidence = measure(real_data, real_fixtures)
        targets = {
            "detection_completeness": DETECTION_COMPLETENESS_TARGET,
            "false_positive": FALSE_POSITIVE_TARGET,
            "performance_seconds": PERFORMANCE_TARGET_SECONDS,
        }
        written = build_all_figures(real_data, real_fixtures, evidence, targets,
                                    directory=str(tmp_path))
        assert len(written) >= 10
        for path in written.values():
            assert os.path.getsize(path) > 1000
        lines = to_markdown(project_summary(real_data)).splitlines()
        assert lines[0].startswith("| project_id")
        assert set(lines[1]) <= {"|", "-", " "}
        assert len(lines) > 2

    def test_markdown_handles_an_empty_frame(self):
        assert to_markdown(pd.DataFrame()) == "_no rows_"
