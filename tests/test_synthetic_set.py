"""The synthetic set must exercise every rule, and the generated documents
must carry the three promised sections.

The real Kaggle data is structurally clean, so most rules can only be
measured against ``data/synthetic/``.  These tests pin that claim: the folder
exists, every rule R1-R14 fires on it, every ground-truth finding is
reproduced, and both generated documents report the original data, the cleaned
data and the synthetic results as separate sections.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "data" / "synthetic"

#: Every rule id the engine defines; coverage is asserted against this set.
ALL_RULES = {f"R{i}" for i in range(1, 15)}

SECTION_HEADINGS = (
    "## 1. Original Kaggle data",
    "## 2. Cleaned Kaggle data",
    "## 3. Synthetic data",
)


def test_synthetic_folder_holds_the_three_files():
    """The deliverable data folder exists with both tiers and the truth."""
    for name in (
        "synthetic_original_data.csv",
        "synthetic_cleaned_data.csv",
        "synthetic_ground_truth.csv",
    ):
        assert (SYNTHETIC / name).is_file(), f"missing data/synthetic/{name}"


def test_ground_truth_labels_every_rule():
    """One labelled finding per rule, so coverage is not asserted on hope."""
    truth = pd.read_csv(SYNTHETIC / "synthetic_ground_truth.csv")
    assert set(truth["rule_id"]) == ALL_RULES
    assert not truth[["record_key", "rule_id"]].duplicated().any()


def test_every_rule_fires_on_the_synthetic_set(evaluation):
    """R1-R14 must all appear: this is the set's whole reason to exist."""
    synthetic = evaluation.synthetic
    assert set(synthetic["rules_fired"]) == ALL_RULES
    assert synthetic["coverage_pct"] == 100.0
    assert synthetic["rules_total"] == 14


def test_every_labelled_finding_is_reproduced(evaluation):
    """Each planted defect must produce exactly the finding it promises."""
    synthetic = evaluation.synthetic
    assert synthetic["missed_detail"] == []
    assert synthetic["ground_truth_matched"] == synthetic["ground_truth_total"]
    assert synthetic["match_pct"] == 100.0


def test_documents_carry_the_three_sections():
    """README and report both separate original, cleaned and synthetic data."""
    from data_quality.reporting.report import build_readme, build_report

    for document in (build_readme(), build_report()):
        for heading in SECTION_HEADINGS:
            assert heading in document, f"missing {heading!r}"


def test_readme_previews_the_original_data():
    """Section 1 shows the real shape and the literal first ten rows."""
    from data_quality.reporting.report import build_readme

    readme = build_readme()
    assert "### First 10 rows" in readme
    # Two values that only appear in the first ten rows of the Kaggle file.
    assert "Water Sub-contractor" in readme
    assert "Hire of Temporary Fencing" in readme
    # Long source_file cells are truncated by the preview formatter.
    assert "P018 - P01 Airport Carp..." in readme
