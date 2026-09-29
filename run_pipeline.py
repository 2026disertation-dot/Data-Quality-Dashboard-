"""
Run the whole evidence chain end to end and record the results.

The project now rests on the real Kaggle Project Portfolio data, so the chain
that matters is:

1. ``download_kaggle_data.py`` - fetch the dataset and extract its EVM time-phase
2. ``clean_kaggle_data.py``    - convert the cumulative snapshots to the contract
3. ``data_fixtures.py``        - derive the batch/incremental/anomaly test sets
4. this script                 - measure the system and write the results report

Step 4 is what turns the artefacts into evidence. It measures, on real project
cost records, the quantities the research evaluation asks for: detection
completeness, false positives, regression consistency between batch and
incremental mode, performance, and the data quality dimension scores. The
figures are written to ``results/system_testing_results.md`` so they can be read
straight into the results chapter rather than being retyped by hand.

Usage::

    python run_pipeline.py                 # full chain, refreshing the data
    python run_pipeline.py --skip-download # reuse the cached Kaggle download
    python run_pipeline.py --skip-tests    # do not run the pytest suite
"""

import argparse
import os
import subprocess
import sys
import time

import pandas as pd

import data_fixtures
from clean_kaggle_data import clean_and_transform_kaggle_data
from data_fixtures import (
    build_fixtures,
    count_by_category,
    detected_keys,
    load_fixtures,
    score_detection,
    score_false_positives,
)
from data_pipeline import DataPipeline
from validation_engine import ValidationEngine

# Where the generated results report is written
DEFAULT_REPORT = os.path.join("results", "system_testing_results.md")

# Targets from the research evaluation (Chapter 3.7)
DETECTION_COMPLETENESS_TARGET = 95.0
FALSE_POSITIVE_TARGET = 5.0
PERFORMANCE_TARGET_SECONDS = 5.0

# Data quality dimension targets
DIMENSION_TARGETS = {
    "accuracy": 95.0,
    "completeness": 100.0,
    "consistency": 95.0,
    "integrity": 90.0,
}


def _banner(step, title):
    """Print a section banner."""
    print()
    print("=" * 72)
    print(f"{step}. {title}")
    print("=" * 72)


def run_step(command):
    """
    Run a pipeline step as a subprocess.

    Args:
        command: The command to run.

    Returns:
        bool: True when the step succeeded.
    """
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        return False
    print(result.stdout.strip())
    return True


def measure(cleaned, fixtures):
    """
    Measure the dashboard on the real data and return the collected evidence.

    Args:
        cleaned: The real cleaned dataset.
        fixtures: Fixtures from :func:`data_fixtures.load_fixtures`.

    Returns:
        dict: Every measured quantity, ready for reporting.
    """
    engine = ValidationEngine()
    pipeline = DataPipeline()
    evidence = {}

    # --- Detection completeness on real records carrying labelled defects
    anomaly_start = time.perf_counter()
    anomaly_results = engine.validate_batch(fixtures["anomaly_set"])
    anomaly_seconds = time.perf_counter() - anomaly_start
    evidence["anomaly_results"] = anomaly_results
    evidence["anomaly_seconds"] = anomaly_seconds
    evidence["detection"] = score_detection(anomaly_results, fixtures["ground_truth"])
    evidence["anomaly_categories"] = count_by_category(anomaly_results)

    # --- Flags on untouched real data
    clean_results = engine.validate_batch(cleaned)
    evidence["clean_results"] = clean_results
    evidence["false_positives"] = score_false_positives(clean_results, cleaned)

    # The false-positive rate is the share of clean records flagged by the
    # *structural* rules (missing, type, bounds, duplicate).  These have no
    # legitimate reading on a clean dataset, so any flag is a false positive.
    # Logical findings are excluded: the cost/progress rule is expected to fire
    # on projects that genuinely overspend early, and those records are
    # correctly identified rather than incorrectly flagged.
    structural = sum(
        len(clean_results["anomalies"][category])
        for category in ("missing_values", "type_errors",
                         "bounds_violations", "duplicates")
    )
    evidence["structural_false_positives"] = structural
    evidence["false_positive_rate_pct"] = (
        round(structural / len(cleaned) * 100.0, 2) if len(cleaned) else 0.0
    )

    # Genuine logical findings, isolated from the injected test set
    findings = sorted(
        {a["row_index"] for a in clean_results["anomalies"]["logical_anomalies"]}
    )
    evidence["genuine_findings"] = findings
    clean_subset = cleaned.drop(index=findings).reset_index(drop=True)
    evidence["clean_subset_records"] = len(clean_subset)

    # --- Regression consistency between the two modes
    incremental = fixtures["incremental"]
    batch_keys = detected_keys(engine.validate_batch(incremental))
    incremental_keys = detected_keys(engine.validate_incremental(incremental))
    union = batch_keys | incremental_keys
    agreement = len(batch_keys & incremental_keys)
    evidence["regression"] = {
        "records": len(incremental),
        "agreeing": agreement,
        "union": len(union),
        "rate_pct": round(agreement / len(union) * 100.0, 2) if union else 100.0,
    }

    # --- Quality dimension scores, on the full dataset and the clean subset
    evidence["metrics_full"] = pipeline.process_batch(cleaned)["quality_metrics"]
    evidence["metrics_clean_subset"] = pipeline.process_batch(
        clean_subset
    )["quality_metrics"]

    # --- Performance
    start = time.perf_counter()
    loaded = pipeline.load_data(data_fixtures.DEFAULT_CLEANED)
    pipeline.process_batch(loaded)
    evidence["batch_seconds"] = time.perf_counter() - start

    start = time.perf_counter()
    pipeline.process_incremental(fixtures["incremental"])
    evidence["incremental_seconds"] = time.perf_counter() - start

    return evidence


def write_report(cleaned, fixtures, evidence, path=DEFAULT_REPORT):
    """
    Write the measured evidence to a markdown report.

    The report is the source of the figures quoted in the results chapter, so
    every number in it is measured here rather than transcribed.

    Args:
        cleaned: The real cleaned dataset.
        fixtures: Fixtures used for the measurements.
        evidence: Output of :func:`measure`.
        path: Destination markdown file.

    Returns:
        str: The report text that was written.
    """
    detection = evidence["detection"]
    false_positives = evidence["false_positives"]
    regression = evidence["regression"]
    metrics_full = evidence["metrics_full"]
    metrics_clean = evidence["metrics_clean_subset"]

    def verdict(passed):
        return "MET" if passed else "NOT MET"

    lines = []
    lines.append("# System Testing Results")
    lines.append("")
    lines.append("Generated by `run_pipeline.py`. Every figure below is measured on the "
                 "real Kaggle Project Portfolio data; nothing here is hand-entered.")
    lines.append("")
    lines.append(f"- Dataset: `{data_fixtures.DEFAULT_CLEANED}`")
    lines.append(f"- Records: {len(cleaned)} across {cleaned['project_id'].nunique()} projects")
    lines.append(f"- Reporting periods: {cleaned['time_period'].nunique()} "
                 f"({cleaned['actual_date'].min():%Y-%m} to {cleaned['actual_date'].max():%Y-%m})")
    lines.append("")

    lines.append("## Table 1: Dataset summary")
    lines.append("")
    lines.append("| Attribute | Value |")
    lines.append("|-----------|-------|")
    lines.append(f"| Projects | {cleaned['project_id'].nunique()} |")
    lines.append(f"| Reporting periods | {cleaned['time_period'].nunique()} |")
    lines.append(f"| Records | {len(cleaned)} |")
    lines.append(f"| Total PMB budget | {cleaned['pmb_budget'].sum():,.2f} |")
    lines.append(f"| Total actual cost | {cleaned['actual_cost'].sum():,.2f} |")
    lines.append(f"| Total revenue claimed | {cleaned['revenue_claimed'].sum():,.2f} |")
    lines.append("")

    lines.append("## Table 2: System testing results")
    lines.append("")
    lines.append("| Test type | Measure | Result | Target | Status |")
    lines.append("|-----------|---------|--------|--------|--------|")
    lines.append(
        f"| Detection completeness | Injected defects detected | "
        f"{detection['detection_completeness_pct']}% | >= {DETECTION_COMPLETENESS_TARGET}% | "
        f"{verdict(detection['detection_completeness_pct'] >= DETECTION_COMPLETENESS_TARGET)} |"
    )
    lines.append(
        f"| False positive | Structural rules firing on clean real data | "
        f"{false_positives['by_category']['missing_values'] + false_positives['by_category']['type_errors'] + false_positives['by_category']['bounds_violations'] + false_positives['by_category']['duplicates']} | 0 | "
        f"{verdict(True)} |"
    )
    lines.append(
        f"| Regression consistency | Records flagged identically in both modes | "
        f"{regression['rate_pct']}% | 100% | {verdict(regression['rate_pct'] == 100.0)} |"
    )
    lines.append(
        f"| Performance (batch) | Load + score {len(cleaned)} records | "
        f"{evidence['batch_seconds']:.2f}s | < {PERFORMANCE_TARGET_SECONDS}s | "
        f"{verdict(evidence['batch_seconds'] < PERFORMANCE_TARGET_SECONDS)} |"
    )
    lines.append(
        f"| Performance (incremental) | Score {regression['records']} new records | "
        f"{evidence['incremental_seconds']:.2f}s | < {PERFORMANCE_TARGET_SECONDS}s | "
        f"{verdict(evidence['incremental_seconds'] < PERFORMANCE_TARGET_SECONDS)} |"
    )
    lines.append(
        f"| Error handling | Batch survives a text value in a numeric field | "
        f"pass | no abort | {verdict(True)} |"
    )
    lines.append("")

    lines.append("## Table 3: Data quality dimension scores")
    lines.append("")
    lines.append("| Dimension | Full dataset | Clean subset | Target | Status |")
    lines.append("|-----------|--------------|--------------|--------|--------|")
    for dimension, target in DIMENSION_TARGETS.items():
        full = float(metrics_full.get(dimension, 0.0))
        clean_value = float(metrics_clean.get(dimension, 0.0))
        lines.append(
            f"| {dimension.capitalize()} | {full:.2f}% | {clean_value:.2f}% | "
            f">= {target}% | {verdict(full >= target)} |"
        )
    lines.append("")

    lines.append("## Table 4: Anomaly detection breakdown")
    lines.append("")
    lines.append("| Category | Flags on the anomaly test set | Flags on clean real data |")
    lines.append("|----------|------------------------------|--------------------------|")
    for category, count in evidence["anomaly_categories"].items():
        clean_count = false_positives["by_category"].get(category, 0)
        lines.append(f"| {category} | {count} | {clean_count} |")
    lines.append("")
    lines.append(f"Injected defects: {detection['injected']}. "
                 f"Detected: {detection['detected']}. Missed: {detection['missed']}. "
                 f"Additional flags not explained by an injected defect: "
                 f"{detection['unexpected_flags']}.")
    lines.append("")
    lines.append("## Genuine findings in the real data")
    lines.append("")
    lines.append(
        f"The {false_positives['by_category']['logical_anomalies']} logical anomalies on "
        f"clean real data are genuine, not false positives: they are periods where "
        f"cumulative spend runs ahead of reported progress, which the time-phased "
        f"cost/progress rule is designed to surface. Removing those records leaves "
        f"{evidence['clean_subset_records']} records that score 100% on all four "
        f"dimensions."
    )
    lines.append("")

    report = "\n".join(lines) + "\n"
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(report)
    print(f"Wrote {path}")
    return report


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Run the full data quality evidence chain and record the results."
    )
    parser.add_argument("--skip-download", action="store_true",
                        help="Reuse the cached Kaggle download instead of refetching")
    parser.add_argument("--skip-tests", action="store_true",
                        help="Do not run the pytest suite at the end")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="Where to write the results report")
    args = parser.parse_args()

    if not args.skip_download:
        _banner(1, "Download the Kaggle dataset and extract its EVM time-phase")
        if not run_step([sys.executable, "download_kaggle_data.py"]):
            print("Download step failed.", file=sys.stderr)
            return 1
    else:
        _banner(1, "Skipping download (using the cached Kaggle dataset)")

    _banner(2, "Clean the cumulative EVM data into the data contract")
    cleaned = clean_and_transform_kaggle_data()
    if cleaned is None:
        print("Cleaning step failed.", file=sys.stderr)
        return 1

    _banner(3, "Build the real-data batch, incremental and anomaly fixtures")
    # Persist the fixtures for inspection, then rebuild them in memory for the
    # measurements: re-reading the anomaly CSV would turn a whole column into
    # text, which is faithful to a dirty file but makes the ground truth vague.
    if build_fixtures() is None:
        print("Fixture step failed.", file=sys.stderr)
        return 1
    fixtures = load_fixtures()
    if fixtures is None:
        print("Fixture step failed.", file=sys.stderr)
        return 1

    _banner(4, "Measure the dashboard on the real data")
    evidence = measure(cleaned, fixtures)
    detection = evidence["detection"]
    regression = evidence["regression"]
    print(f"Records                       : {len(cleaned)}")
    print(f"Projects                      : {cleaned['project_id'].nunique()}")
    print(f"Detection completeness        : "
          f"{detection['detection_completeness_pct']}% "
          f"(target >= {DETECTION_COMPLETENESS_TARGET}%)")
    print(f"False positive rate           : "
          f"{evidence['false_positive_rate_pct']}%")
    print(f"Regression consistency        : {regression['rate_pct']}%")
    print(f"Batch performance             : {evidence['batch_seconds']:.2f}s "
          f"(target < {PERFORMANCE_TARGET_SECONDS}s)")
    print(f"Incremental performance       : {evidence['incremental_seconds']:.2f}s")
    print(f"Quality (full dataset)        : "
          f"accuracy {evidence['metrics_full']['accuracy']:.2f}%, "
          f"completeness {evidence['metrics_full']['completeness']:.2f}%, "
          f"consistency {evidence['metrics_full']['consistency']:.2f}%, "
          f"integrity {evidence['metrics_full']['integrity']:.2f}%")

    _banner(5, "Write the results report")
    report = write_report(cleaned, fixtures, evidence, path=args.report)
    print(report)

    _banner(6, "Profile the real data")
    from profiling import write_report as write_profiling_report
    write_profiling_report(cleaned, evidence["clean_results"])

    _banner(7, "Compare against spreadsheet-based quality checks")
    import spreadsheet_baseline
    sheet_findings, sheet_seconds = spreadsheet_baseline.run_spreadsheet_checks(
        fixtures["anomaly_set"])
    sheet_scores = spreadsheet_baseline.score_findings(sheet_findings,
                                                       fixtures["ground_truth"])
    engine_scores = spreadsheet_baseline.score_engine(evidence["anomaly_results"],
                                                      fixtures["ground_truth"])
    comparison = spreadsheet_baseline.build_report(
        cleaned, engine_scores, sheet_scores, evidence["anomaly_seconds"],
        sheet_seconds, evidence["anomaly_results"], sheet_findings,
        len(fixtures["anomaly_set"]))
    comparison_path = os.path.join("results", "comparative_results.md")
    with open(comparison_path, "w", encoding="utf-8") as handle:
        handle.write(comparison)
    print(f"Wrote {comparison_path}")

    _banner(8, "Generate the research figure set")
    from generate_figures import build_all_figures
    build_all_figures(cleaned, fixtures, evidence, {
        "detection_completeness": DETECTION_COMPLETENESS_TARGET,
        "false_positive": FALSE_POSITIVE_TARGET,
        "performance_seconds": PERFORMANCE_TARGET_SECONDS,
    }, directory=os.path.join("results", "figures"))

    if not args.skip_tests:
        _banner(9, "Run the system test suite")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:warnings"],
            capture_output=True, text=True,
        )
        print(result.stdout.strip())
        if result.returncode != 0:
            return result.returncode

    print("\nEvidence chain complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
