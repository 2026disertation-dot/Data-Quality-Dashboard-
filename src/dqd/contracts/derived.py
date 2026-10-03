"""
Derived project-level data contract.

The raw WBS-level contract in :mod:`dqd.contracts.raw` governs what the source
workbooks contain.  This contract governs the *time-phased project record* that
the cleaning stage produces, which is the shape the dashboard reasons about.

Why the derived tier exists
---------------------------
The raw records are cumulative per work package.  A monthly cost record, by
contrast, holds the movement for one reporting period.  Two rules only make
sense on the derived shape:

* cumulative spend must stay within a multiple of cumulative budget
* cumulative spend must not outrun reported progress

Both need a project-level running total across periods, which does not exist at
WBS granularity.

Granularity
-----------
One row per (project_id, time_period).  The real dataset yields 76 such rows
across 8 projects and 14 reporting periods.

Non-negotiables for the derived transform
------------------------------------------
``dqd/preprocess/clean.py`` de-cumulativises the raw series by differencing
consecutive snapshots.  A falling snapshot therefore becomes a *negative period
movement*, which would make every downstream non-negativity rule fire.  The
cleaning stage floors such movements at zero and reports the count; this module
holds the target schema, and the floor is applied upstream in the transform.
"""

import pandera as pa
from pandera import Check, Column

#: Composite key for the derived tier.  Uniqueness is rule R5.
DERIVED_KEY = ["project_id", "time_period"]

#: Period-level movement columns.  These must be non-negative (rule R4).
DERIVED_MONEY_COLUMNS = [
    "pmb_budget",
    "actual_cost",
    "revenue_claimed",
]


def derived_schema(strict: bool = True) -> pa.DataFrameSchema:
    """
    Build the pandera schema for derived project-level records.

    Args:
        strict: When True the schema rejects unexpected extra columns.

    Returns:
        pandera.DataFrameSchema: The derived contract schema.
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
            "time_period": Column(
                str,
                required=True,
                coerce=True,
                nullable=False,
                description="Reporting period label, e.g. Month-3",
            ),
            "pmb_budget": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Period planned budget, de-cumulativised",
            ),
            "actual_cost": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Period actual cost, de-cumulativised",
            ),
            "progress_pct": Column(
                float,
                [Check.ge(0), Check.le(100)],
                required=True,
                coerce=True,
                nullable=False,
                description="Cumulative completion reported for the project",
            ),
            "revenue_claimed": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="Period revenue claimed, de-cumulativised",
            ),
            "actual_date": Column(
                "datetime64[ns]",
                required=True,
                coerce=True,
                nullable=False,
                description="Calendar date of the reporting period",
            ),
            "baseline_start_date": Column(
                "datetime64[ns]",
                required=True,
                coerce=True,
                nullable=False,
                description=(
                    "Project baseline start date; actual_date must not "
                    "precede it (rule R8)"
                ),
            ),
        },
        strict=strict,
        coerce=True,
        drop_invalid_rows=False,
    )


#: Module-level singleton shared by every operating mode.
DERIVED_CONTRACT = derived_schema()