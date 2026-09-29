"""
Figure generation for the data quality dashboard.

The research write-up references a set of figures: the data preview, the
dimension scores, the distributions, the planned-versus-actual comparison, the
cost-variance effect of anomaly treatment, the incremental validation results
and the system-testing summary.  This module produces all of them from the real
Kaggle Project Portfolio data, so the figures in the repository are the ones the
dashboard actually renders rather than hand-made illustrations.

Every figure is written twice: a PNG for the write-up (via kaleido, the static
image engine Plotly uses) and the Plotly figure object is returned so the same
chart can be embedded in the Streamlit app.

Usage::

    python generate_figures.py
    python generate_figures.py --output results/figures
"""

import argparse
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import data_fixtures
from data_fixtures import load_fixtures
from data_pipeline import DataPipeline
from profiling import load_cleaned_data, project_summary, summary_statistics_table
from validation_engine import ValidationEngine

# Where the PNGs are written
DEFAULT_OUTPUT_DIR = os.path.join("results", "figures")

# Consistent house style so the figure set reads as one document.
COLOUR_TEMPLATE = "plotly_white"
ACCENT = "#1f77b4"
GOOD = "#2ecc71"
WARN = "#f39c12"
BAD = "#e74c3c"

# The four dimensions, in the order the research presents them.
DIMENSIONS = ["accuracy", "completeness", "consistency", "integrity"]


def _period_labels(df):
    """
    Order reporting periods naturally rather than as raw strings.

    ``Month-10`` sorts before ``Month-2`` alphabetically, which would scramble
    the time axis, so the numeric suffix is used as the sort key.

    Args:
        df: Frame carrying a ``time_period`` column.

    Returns:
        pd.Series: A categorical series ordered by reporting period.
    """
    if "time_period" not in df.columns:
        return None
    # The contract stores the period label with an arrow-backed string dtype,
    # whose accessor is stricter than the object one, so the numeric suffix is
    # pulled out with plain Python string handling instead.  The categories are
    # de-duplicated explicitly because a label recurs across projects and
    # Categorical rejects repeated categories.
    labels = [str(label) for label in df["time_period"]]
    numbers = [int(label.rpartition("-")[2]) for label in labels]
    seen = {}
    for label, number in zip(labels, numbers):
        seen.setdefault(label, number)
    categories = [label for label, _ in sorted(seen.items(), key=lambda item: item[1])]
    return pd.Categorical(labels, categories=categories, ordered=True)


def figure_data_preview(df, rows=8):
    """
    Figure: the dataset preview the dashboard shows on load.

    Args:
        df: The cleaned cost records.
        rows: How many records to show.

    Returns:
        go.Figure: A table figure of the first ``rows`` records.
    """
    preview = df.head(rows).copy()
    preview["actual_date"] = preview["actual_date"].dt.strftime("%Y-%m-%d")
    preview["baseline_start_date"] = preview["baseline_start_date"].dt.strftime("%Y-%m-%d")
    return go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=list(preview.columns),
                    fill_color=ACCENT,
                    font=dict(color="white", size=12),
                    align="left",
                ),
                cells=dict(
                    values=[preview[column].tolist() for column in preview.columns],
                    align="left",
                ),
            )
        ]
    ).update_layout(
        title=f"Data preview - {len(df)} records across {df['project_id'].nunique()} projects",
        template=COLOUR_TEMPLATE,
    )


def figure_dimension_scores(metrics, targets=None):
    """
    Figure: the four data quality dimension scores against their targets.

    Args:
        metrics: Quality metrics from ``DataPipeline.process_batch``.
        targets: Optional target per dimension, drawn as a marker.

    Returns:
        go.Figure: A horizontal bar chart of the dimension scores.
    """
    if targets is None:
        targets = {"accuracy": 95.0, "completeness": 100.0,
                   "consistency": 95.0, "integrity": 90.0}

    values = [float(metrics.get(dimension, 0.0)) for dimension in DIMENSIONS]
    colours = [GOOD if value >= targets[dimension] else
               (WARN if value >= targets[dimension] - 10 else BAD)
               for value, dimension in zip(values, DIMENSIONS)]

    figure = go.Figure(
        go.Bar(
            x=values,
            y=[dimension.capitalize() for dimension in DIMENSIONS],
            orientation="h",
            marker_color=colours,
            text=[f"{value:.2f}%" for value in values],
            textposition="outside",
        )
    )
    for dimension, value in zip(DIMENSIONS, values):
        figure.add_vline(x=targets[dimension], line_dash="dot", line_color="#555",
                         annotation_text=f"target {targets[dimension]:.0f}%",
                         annotation_position="top")
    figure.update_layout(
        title="Data quality dimension scores",
        xaxis_title="Score (%)",
        yaxis_title="",
        xaxis_range=[0, 115],
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_cost_distribution(df, column="actual_cost"):
    """
    Figure: the distribution of a selected cost variable.

    Args:
        df: The cleaned cost records.
        column: The cost column to plot.

    Returns:
        go.Figure: A histogram of the selected variable.
    """
    figure = px.histogram(
        df, x=column, nbins=30, marginal="box",
        labels={column: f"{column} (currency)"},
        color_discrete_sequence=[ACCENT],
    )
    figure.update_layout(
        title=f"Distribution of {column}",
        template=COLOUR_TEMPLATE,
        showlegend=False,
    )
    return figure


def figure_summary_statistics(stats):
    """
    Figure: mean, median and mode for each cost variable.

    Args:
        stats: Summary statistics from ``profiling.summary_statistics_table``.

    Returns:
        go.Figure: A grouped bar chart of central tendency per variable.
    """
    frame = stats.reset_index().rename(columns={"index": "field"})
    melted = frame.melt(
        id_vars="field", value_vars=["mean", "median", "mode"],
        var_name="statistic", value_name="value",
    )
    figure = px.bar(
        melted, x="field", y="value", color="statistic", barmode="group",
        labels={"field": "Variable", "value": "Value", "statistic": "Statistic"},
        color_discrete_sequence=[ACCENT, WARN, GOOD],
    )
    figure.update_layout(title="Summary statistics by variable", template=COLOUR_TEMPLATE)
    return figure


def figure_planned_vs_actual(df, project=None):
    """
    Figure: cumulative planned value against cumulative actual cost over time.

    This is the multi-project cost comparison the research describes: each
    project should track its baseline, and a divergence is either genuine cost
    performance or a data quality defect.

    Args:
        df: The cleaned cost records.
        project: Optional single project to show. None shows every project.

    Returns:
        go.Figure: A line chart of planned versus actual cost.
    """
    frame = df if project is None else df[df["project_id"] == project]
    ordered = frame.sort_values(["project_id", "actual_date"]).copy()
    ordered["period"] = _period_labels(ordered)

    wide = ordered.groupby(["project_id", "period"], observed=True, as_index=False).agg(
        actual_date=("actual_date", "max"),
        planned=("pmb_budget", "sum"),
        actual=("actual_cost", "sum"),
    )

    figure = go.Figure()
    for project_id in sorted(wide["project_id"].unique()):
        series = wide[wide["project_id"] == project_id].sort_values("actual_date")
        figure.add_trace(go.Scatter(
            x=series["actual_date"], y=series["planned"].cumsum(),
            name=f"{project_id} planned", mode="lines+markers",
            line=dict(dash="dot"),
        ))
        figure.add_trace(go.Scatter(
            x=series["actual_date"], y=series["actual"].cumsum(),
            name=f"{project_id} actual", mode="lines+markers",
        ))

    figure.update_layout(
        title="Cumulative planned value vs actual cost"
              + (f" - {project}" if project else " - all projects"),
        xaxis_title="Reporting month",
        yaxis_title="Cumulative cost",
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_project_summary(summary):
    """
    Figure: budget against actual cost at project level.

    Args:
        summary: Output of ``profiling.project_summary``.

    Returns:
        go.Figure: A grouped bar chart per project.
    """
    melted = summary.melt(
        id_vars="project_id",
        value_vars=["total_pmb_budget", "total_actual_cost", "total_revenue_claimed"],
        var_name="measure", value_name="value",
    )
    melted["measure"] = melted["measure"].map({
        "total_pmb_budget": "PMB budget",
        "total_actual_cost": "Actual cost",
        "total_revenue_claimed": "Revenue claimed",
    })
    figure = px.bar(
        melted, x="project_id", y="value", color="measure", barmode="group",
        labels={"project_id": "Project", "value": "Total (currency)"},
        color_discrete_sequence=[ACCENT, BAD, GOOD],
    )


def figure_anomaly_breakdown(results):
    """
    Figure: how many findings the engine raised in each anomaly category.

    Args:
        results: Output of ``ValidationEngine.validate_batch``.

    Returns:
        go.Figure: A bar chart of the per-category finding counts.
    """
    summary = results.get("summary", {})
    labels = {
        "missing_count": "Missing values",
        "type_error_count": "Type errors",
        "bounds_violation_count": "Bounds violations",
        "logical_anomaly_count": "Logical anomalies",
        "duplicate_count": "Duplicates",
    }
    keys = list(labels)
    values = [int(summary.get(key, 0)) for key in keys]

    figure = go.Figure(go.Bar(
        x=[labels[key] for key in keys],
        y=values,
        marker_color=[BAD if value else GOOD for value in values],
        text=[str(value) for value in values],
        textposition="outside",
    ))
    figure.update_layout(
        title="Validation findings by anomaly category",
        xaxis_title="Category",
        yaxis_title="Findings",
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_incremental_validation(ground_truth, results):
    """
    Figure: what the dashboard reports when malformed records arrive.

    Args:
        ground_truth: The defects injected into the test set.
        results: Validation output for that set.

    Returns:
        go.Figure: A grouped bar chart of detected versus injected defects.
    """
    injected = ground_truth["anomaly_name"].value_counts()
    detected_rows = {entry["row_index"]
                     for entries in results.get("anomalies", {}).values()
                     for entry in (entries or [])}
    detected = ground_truth[ground_truth["row_index"].isin(detected_rows)][
        "anomaly_name"].value_counts()

    names = sorted(set(injected.index) | set(detected.index))
    figure = go.Figure([
        go.Bar(x=names, y=[int(injected.get(name, 0)) for name in names],
               name="Injected", marker_color=ACCENT),
        go.Bar(x=names, y=[int(detected.get(name, 0)) for name in names],
               name="Detected", marker_color=GOOD),
    ])
    figure.update_layout(
        title="Incremental validation: injected versus detected defects",
        xaxis_title="Injected defect",
        yaxis_title="Count",
        barmode="group",
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_system_testing(evidence, targets):
    """
    Figure: the system-testing measures against their targets.

    Each measure is normalised to a percentage of its target so they can share
    one axis: detection completeness and regression consistency are "higher is
    better", while load time and the false-positive rate are "lower is better".

    Args:
        evidence: The measured evidence from ``run_pipeline.measure``.
        targets: The target values, keyed as in the report.

    Returns:
        go.Figure: A bar chart of attainment against target.
    """
    rows = [
        ("Detection completeness",
         evidence["detection"]["detection_completeness_pct"],
         targets["detection_completeness"], True),
        ("Regression consistency",
         evidence["regression"]["rate_pct"], 100.0, True),
        ("False positive rate",
         evidence["false_positive_rate_pct"], targets["false_positive"], False),
        ("Batch load time",
         evidence["batch_seconds"], targets["performance_seconds"], False),
    ]

    attainment = []
    for _, value, target, higher_is_better in rows:
        if higher_is_better:
            score = value / target * 100.0 if target else 0.0
        else:
            score = target / value * 100.0 if value else 100.0
        attainment.append(min(score, 130.0))

    figure = go.Figure(go.Bar(
        x=[row[0] for row in rows],
        y=attainment,
        marker_color=[GOOD if score >= 100 else BAD for score in attainment],
        text=[f"{row[1]:.2f}" for row in rows],
        textposition="outside",
        hovertemplate="%{x}<br>attainment %{y:.1f}% of target<extra></extra>",
    ))
    figure.add_hline(y=100, line_dash="dot", line_color="#555",
                     annotation_text="target")
    figure.update_layout(
        title="System testing: attainment against target",
        xaxis_title="Measure",
        yaxis_title="Percent of target met",
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_cost_variance_effect(cleaned, flagged_rows):
    """
    Figure: cost variance before and after the flagged records are removed.

    Quantifies what the detected inconsistencies actually cost: the variance
    computed on the records as they arrived, against the variance computed on the
    records that survive validation.

    Args:
        cleaned: The real cleaned cost records.
        flagged_rows: Row indices the engine flagged.

    Returns:
        go.Figure: Overlaid histograms of the two variance distributions.
    """
    frame = cleaned.copy()
    frame["cost_variance"] = frame["revenue_claimed"] - frame["actual_cost"]
    treated = frame.drop(index=[i for i in flagged_rows if i in frame.index])

    figure = go.Figure()
    figure.add_histogram(
        x=frame["cost_variance"], name="As received", nbinsx=40,
        opacity=0.55, marker_color=BAD,
    )
    figure.add_histogram(
        x=treated["cost_variance"], name="After anomaly treatment", nbinsx=40,
        opacity=0.55, marker_color=GOOD,
    )
    figure.update_layout(
        title="Cost variance distribution before and after anomaly treatment",
        xaxis_title="Cost variance (revenue claimed - actual cost)",
        yaxis_title="Records",
        barmode="overlay",
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_pipeline_workflow(fixtures):
    """
    Figure: the dual-mode pipeline, from ingest through validation to reporting.

    Args:
        fixtures: The real-data fixtures, used for the record counts.

    Returns:
        go.Figure: A flow diagram of the batch and incremental paths.
    """
    batch_count = len(fixtures["batch"])
    incremental_count = len(fixtures["incremental"])

    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=[0, 1, 2, 2, 1, 0], y=[0, 0, 0.6, 1.4, 1, 0],
        mode="lines", line=dict(color="#999", width=1), hoverinfo="skip",
        showlegend=False,
    ))

    nodes = [
        (0, 0, "Kaggle\nworkbooks", "16 workbooks"),
        (1, 0, "EVM\nextraction", f"{len(fixtures['cleaned'])} projects"),
        (2, 0.6, f"Batch mode\n{batch_count} records", "history"),
        (2, 1.4, f"Incremental mode\n{incremental_count} records", "new arrivals"),
        (1, 1, "Validation\nengine", "5 rule families"),
        (0, 1, "Diagnostics\nand report", "dashboard"),
    ]
    figure.add_trace(go.Scatter(
        x=[node[0] for node in nodes],
        y=[node[1] for node in nodes],
        mode="markers+text",
        marker=dict(size=46, color=ACCENT, symbol="circle"),
        text=[node[2] for node in nodes],
        textposition="middle center",
        hovertext=[node[3] for node in nodes],
        hoverinfo="text",
        textfont=dict(color="white", size=10),
        showlegend=False,
    ))

    figure.update_layout(
        title="Dual-mode pipeline: batch and incremental processing",
        xaxis=dict(visible=False, range=[-0.5, 2.5]),
        yaxis=dict(visible=False, range=[-0.4, 1.8]),
        template=COLOUR_TEMPLATE,
    )
    return figure


def figure_project_summary(summary):
    """
    Figure: budget against actual cost at project level.

    Args:
        summary: Output of ``profiling.project_summary``.

    Returns:
        go.Figure: A grouped bar chart per project.
    """
    melted = summary.melt(
        id_vars="project_id",
        value_vars=["total_pmb_budget", "total_actual_cost", "total_revenue_claimed"],
        var_name="measure", value_name="value",
    )
    melted["measure"] = melted["measure"].map({
        "total_pmb_budget": "PMB budget",
        "total_actual_cost": "Actual cost",
        "total_revenue_claimed": "Revenue claimed",
    })
    figure = px.bar(
        melted, x="project_id", y="value", color="measure", barmode="group",
        labels={"project_id": "Project", "value": "Total (currency)"},
        color_discrete_sequence=[ACCENT, BAD, GOOD],
    )
    figure.update_layout(title="Project cost summary", template=COLOUR_TEMPLATE)
    return figure


def save_figure(figure, name, directory=DEFAULT_OUTPUT_DIR):
    """
    Write a figure to a PNG and return the path.

    Args:
        figure: The Plotly figure to export.
        name: File stem for the PNG.
        directory: Destination directory, created when missing.

    Returns:
        str: The path written.
    """
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.png")
    figure.write_image(path, width=1400, height=800, scale=2)
    return path


def build_all_figures(cleaned, fixtures, evidence, targets, directory=DEFAULT_OUTPUT_DIR):
    """
    Build and export the whole figure set from the real data.

    Args:
        cleaned: The real cleaned cost records.
        fixtures: Real-data fixtures.
        evidence: Measured evidence from ``run_pipeline.measure``.
        targets: System-testing targets.
        directory: Where the PNGs are written.

    Returns:
        dict: Figure name to written path.
    """
    engine = ValidationEngine()
    pipeline = DataPipeline()

    clean_results = engine.validate_batch(cleaned)
    anomaly_results = engine.validate_batch(fixtures["anomaly_set"])
    metrics = pipeline.process_batch(cleaned)["quality_metrics"]
    flagged = sorted({entry["row_index"]
                      for entry in clean_results["anomalies"]["logical_anomalies"]})

    figures = {
        "fig01_data_preview": figure_data_preview(cleaned),
        "fig02_dimension_scores": figure_dimension_scores(metrics),
        "fig03_cost_distribution": figure_cost_distribution(cleaned, "actual_cost"),
        "fig04_summary_statistics": figure_summary_statistics(
            summary_statistics_table(cleaned)),
        "fig05_planned_vs_actual": figure_planned_vs_actual(cleaned),
        "fig06_project_summary": figure_project_summary(project_summary(cleaned)),
        "fig07_anomaly_breakdown": figure_anomaly_breakdown(clean_results),
        "fig08_incremental_validation": figure_incremental_validation(
            fixtures["ground_truth"], anomaly_results),
        "fig09_system_testing": figure_system_testing(evidence, targets),
        "fig10_cost_variance_effect": figure_cost_variance_effect(cleaned, flagged),
        "fig11_pipeline_workflow": figure_pipeline_workflow(fixtures),
    }

    written = {}
    for name, figure in figures.items():
        path = save_figure(figure, name, directory=directory)
        written[name] = path
        print(f"  wrote {path}")
    return written


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(
        description="Generate the research figure set from the real Kaggle data."
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT_DIR,
                        help="Directory to write the PNG figures into")
    args = parser.parse_args()

    cleaned = load_cleaned_data()
    fixtures = load_fixtures()
    if cleaned is None or fixtures is None:
        return 1

    from run_pipeline import (DETECTION_COMPLETENESS_TARGET,
                             PERFORMANCE_TARGET_SECONDS, measure)

    targets = {
        "detection_completeness": DETECTION_COMPLETENESS_TARGET,
        "false_positive": 5.0,
        "performance_seconds": PERFORMANCE_TARGET_SECONDS,
    }

    print("Measuring the dashboard on the real data...")
    evidence = measure(cleaned, fixtures)
    print("Building figures...")
    written = build_all_figures(cleaned, fixtures, evidence, targets,
                                directory=args.output)
    print(f"\nWrote {len(written)} figures to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
