"""
Raw WBS-level data contract (Table 4.1).

This contract governs the ten fields that exist in the *original* Kaggle
Project Portfolio Dataset, before any cleaning or aggregation takes place.  It is
the schema the dissertation specifies, and it is the only place where the
structural rules (naming, WBS mapping, source-file traceability) can be
enforced, because ``project_name``, ``source_file``, ``wbs_code`` and
``wbs_description`` do not survive into the derived project-level contract.

Granularity
-----------
One row per (project_id, wbs_code, period_index).  The real dataset holds
2,727 such rows across 8 projects and 82 distinct WBS codes.

Why two contracts
-----------------
The system validates two related but distinct shapes of record:

* the **raw** WBS-level record, governed by :mod:`dqd.contracts.raw`
* the **derived** project-level time-phased record, governed by
  :mod:`dqd.contracts.derived`

Both are enforced by the same rule engine, so a rule behaves identically in
batch mode, incremental mode and through the live API regardless of tier.
"""

import pandas as pd
import pandera as pa
from pandera import Check, Column

# Composite key for the raw tier.  Uniqueness of this key is rule R5.
RAW_KEY = ["project_id", "wbs_code", "period_index"]

# Columns that hold a cumulative cost series.  These must be non-negative (R4)
# and must not decrease over period_index (R9).
RAW_CUMULATIVE_COLUMNS = ["pv_cum", "ac_cum", "ev_cum"]


def raw_schema(strict: bool = True) -> pa.DataFrameSchema:
    """
    Build the pandera schema for raw WBS-level records (Table 4.1).

    Type and range constraints are enforced declaratively by pandera.  Rules
    that require comparing a record against its neighbours (R6, R7, R9, R11)
    cannot be expressed as a per-column check and are enforced by the rule
    engine in :mod:`dqd.engine.rules`.

    Args:
        strict: When True the schema rejects any unexpected extra column.
            This is deliberate: an unrecognised column usually signals a
            malformed upload and should not pass silently.

    Returns:
        pandera.DataFrameSchema: The raw contract schema.
    """
    return pa.DataFrameSchema(
        {
            "project_id": Column(
                str,
                Check.str_matches(r"^P\d{2}$"),
                required=True,
                coerce=True,
                nullable=False,
                description="Project identifier",
            ),
            "project_name": Column(
                str,
                required=True,
                coerce=True,
                nullable=False,
                description="Human-readable project label (rule R6)",
            ),
            "source_file": Column(
                str,
                required=True,
                coerce=True,
                nullable=False,
                description="Originating workbook (rule R11)",
            ),
            "wbs_code": Column(
                str,
                required=True,
                coerce=True,
                nullable=False,
                description=(
                    "Work package code, kept as a string so leading zeros "
                    "survive and codes are never summed"
                ),
            ),
            "wbs_description": Column(
                str,
                required=True,
                coerce=True,
                nullable=False,
                description="Work package label (rules R7, R12)",
            ),
            "period_date": Column(
                "datetime64[ns]",
                required=True,
                coerce=True,
                nullable=False,
                description="Calendar date of the reporting period (rule R8)",
            ),
            "period_index": Column(
                int,
                Check.ge(1),
                required=True,
                coerce=True,
                nullable=False,
                description="Sequential period number (rule R3)",
            ),
            "pv_cum": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Cumulative planned value (rules R4, R9)",
            ),
            "ac_cum": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Cumulative actual cost (rules R4, R9)",
            ),
            "ev_cum": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Cumulative earned value (rules R4, R9)",
            ),
        },
        strict=strict,
        coerce=True,
        # Invalid rows are retained so the engine can report every defect in a
        # record rather than stopping at the first one.
        drop_invalid_rows=False,
    )


#: Module-level singleton so every mode validates against one identical object.
RAW_CONTRACT = raw_schema()