"""
Data Quality Dashboard for Multi-Project Cost Management
Main Streamlit application (Section 4.7).

Uses the shared :class:`~data_quality.engine.validator.Validator` from
``data_quality.engine.validator``, ensuring identical validation logic between
the dashboard, the batch engine, incremental mode and the live API.  Thresholds
are loaded from ``config/rules.yaml`` (R-DQ6, §4.8.1) so that the dashboard's
display targets stay synchronised with the rule engine's pass/fail logic: change
a threshold in the YAML and both the engine and the display follow.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_quality.config.loader import load_config
from data_quality.engine.findings import summarise_counts
from data_quality.engine.validator import Validator
from data_quality.pipeline.quality import score_dimensions

# Shared colour palette.
#
# These are the same tokens as .streamlit/config.toml, so the chrome, the CSS
# and the charts are guaranteed to agree.  Keeping them in one place means a
# palette change happens once rather than drifting between the app and the
# figure-export module.
ACCENT = "#007AFF"      # blue - primary series
GOOD = "#34C759"        # green - within target / valid
WARN = "#FF9F0A"        # amber - attention
BAD = "#FF3B30"         # red   - out of target / invalid
NEUTRAL = "#8E8E93"     # grey  - reference lines
GRID = "#E5E5EA"        # light grey - axis and grid lines
INK = "#1D1D1F"         # near-black - text
MUTED = "#6E6E73"       # grey - secondary text
SURFACE = "#FFFFFF"     # card background

# Sequential blue ramp for multi-series charts.  These read as one family
# rather than the unrelated pastels a default palette would produce.
SERIES_COLORS = ["#007AFF", "#0057B8", "#66B5FF", "#5AC8FA",
                 "#8E8E93", "#C7C7CC", "#AF52DE", "#E5E5EA"]

# A restrained Plotly template matching the Streamlit theme.
#
# NOTE: ``title`` is deliberately absent.  Supplying a title object here forces
# Plotly to stop reserving top margin for the title, which pushed the gauge's
# arc outside the canvas.  Each figure sets its own title as a string, and
# Plotly's own auto-margin then reserves the correct space.
PLOT_LAYOUT = {
    "template": "plotly_white",
    "paper_bgcolor": SURFACE,
    "plot_bgcolor": SURFACE,
    "font": {"family": "Segoe UI, Roboto, Helvetica, Arial, sans-serif",
             "color": INK, "size": 12},
    "margin": {"t": 55, "b": 45, "l": 60, "r": 25},
}

#: The six analysis tabs mandated by Table 4.5.  Kept as a constant so the tab
#: order can never silently drift from the specification.
TABS = ["Data Preview", "Metric Table", "Metric Graph",
        "Distribution", "Summary Statistics", "Cost Variance"]

#: Monetary columns per tier.  The derived contract stores cumulative values, so
#: cost variance on the derived tier is cumulative budget minus cumulative
#: actual.  On the raw (WBS-level) tier the equivalents are pv_cum / ac_cum.
COST_COLUMNS = {
    "raw": ("pv_cum", "ac_cum"),
    "derived": ("pmb_budget", "actual_cost"),
}


def period_sort_key(periods):
    """Build a natural sort key for ``time_period`` labels.

    Labels such as ``Week-2`` or ``Month-10`` sort incorrectly as plain strings
    (``"Month-10"`` sorts before ``"Month-2"``), which would scramble the time
    axis of the cost charts.  Splitting each label into its prefix and numeric
    suffix keeps the reporting periods in chronological order.
    """
    def key(label):
        text = str(label)
        prefix, separator, number = text.rpartition("-")
        if separator and number.isdigit():
            return (prefix, int(number), "")
        return (text, 0, "")

    return pd.Series([key(label) for label in periods],
                     index=periods.index, dtype=object)


# Page configuration
st.set_page_config(
    page_title="Data Quality Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling.
#
# Streamlit's own theme (see .streamlit/config.toml) sets the base palette; the
# rules here handle what a theme cannot express: the header treatment, card
# surfaces, tightened vertical rhythm and consistent alignment.  Colours are the
# same tokens as the theme file so the interface and the charts agree.
CSS_BASE = """
<style>
    /* Typography */
    html, body, [class*="css"] {
        font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
    }

    /* Page header */
    .main-header {
        font-size: 1.75rem;
        font-weight: 600;
        letter-spacing: -0.02em;      /* tighter tracking reads as larger */
        color: #1D1D1F;
        text-align: left;
        padding: 0 0 0.25rem 0;
        margin: 0 0 0.75rem 0;
    }

    /* A thin rule separates the title from the content without the
       heaviness of a full-width border. */
    .main-header::after {
        content: "";
        display: block;
        width: 100%;
        height: 1px;
        margin-top: 0.9rem;
        background: #D8D8DC;
    }

    .page-subtitle {
        color: #6E6E73;
        font-size: 0.95rem;
        margin: 0 0 1.5rem 0;
        padding: 0;
    }

    /* Metric cards */
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 12px;
        padding: 1rem 1.15rem;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    }

    div[data-testid="stMetricLabel"] p {
        color: #6E6E73;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: 0.01em;
        text-transform: uppercase;
    }

    div[data-testid="stMetricValue"] {
        color: #1D1D1F;
        font-size: 1.65rem;
        font-weight: 600;
        letter-spacing: -0.02em;
    }

    div[data-testid="stMetricDelta"] { font-size: 0.8rem; }

    /* Tabs */
    button[data-baseweb="tab"] {
        font-size: 0.92rem;
        font-weight: 500;
        color: #6E6E73;
        padding: 0.55rem 0.9rem;
    }

    button[data-baseweb="tab"]:hover {
        color: #1D1D1F;
        background: transparent;
    }

    button[data-baseweb="tab"][aria-selected="true"] {
        color: #007AFF;
        font-weight: 600;
    }

    div[data-baseweb="tab-highlight"],
    div[data-baseweb="tab-border"] { background-color: #007AFF; }
</style>
"""
st.markdown(CSS_BASE, unsafe_allow_html=True)

# The second half of the design system: inputs, tables, vertical rhythm and
# accessibility.  Kept separate so each block stays readable.
CSS_COMPONENTS = """
<style>
    /* Buttons */
    .stButton > button {
        border-radius: 8px;
        border: 1px solid rgba(0, 0, 0, 0.08);
        font-weight: 500;
        transition: background 150ms ease, border-color 150ms ease;
    }

    .stButton > button[kind="primary"] {
        background-color: #007AFF;
        border-color: #007AFF;
    }

    .stButton > button[kind="primary"]:hover {
        background-color: #0062CC;
        border-color: #0062CC;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        border-right: 1px solid rgba(0, 0, 0, 0.06);
    }

    section[data-testid="stSidebar"] .block-container { padding-top: 2rem; }

    /* Keep the file uploader from dominating the sidebar. */
    section[data-testid="stSidebar"] div[data-testid="stFileUploader"] {
        background: #FFFFFF;
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 12px;
        padding: 0.85rem;
    }

    /* Tables and alerts */
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(0, 0, 0, 0.06);
        border-radius: 12px;
        overflow: hidden;
    }

    div[data-testid="stAlert"] {
        border-radius: 10px;
        border: 1px solid rgba(0, 0, 0, 0.05);
    }

    /* Vertical rhythm */
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 4rem;
        max-width: 1400px;
    }

    h1, h2, h3 {
        font-weight: 600;
        letter-spacing: -0.015em;
        color: #1D1D1F;
    }

    h2 { font-size: 1.35rem; margin-top: 1.5rem; }
    h3 { font-size: 1.1rem;  margin-top: 1rem; }

    hr {
        border-color: rgba(0, 0, 0, 0.07);
        margin: 2rem 0;
    }

    /* Plots: deliberately NOT styled from CSS.  An earlier version set a
       background on Plotly's internal ``.main-svg``, which blanked every chart
       in the app.  Plotly draws into that SVG with its own stacking context, so
       a background applied from outside hides the rendered output.  The chart
       background is set from Plotly itself instead - see ``paper_bgcolor`` and
       ``plot_bgcolor`` in PLOT_LAYOUT. */

    /* Accessibility: focus rings stay visible for keyboard users. */
    button:focus-visible,
    [data-testid="stSelectbox"] *:focus-visible {
        outline: 2px solid #007AFF;
        outline-offset: 2px;
    }

    /* Status text stays white on the saturated green used by the metric
       delta pill, where the white text is large and bold rather than body
       copy.  Normal alert text uses the accessible dark green from the
       theme instead. */
    div[data-testid="stMetricDelta"][data-direction="up"] {
        background-color: #34C759;
        color: #FFFFFF;
    }

    div[data-testid="stMetricDelta"][data-direction="up"] * {
        color: #FFFFFF;
    }
</style>
"""
st.markdown(CSS_COMPONENTS, unsafe_allow_html=True)


@st.cache_data(show_spinner="Loading data...")
def load_file(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Read an uploaded CSV or Excel file into a frame, cached per file."""
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    return pd.read_excel(io.BytesIO(file_bytes))


@st.cache_data(show_spinner="Validating...")
def run_validation(frame: pd.DataFrame, tier_name: str):
    """Validate a frame with the shared Validator, cached per (frame, tier).

    Routing the dashboard through the same :class:`Validator` used by the API
    and the batch engine is what guarantees the multi-mode consistency claim in
    Chapter 4: a record flagged here is flagged identically everywhere.
    """
    return Validator().validate(frame, tier=tier_name)


def main() -> None:
    """Render the dashboard shell and route to the six analysis tabs."""
    st.markdown('<h1 class="main-header">Data Quality Dashboard</h1>',
                unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Detect, visualise and prioritise '
        'inconsistencies in multi-project cost data.</p>',
        unsafe_allow_html=True)

    with st.sidebar:
        st.header("Upload and Configure")

        uploaded_file = st.file_uploader(
            "Choose Excel or CSV file",
            type=["xlsx", "xls", "csv"],
            help="Upload your project cost data file",
        )

        # The contract tier selects which rule set runs.  WBS-level records
        # (R1-R7, R10-R12) and project-period records (R8, R9, R13, R14) are
        # validated against different contracts, per Chapter 3 Table 3.9.
        tier = st.radio(
            "Contract tier",
            ["raw", "derived"],
            index=0,
            help="raw = WBS-level records; derived = time-phased project records",
        )

        st.divider()
        st.caption(
            "Thresholds are read from config/rules.yaml, so the targets shown "
            "here always match the engine's pass/fail logic."
        )

    if uploaded_file is None:
        display_welcome_screen()
        return

    df = load_file(uploaded_file.getvalue(), uploaded_file.name)
    display_dashboard(df, tier)


def display_dashboard(df: pd.DataFrame, tier: str) -> None:
    """Render the six-tab dashboard for a loaded, validated frame."""
    result = run_validation(df, tier)
    counts = summarise_counts(result.all_findings, result.total_records)
    thresholds = load_config()["thresholds"]

    tab_preview, tab_metric, tab_graph, tab_dist, tab_summary, tab_cost = st.tabs(TABS)

    with tab_preview:
        display_data_preview(df, counts)

    with tab_metric:
        display_metric_table(df, tier, result, thresholds)

    with tab_graph:
        display_metric_graph(df, tier, thresholds)

    with tab_dist:
        display_distribution(df)

    with tab_summary:
        display_summary_statistics(df)

    with tab_cost:
        display_cost_variance(df, tier)


def display_data_preview(df: pd.DataFrame, counts: dict) -> None:
    """Tab 1: inspect the uploaded records and the validation counts."""
    st.subheader("Data Preview")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Records", f"{counts['total_records']:,}")
    with col2:
        st.metric("Valid Records", f"{counts['valid_records']:,}")
    with col3:
        st.metric("Invalid Records", f"{counts['invalid_records']:,}")
    with col4:
        st.metric("Total Findings", f"{counts['total_findings']:,}")

    st.divider()
    st.dataframe(df.head(100), use_container_width=True, hide_index=True)

    st.subheader("Column Information")
    col_info = pd.DataFrame({
        "Column": df.columns,
        "Data Type": df.dtypes.astype(str),
        "Non-Null Count": df.notna().sum().to_numpy(),
        "Null Count": df.isna().sum().to_numpy(),
    })
    st.dataframe(col_info, use_container_width=True, hide_index=True)


def display_metric_table(
    df: pd.DataFrame, tier: str, result, thresholds: dict
) -> None:
    """Tab 2: dimension scores against the YAML thresholds, plus findings.

    The four dimension scores are computed by
    :func:`data_quality.pipeline.quality.score_dimensions`, the same operational
    definitions the engine and the reporting layer use, so the dashboard cannot
    diverge from the reported figures.
    """
    st.subheader("Quality Dimension Scores")

    scores = score_dimensions(df, tier=tier)
    order = ["completeness", "consistency", "accuracy", "integrity"]
    quality_metrics = pd.DataFrame({
        "Metric": [d.capitalize() for d in order],
        "Value": [scores[d] for d in order],
        "Target": [thresholds[d] for d in order],
        "Status": ["Pass" if scores[d] >= thresholds[d] else "Fail" for d in order],
    })
    st.dataframe(quality_metrics, use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Overall Weighted Score", f"{scores['overall']:.1f}/100")
    with col2:
        st.metric("Records Validated", f"{result.total_records:,}")

    st.divider()
    st.subheader("Findings")
    findings_df = pd.DataFrame([f.to_dict() for f in result.all_findings])
    if findings_df.empty:
        st.success("No findings: every record satisfies the contract.")
        return

    by_rule = result.findings_by_rule()
    st.dataframe(
        pd.DataFrame({"Rule": list(by_rule), "Findings": list(by_rule.values())}),
        use_container_width=True,
        hide_index=True,
    )
    st.dataframe(
        findings_df[["rule_id", "severity", "record_key", "field",
                     "description", "remediation"]],
        use_container_width=True,
        hide_index=True,
    )


def display_metric_graph(df: pd.DataFrame, tier: str, thresholds: dict) -> None:
    """Tab 3: a chart of the dimension scores against their targets."""
    st.subheader("Data Quality Dimensions")

    scores = score_dimensions(df, tier=tier)
    order = ["completeness", "consistency", "accuracy", "integrity"]
    metric_df = pd.DataFrame({
        "Metric": [d.capitalize() for d in order],
        "Value": [scores[d] for d in order],
        "Target": [thresholds[d] for d in order],
    })

    # A bar against the target line reads more precisely than a pie: the reader
    # can see how far each dimension sits from its threshold, which a slice
    # angle cannot show.
    fig = px.bar(metric_df, x="Metric", y="Value",
                 title="Data Quality Dimensions vs. Target",
                 range_y=[0, 100], color_discrete_sequence=[ACCENT])
    fig.add_scatter(x=metric_df["Metric"], y=metric_df["Target"],
                    mode="markers", name="Target",
                    marker=dict(color=BAD, size=11, symbol="line-ew-open"))
    fig.update_layout(**PLOT_LAYOUT)
    fig.update_layout(yaxis_title="Score", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


def display_distribution(df: pd.DataFrame) -> None:
    """Tab 4: histogram of a selected numeric variable."""
    st.subheader("Distribution")

    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_columns:
        st.warning("No numeric columns available for analysis.")
        return

    variable = st.selectbox("Select Variable", numeric_columns)
    fig = px.histogram(df, x=variable, nbins=30,
                       title=f"Distribution of {variable}",
                       color_discrete_sequence=[ACCENT])
    fig.update_layout(bargap=0.1)
    fig.update_layout(**PLOT_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)


def display_summary_statistics(df: pd.DataFrame) -> None:
    """Tab 5: mean / median / std / min / max for a selected variable."""
    st.subheader("Summary Statistics")

    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_columns:
        st.warning("No numeric columns available for analysis.")
        return

    variable = st.selectbox("Select Variable", numeric_columns, key="summary_variable")
    selected = df[variable]
    st.dataframe(
        pd.DataFrame({
            "Statistic": ["Mean", "Median", "Std Dev", "Min", "Max", "Count"],
            "Value": [selected.mean(), selected.median(), selected.std(),
                      selected.min(), selected.max(), selected.count()],
        }),
        use_container_width=True,
        hide_index=True,
    )


def display_cost_variance(df: pd.DataFrame, tier: str) -> None:
    """Tab 6: cumulative cost variance (cumulative budget - cumulative actual).

    The derived contract stores cumulative values, so the variance plotted here
    is cumulative budget minus cumulative actual; on the raw tier the equivalent
    cumulative columns are pv_cum and ac_cum.
    """
    st.subheader("Cost Variance (Cumulative)")

    budget_col, actual_col = COST_COLUMNS[tier]
    if budget_col not in df.columns or actual_col not in df.columns:
        st.warning(
            f"Cost columns '{budget_col}' and '{actual_col}' not found for the "
            f"'{tier}' tier."
        )
        return

    frame = df.copy()
    frame["cost_variance"] = frame[budget_col] - frame[actual_col]

    fig = px.histogram(
        frame, x="cost_variance", nbins=30,
        title="Distribution of Cost Variance (Cumulative Budget - Cumulative Actual)",
        color_discrete_sequence=[ACCENT],
    )
    fig.add_vline(x=0, line_dash="dash", line_color=NEUTRAL,
                  annotation_text="On budget", annotation_font_color=MUTED)
    fig.update_layout(**PLOT_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

    if "project_id" in frame.columns and "time_period" in frame.columns:
        st.subheader("Cumulative Cost Variance by Project")

        grouped = (frame.groupby(["project_id", "time_period"])
                   [["cost_variance"]].sum().reset_index())
        grouped["_period_order"] = period_sort_key(grouped["time_period"])
        grouped = grouped.sort_values(["project_id", "_period_order"])
        grouped = grouped.drop(columns="_period_order")

        fig_project = go.Figure()
        for position, project in enumerate(grouped["project_id"].unique()):
            project_data = grouped[grouped["project_id"] == project]
            project_color = SERIES_COLORS[position % len(SERIES_COLORS)]
            fig_project.add_trace(go.Scatter(
                x=project_data["time_period"],
                y=project_data["cost_variance"],
                mode="lines+markers",
                name=str(project),
                line=dict(width=2, color=project_color),
            ))

        fig_project.add_hline(y=0, line_dash="dash", line_color=NEUTRAL)
        fig_project.update_layout(**PLOT_LAYOUT)
        fig_project.update_layout(
            xaxis_title="Time Period", yaxis_title="Cost Variance",
            hovermode="x unified", height=480,
            legend=dict(orientation="h", yanchor="top", y=-0.2,
                        xanchor="left", x=0, font={"size": 11}),
            margin={"t": 20, "b": 110, "l": 60, "r": 25},
        )
        st.plotly_chart(fig_project, use_container_width=True)


def display_welcome_screen() -> None:
    """Show guidance and a probe script before any file is loaded."""
    st.subheader("Welcome to the Data Quality Dashboard")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.info(
            """
            **Getting started**

            1. Upload your data using the file uploader in the sidebar.
            2. Choose the contract tier: **raw** (WBS-level) or **derived**
               (time-phased project records).
            3. Explore the results across the six tabs:
               - Data Preview: records and validation counts
               - Metric Table: dimension scores against YAML targets, plus findings
               - Metric Graph: dimension scores against their targets
               - Distribution: distribution of a numeric variable
               - Summary Statistics: descriptive statistics
               - Cost Variance: cumulative budget minus cumulative actual
            """
        )

    with col2:
        st.success(
            """
            **Guarantees**

            - Shared Validator with the live API
            - Config-driven thresholds (rules.yaml)
            - Identical findings across all modes
            - Cumulative-semantics cost variance
            - Accessible, colour-safe charts
            """
        )


if __name__ == "__main__":
    main()
