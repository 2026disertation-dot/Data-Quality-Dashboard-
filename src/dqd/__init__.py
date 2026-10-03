"""Data quality dashboard for WBS cost and progress data.

Layout::

    contracts/   the two data contracts (raw 10-field, derived 8-field)
    engine/      rules R1-R14 and the single shared Validator
    pipeline/    batch and incremental orchestration, dimension scoring
    api/         Flask service (200 accepted / 202 quarantined / 422 rejected)
    fixtures/    controlled defect injection into real records
    preprocess/  download and clean, producing data/*.csv
    reporting/   evaluation, document generation, figures, pipeline runner
    legacy/      the superseded single-tier implementation, kept as baseline
"""
