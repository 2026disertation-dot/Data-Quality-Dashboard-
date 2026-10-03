"""Shared pytest fixtures and path setup."""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
    from dqd.fixtures.builder import build_fixtures

    return build_fixtures(raw_data)


@pytest.fixture(scope="session")
def validator():
    from dqd.engine.validator import Validator

    return Validator()


@pytest.fixture(scope="session")
def evaluation(raw_data, derived_data, fixtures):
    """The full measured evaluation, computed once per session."""
    from dqd.reporting.evaluation import evaluate

    return evaluate(raw_data, derived_data, fixtures)
