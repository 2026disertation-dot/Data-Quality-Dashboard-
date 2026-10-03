"""Repository hygiene: no stale reports, no duplicate figures, no BOMs.

These guard the cleanup itself.  Each one corresponds to something that was
actually wrong at some point, so a regression is caught rather than noticed
months later in the write-up.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_only_one_results_report_exists():
    """One source of truth for measured figures.

    Nine overlapping reports existed, several carrying numbers that contradicted
    the code - one claimed the API was unimplemented and another quoted an
    integrity score from the wrong tier.
    """
    reports = sorted((ROOT / "results").glob("*.md"))
    assert [p.name for p in reports] == ["RESULTS.md"]


def test_figures_are_not_duplicated():
    """No two figures may share identical bytes.

    Five figures existed twice under different names, inflating the apparent
    evidence by a third.
    """
    import hashlib

    figures = sorted((ROOT / "results" / "figures").glob("*.png"))
    digests: dict[str, str] = {}
    for figure in figures:
        digest = hashlib.sha256(figure.read_bytes()).hexdigest()
        assert digest not in digests, (
            f"{figure.name} is byte-identical to {digests[digest]}"
        )
        digests[digest] = figure.name


def test_source_files_have_no_byte_order_mark():
    """A UTF-8 BOM makes a module unimportable by ``ast.parse``."""
    offenders = []
    for path in list(ROOT.glob("*.py")) + list((ROOT / "src").rglob("*.py")):
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            offenders.append(path.name)
    assert not offenders, f"BOM found in: {offenders}"


def test_no_credentials_are_tracked():
    """kaggle.json must never be committed."""
    assert not (ROOT / "kaggle.json").exists()
    assert "kaggle.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_readme_points_at_the_generated_report():
    """The README must not restate numbers the generator owns."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "dqd.reporting.report" in readme
    assert "results/RESULTS.md" in readme


def test_declared_dependencies_are_all_imported():
    """requirements.txt must not list unused runtime packages.

    ``great-expectations``, ``pytz`` and ``openpyxl`` were listed but never
    imported; ``flask`` was imported everywhere but missing, so a clean install
    could not run the API at all.
    """
    import re

    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    declared = {
        re.split(r"[><=]", line)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }
    # The test runner is invoked rather than imported, so exempt it.
    declared.discard("pytest")
    assert declared, "nothing left to check"
    sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in list(ROOT.glob("*.py")) + list((ROOT / "src").rglob("*.py"))
    )
    for package in declared:
        module = package.replace("-", "_")
        # Both spellings occur: ``import pandas`` and ``from flask import Flask``.
        used = f"import {module}" in sources or f"from {module}" in sources
        assert used, f"{package} is declared but unused"
