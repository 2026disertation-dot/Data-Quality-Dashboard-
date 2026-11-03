"""Impact quantification of detected inconsistencies (spec Section 3.6.8).

Objective 2 asks the study to quantify how the inconsistencies the engine
detects distort three project-control indicators.  Each is computed twice - over
the full derived dataset and over the *clean subset* (records that carry no
finding) - and the difference is reported:

* cost variance, ``CV = EV - AC``
* estimate at completion, ``EAC = BAC / CPI`` with ``CPI = EV / AC``
* portfolio forecasting reliability: total CV, total EAC and the number of
  projects carrying negative CV

The measures are descriptive.  They compare indicators computed from the full
data with those computed from verified-clean records; they are not a causal
claim, and the difference is not read as the sole effect of data-quality
defects.

Two aggregation bases are reported, because the derived contract stores
*cumulative* totals:

* **series total** - the sum of every project-period CV in the frame.  This is
  the literal reading of the specification ("for each project-period record")
  and it is where mid-series distortion is visible.
* **end-state** - each project's latest reported period only.  This is the
  standard EVM point-in-time position and it does not double-count cumulative
  totals.  On this dataset every project's final period is clean, so the
  end-state difference is zero - itself a reported finding.
"""

from __future__ import annotations

import pandas as pd

from ..engine.cross_record_rules import _natural_keys

#: NPV/EVM columns on the derived contract.
EV_COLUMN = "revenue_claimed"
AC_COLUMN = "actual_cost"
BUDGET_COLUMN = "pmb_budget"

#: Composite key of the derived contract.
KEY_COLUMNS = ("project_id", "time_period")


def record_keys(frame: pd.DataFrame) -> list[str]:
    """Return the ``project_id|time_period`` composite key of every row."""
    return [
        "|".join(str(value) for value in row)
        for row in frame[list(KEY_COLUMNS)].itertuples(index=False, name=None)
    ]


def _ordered(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` sorted by project then natural reporting-period order."""
    out = frame.copy()
    out["_order"] = _natural_keys(out["time_period"])
    return out.sort_values(["project_id", "_order"], kind="stable")


def _project_metrics(frame: pd.DataFrame) -> dict[str, dict]:
    """Compute the three indicators per project over one record set."""
    projects: dict[str, dict] = {}
    for project_id, group in _ordered(frame).groupby("project_id", sort=True):
        ev = pd.to_numeric(group[EV_COLUMN], errors="coerce")
        ac = pd.to_numeric(group[AC_COLUMN], errors="coerce")
        budget = pd.to_numeric(group[BUDGET_COLUMN], errors="coerce")

        if ev.dropna().empty or ac.dropna().empty:
            continue

        bac = float(budget.max())            # budget at completion
        end_ev = float(ev.iloc[-1])          # end-state cumulative values
        end_ac = float(ac.iloc[-1])
        cpi = end_ev / end_ac if end_ac else None
        eac = bac / cpi if cpi else None

        projects[project_id] = {
            "periods": int(len(group)),
            "bac": bac,
            "series_cv": float((ev - ac).sum()),
            "end_state_cv": end_ev - end_ac,
            "end_ev": end_ev,
            "end_ac": end_ac,
            "cpi": cpi,
            "eac": eac,
        }
    return projects


def _portfolio_metrics(projects: dict[str, dict]) -> dict:
    """Roll the per-project figures up to the portfolio."""
    eacs = [p["eac"] for p in projects.values() if p["eac"] is not None]
    return {
        "projects": len(projects),
        "series_cv": sum(p["series_cv"] for p in projects.values()),
        "end_state_cv": sum(p["end_state_cv"] for p in projects.values()),
        "total_eac": sum(eacs),
        "negative_cv_projects_series": sum(
            1 for p in projects.values() if p["series_cv"] < 0
        ),
        "negative_cv_projects_end_state": sum(
            1 for p in projects.values() if p["end_state_cv"] < 0
        ),
    }


def _difference(full: float, clean: float) -> dict:
    """Absolute and percentage difference of the clean figure against full."""
    absolute = full - clean
    pct = (absolute / clean * 100.0) if clean else None
    return {"absolute": absolute, "pct": pct}


def impact_quantification(derived: pd.DataFrame, flagged_keys) -> dict:
    """Quantify the impact of detected inconsistencies (Section 3.6.8).

    Args:
        derived: The full derived (project-period) dataset.
        flagged_keys: Record keys carrying at least one finding - precisely the
            rows the clean subset removes.

    Returns:
        dict: Per-project and portfolio indicators for the full dataset and the
        clean subset, together with the difference between them.
    """
    flagged = set(flagged_keys)
    keys = record_keys(derived)
    keep = pd.Series(
        [key not in flagged for key in keys], index=derived.index, dtype=bool
    )

    full_projects = _project_metrics(derived)
    clean_projects = _project_metrics(derived[keep])
    full_portfolio = _portfolio_metrics(full_projects)
    clean_portfolio = _portfolio_metrics(clean_projects)

    portfolio = {
        "full": full_portfolio,
        "clean": clean_portfolio,
        "difference": {
            "series_cv": _difference(
                full_portfolio["series_cv"], clean_portfolio["series_cv"]
            ),
            "end_state_cv": _difference(
                full_portfolio["end_state_cv"], clean_portfolio["end_state_cv"]
            ),
            "total_eac": _difference(
                full_portfolio["total_eac"], clean_portfolio["total_eac"]
            ),
            "negative_cv_projects_series": (
                full_portfolio["negative_cv_projects_series"]
                - clean_portfolio["negative_cv_projects_series"]
            ),
            "negative_cv_projects_end_state": (
                full_portfolio["negative_cv_projects_end_state"]
                - clean_portfolio["negative_cv_projects_end_state"]
            ),
        },
    }

    projects = {
        project_id: {
            "full": full_projects[project_id],
            "clean": clean_projects.get(project_id, {}),
            "difference": _difference(
                full_projects[project_id]["series_cv"],
                clean_projects.get(project_id, {}).get("series_cv", 0.0),
            ),
        }
        for project_id in full_projects
    }

    return {
        "flagged_records": len(flagged),
        "clean_records": int(keep.sum()),
        "portfolio": portfolio,
        "projects": projects,
    }
