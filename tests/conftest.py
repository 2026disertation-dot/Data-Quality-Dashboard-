"""Shared pytest fixtures and path setup."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
# The package sits at the repository root, so the root itself is what needs to be
# importable.  Streamlit gets this for free because it runs from the project
# directory; pytest needs to be told.
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data"


@pytest.fixture(scope="session")
def raw_data() -> pd.DataFrame:
    """The real WBS-level dataset, exactly as downloaded."""
    return pd.read_csv(DATA / "kaggle_original_data.csv")


@pytest.fixture(scope="session")
def derived_data() -> pd.DataFrame:
    """The real project-level dataset produced by the cleaning stage."""
    return pd.read_csv(DATA / "kaggle_cleaned_data.csv")


@pytest.fixture(scope="session")
def fixtures(raw_data):
    """Derived test sets: batch/incremental split, defects, clean sample."""
    from data_quality.fixtures.builder import build_fixtures

    return build_fixtures(raw_data)


@pytest.fixture(scope="session")
def validator():
    from data_quality.engine.validator import Validator

    return Validator()


@pytest.fixture(scope="session")
def evaluation(raw_data, derived_data, fixtures):
    """The full measured evaluation, computed once per session."""
    from data_quality.reporting.evaluation import evaluate

    return evaluate(raw_data, derived_data, fixtures)
