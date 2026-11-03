"""
Derived project-level data contract.

The raw WBS-level contract in :mod:`data_quality.contracts.raw` governs what the source
workbooks contain.  This contract governs the *time-phased project record* that
the cleaning stage produces, which is the shape the dashboard reasons about.

Why the derived tier exists
---------------------------
The derived records store the same *cumulative* figures as the raw WBS-level
contract, but aggregated from leaf-level work packages up to one row per
project and reporting period.  Keeping them cumulative is what lets the
project-period rules operate on the correct semantics (Chapter 4, Challenge 6):

* cumulative spend must stay within a multiple of cumulative budget (R13)
* cumulative spend must not outrun reported progress (R14)
* cumulative totals must not decrease over time (R9)

Period movements are a display concern only; the dashboard derives them on the
fly for chart readability, but validation always consumes the cumulative
values.

Granularity
-----------
One row per (project_id, time_period).  The real dataset yields 76 such rows
across 8 projects and 14 reporting periods.

Non-negotiables for the derived transform
------------------------------------------
``data_quality/preprocess/clean.py`` aggregates leaf-level WBS records and
stores the summed cumulative planned value, actual cost and earned value
directly as ``pmb_budget``, ``actual_cost`` and ``revenue_claimed``.  It does
**not** de-cumulativise on the validation path: a diverging snapshot must remain
visible to R9 (Chapter 4, Challenge 6).  ``de_cumulativise`` is retained for
dashboard display only.
"""

import pandera as pa
from pandera import Check, Column

#: Composite key for the derived tier.  Uniqueness is rule R5.
DERIVED_KEY = ["project_id", "time_period"]

#: Cumulative monetary columns.  These are the columns rule R9 checks for
#: monotonicity on the project-period view and R13/R14 compare against each
#: other.  They must be non-negative (rule R4).
DERIVED_CUMULATIVE_COLUMNS = [
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
                description=(
                    "CUMULATIVE Performance Measurement Baseline "
                    "(equivalently pv_cum)"
                ),
            ),
            "actual_cost": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="CUMULATIVE actual cost (equivalently ac_cum)",
            ),
            "progress_pct": Column(
                float,
                [Check.ge(0), Check.le(100)],
                required=True,
                coerce=True,
                nullable=False,
                description=(
                    "Progress percentage, derived as "
                    "revenue_claimed / max(pmb_budget) x 100"
                ),
            ),
            "revenue_claimed": Column(
                float,
                Check.ge(0),
                required=True,
                coerce=True,
                nullable=False,
                description="CUMULATIVE earned value (equivalently ev_cum)",
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