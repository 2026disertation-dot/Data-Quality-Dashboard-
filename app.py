"""
Data Quality Dashboard for Multi-Project Cost Management
Main Streamlit application for real-time data quality monitoring
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime
import os
from typing import Optional

# Import our custom modules
from dqd.legacy.pipeline import DataPipeline
from dqd.legacy.contract import get_contract_specification



# Shared colour palette.
#
# These are the same tokens as .streamlit/config.toml, so the chrome, the CSS
# and the charts are guaranteed to agree.  Keeping them in one place means a
# palette change happens once rather than drifting between the app and the
# figure-export module.
ACCENT = "#007AFF"      # system blue - primary series
GOOD = "#34C759"        # green   - within target / valid
WARN = "#FF9F0A"        # amber   - attention
BAD = "#FF3B30"         # red     - out of target / invalid
NEUTRAL = "#8E8E93"     # grey    - reference lines
GRID = "#E5E5EA"        # light grey - axis and grid lines
INK = "#1D1D1F"         # near-black - text
MUTED = "#6E6E73"       # grey     - secondary text
SURFACE = "#FFFFFF"     # card background

# Sequential blue ramp for multi-series charts.  These read as one family
# rather than the unrelated pastels a default palette would produce.
SERIES_COLORS = ["#007AFF", "#66B5FF", "#34C759", "#FF9F0A", "#FF3B30",
                 "#AF52DE", "#5AC8FA", "#8E8E93"]

# A restrained Plotly template matching the Streamlit theme.
#
# NOTE: ``title`` is deliberately absent.  Supplying a title object here forces
# Plotly to stop reserving top margin for the title, which pushed the gauge's
# arc outside the canvas (its paths resolved to negative coordinates and the
# chart rendered blank).  Each figure sets its own title as a string, and
# Plotly's own auto-margin then reserves the correct space.
PLOT_LAYOUT = {
    "template": "plotly_white",
    "paper_bgcolor": SURFACE,
    "plot_bgcolor": SURFACE,
    "font": {"family": "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif",
             "color": INK, "size": 12},
    "margin": {"t": 55, "b": 45, "l": 60, "r": 25},
}


def period_sort_key(periods):
    """
    Build a natural sort key for ``time_period`` labels.

    Labels such as ``Week-2`` or ``Month-10`` sort incorrectly as plain
    strings (``"Month-10"`` sorts before ``"Month-2``), which would scramble
    the time axis of the cost charts. Splitting each label into its prefix and
    numeric suffix keeps the reporting periods in chronological order.
    """
    def key(label):
        text = str(label)
        prefix, separator, number = text.rpartition("-")
        if separator and number.isdigit():
            return (prefix, int(number), "")
        return (text, 0, "")

    return pd.Series([key(label) for label in periods], index=periods.index, dtype=object)


# Page configuration
st.set_page_config(
    page_title="Data Quality Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling.
#
# Streamlit's own theme (see .streamlit/config.toml) sets the base palette; the
# rules here handle what a theme cannot express: the header treatment, card
# surfaces, tightened vertical rhythm and consistent alignment.  Colours are
# the same tokens as the theme file so the interface and the charts agree.
CSS_BASE = """
<style>
    /* Typography */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                     "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
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

    /* A thin gradient rule separates the title from the content without the
       heaviness of a full-width border. */
    .main-header::after {
        content: "";
        display: block;
        width: 100%;
        height: 1px;
        margin-top: 0.9rem;
        background: linear-gradient(90deg, #D2D2D7 0%, rgba(210,210,215,0) 100%);
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
        transition: box-shadow 150ms ease, transform 150ms ease;
    }

    div[data-testid="stMetric"]:hover {
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.07);
        transform: translateY(-1px);
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
       ``plot_bgcolor`` in PLOT_LAYOUT in app.py. */

    /* Accessibility: focus rings stay visible for keyboard users. */
    button:focus-visible,
    [data-testid="stSelectbox"] *:focus-visible {
        outline: 2px solid #007AFF;
        outline-offset: 2px;
    }

    /* Success green: white text on the Apple green.
       The theme token (greenTextColor) does not by itself reach the alert
       container, which kept rendering the default dark green and read as muddy
       against the #34C759 background.  These selectors were read off the live
       DOM rather than guessed: the success alert and the metric delta pill.
       Contrast is 2.22:1, below WCAG AA - a deliberate visual trade. */
    div[data-testid="stAlertContainer"] p,
    div[data-testid="stAlertContainer"] span,
    div[data-testid="stAlertContainer"] div {
        color: #FFFFFF;
    }

    div[data-testid="stMetricDelta"] {
        color: #FFFFFF;
    }

    /* The delta pill only turns green for a favourable change, so the colour
       has to be pinned rather than left to the theme. */
    div[data-testid="stMetricDelta"][data-direction="up"] {
        background-color: #34C759;
        color: #FFFFFF;
    }

    .success { color: #248A3D; }
    .warning { color: #B25000; }
    .error   { color: #D70015; }
</style>
"""
st.markdown(CSS_COMPONENTS, unsafe_allow_html=True)

# Initialize session state
if 'pipeline' not in st.session_state:
    st.session_state.pipeline = DataPipeline()
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'validation_results' not in st.session_state:
    st.session_state.validation_results = None
if 'quality_metrics' not in st.session_state:
    st.session_state.quality_metrics = None
if 'current_data' not in st.session_state:
    st.session_state.current_data = None
# Tracks whether the contract specification panel is expanded.  This is a real
# toggle rather than the previous one-way latch, which could open the panel but
# never close it and gave no indication of its state.
if 'contract_spec_open' not in st.session_state:
    st.session_state.contract_spec_open = False

def main():
    """Main application function"""
    
    # Header
    st.markdown('<h1 class="main-header">Data Quality Dashboard for Multi-Project Cost Management</h1>', 
                unsafe_allow_html=True)
    st.markdown(
        '<p class="page-subtitle">Real-time accuracy, completeness, consistency '
        'and integrity monitoring for earned-value cost records.</p>',
        unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.header("Upload and Configure")
        
        # File upload
        uploaded_file = st.file_uploader(
            "Choose Excel or CSV file",
            type=["xlsx", "xls", "csv"],
            help="Upload your project cost data file"
        )
        
        # Processing mode selection
        st.subheader("Processing Mode")
        processing_mode = st.radio(
            "Select Mode",
            ["Batch Mode", "Incremental Mode"],
            help="Batch: Analyze entire dataset | Incremental: Add new records"
        )
        
        # Action buttons
        if uploaded_file is not None:
            if st.button("Process Data", type="primary"):
                process_uploaded_data(uploaded_file, processing_mode)
        
        st.divider()
        
        # Data contract info
        st.subheader("Data Contract")

        # A genuine two-way toggle.  The label carries the state so the control
        # is self-explanatory without relying on the caret glyph alone, and the
        # panel is collapsed by default so opening it never hides the System
        # Information summary underneath.
        contract_open = st.session_state.contract_spec_open
        if st.button(
            "Hide Contract Specification" if contract_open
            else "Show Contract Specification",
            key="contract_toggle",
            use_container_width=True,
        ):
            st.session_state.contract_spec_open = not contract_open
            # Re-run so the panel and the label both reflect the new state on
            # the same click.  Streamlit resets widget state on rerun, so the
            # button is keyed and the value lives in session_state.
            st.rerun()

        if st.session_state.contract_spec_open:
            display_data_contract()
        
        st.divider()
        
        # System info
        st.subheader("System Information")
        if st.session_state.data_loaded:
            st.success(f"✅ Data loaded: {len(st.session_state.current_data)} records")
            if st.session_state.quality_metrics:
                st.metric("Overall Quality Score", 
                         f"{st.session_state.quality_metrics['overall_score']:.1f}/100")
        else:
            st.info("⏳ No data loaded")
    
    # Main content area
    if st.session_state.data_loaded:
        display_dashboard()
    else:
        display_welcome_screen()

def process_uploaded_data(uploaded_file, processing_mode: str) -> None:
    """Process the uploaded data file"""
    
    try:
        # Load data
        file_type = uploaded_file.name.split('.')[-1].lower()
        
        # Save to temporary file
        temp_path = f"temp_upload.{file_type}"
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        # Load using pipeline
        df = st.session_state.pipeline.load_data(temp_path, file_type)
        
        # Process based on mode
        if processing_mode == "Batch Mode":
            results = st.session_state.pipeline.process_batch(df)
        else:
            results = st.session_state.pipeline.process_incremental(df)
        
        # Update session state
        st.session_state.current_data = results['processed_data']
        st.session_state.validation_results = results['validation_results']
        st.session_state.quality_metrics = results['quality_metrics']
        st.session_state.data_loaded = True
        
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        st.success(f"✅ Data processed successfully in {processing_mode}!")
        st.rerun()
        
    except Exception as e:
        st.error(f"❌ Error processing data: {str(e)}")

def display_dashboard() -> None:
    """Display the main dashboard with all tabs"""
    
    # Create tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Data Preview", "📈 Quality Metrics", "🎯 Distribution", 
        "🔍 Validation Results", "📉 Cost Analysis", "📋 Summary Statistics"
    ])
    
    with tab1:
        display_data_preview()
    
    with tab2:
        display_quality_metrics()
    
    with tab3:
        display_distribution_analysis()
    
    with tab4:
        display_validation_results()
    
    with tab5:
        display_cost_analysis()
    
    with tab6:
        display_summary_statistics()

def display_data_preview() -> None:
    """Display data preview tab"""
    st.subheader("Data Preview")
    
    df = st.session_state.current_data
    
    # Show basic info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Records", len(df))
    with col2:
        st.metric("Total Columns", len(df.columns))
    with col3:
        st.metric("Memory Usage", f"{df.memory_usage(deep=True).sum() / 1024:.1f} KB")
    
    st.divider()
    
    # Display dataframe
    st.dataframe(df.head(100), use_container_width=True)
    
    # Column info
    st.subheader("Column Information")
    col_info = pd.DataFrame({
        "Column": df.columns,
        "Data Type": df.dtypes.astype(str),
        "Non-Null Count": df.notna().sum(),
        "Null Count": df.isna().sum()
    })
    st.dataframe(col_info, use_container_width=True)

def display_quality_metrics() -> None:
    """Display quality metrics tab"""
    st.subheader("Data Quality Dimensions")
    
    metrics = st.session_state.quality_metrics
    
    if not metrics:
        st.warning("No quality metrics available")
        return
    
    # Display metric cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        accuracy_score = metrics['accuracy']
        color = "success" if accuracy_score >= 80 else "warning" if accuracy_score >= 60 else "error"
        st.metric("Accuracy", f"{accuracy_score:.1f}%", 
                 delta=f"{accuracy_score-100:.1f}%" if accuracy_score < 100 else "Perfect")
    
    with col2:
        completeness_score = metrics['completeness']
        color = "success" if completeness_score >= 80 else "warning" if completeness_score >= 60 else "error"
        st.metric("Completeness", f"{completeness_score:.1f}%",
                 delta=f"{completeness_score-100:.1f}%" if completeness_score < 100 else "Perfect")
    
    with col3:
        consistency_score = metrics['consistency']
        color = "success" if consistency_score >= 80 else "warning" if consistency_score >= 60 else "error"
        st.metric("Consistency", f"{consistency_score:.1f}%",
                 delta=f"{consistency_score-100:.1f}%" if consistency_score < 100 else "Perfect")
    
    with col4:
        integrity_score = metrics['integrity']
        color = "success" if integrity_score >= 80 else "warning" if integrity_score >= 60 else "error"
        st.metric("Integrity", f"{integrity_score:.1f}%",
                 delta=f"{integrity_score-100:.1f}%" if integrity_score < 100 else "Perfect")
    
    st.divider()
    
    # Overall score gauge
    st.subheader("Overall Data Quality Score")
    overall_score = metrics['overall_score']
    
    # Create gauge chart
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = overall_score,
        # A gauge drawn across the full 0-1 domain spreads to the edges of a
        # wide canvas, leaving the dial small and off-centre.  Constraining the
        # domain to the middle keeps the arc centred and fully visible.
        domain = {'x': [0.25, 0.75], 'y': [0.1, 0.85]},
        title = {'text': "Quality Score", "font": {"size": 13, "color": MUTED}},
        number = {'font': {"size": 30, "color": INK}, "suffix": "/100"},
        gauge = {
            'axis': {'range': [None, 100], 'tickcolor': GRID, 'tickfont': {"size": 10, "color": MUTED}},
            # A thin needle on a white track reads more cleanly than a filled
            # bar, and the faint band tints signal the score without shouting.
            'bar': {'color': ACCENT, 'thickness': 0.28},
            'steps': [
                {'range': [0, 60], 'color': "rgba(255,59,48,0.10)"},
                {'range': [60, 80], 'color': "rgba(255,159,10,0.12)"},
                {'range': [80, 100], 'color': "rgba(52,199,89,0.12)"}
            ],
            'threshold': {
                'line': {'color': BAD, 'width': 3},
                'thickness': 0.8,
                'value': 90
            }
        }
    ))
    # The gauge needs a tighter margin than the shared layout default, so it is
    # overridden here.  Passing ``margin`` alongside ``**PLOT_LAYOUT`` would be a
    # duplicate keyword argument, so the override is applied as a second call.
    fig.update_layout(**PLOT_LAYOUT)
    fig.update_layout(height=300, margin={"t": 10, "b": 10, "l": 40, "r": 40})
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Pie chart of dimensions
    st.subheader("Quality Dimension Breakdown")
    metric_df = pd.DataFrame({
        "Dimension": ["Accuracy", "Completeness", "Consistency", "Integrity"],
        "Score": [metrics['accuracy'], metrics['completeness'], 
                 metrics['consistency'], metrics['integrity']]
    })
    
    # The four dimensions use the shared series ramp, so the pie reads as part
    # of the same system as the other charts.
    fig_pie = px.pie(metric_df, values="Score", names="Dimension", 
                     title="Data Quality Dimensions Distribution",
                     color_discrete_sequence=SERIES_COLORS,
                     hole=0.45)
    fig_pie.update_traces(textposition="outside", textinfo="label+percent",
                          marker=dict(line=dict(color=SURFACE, width=2)))
    fig_pie.update_layout(**PLOT_LAYOUT)
    st.plotly_chart(fig_pie, use_container_width=True)

def display_distribution_analysis() -> None:
    """Display distribution analysis tab"""
    st.subheader("Distribution Analysis")
    
    df = st.session_state.current_data
    
    # Select variable for analysis
    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_columns:
        st.warning("No numeric columns available for analysis")
        return
    
    selected_variable = st.selectbox("Select Variable for Analysis", numeric_columns)
    
    if selected_variable:
        # Histogram
        fig_hist = px.histogram(df, x=selected_variable, nbins=30,
                                title=f"Distribution of {selected_variable}",
                                color_discrete_sequence=[ACCENT])
        fig_hist.update_layout(bargap=0.1)
        fig_hist.update_layout(**PLOT_LAYOUT)
        st.plotly_chart(fig_hist, use_container_width=True)
        
        # Box plot
        fig_box = px.box(df, y=selected_variable,
                        title=f"Box Plot of {selected_variable}",
                        color_discrete_sequence=[ACCENT])
        fig_box.update_layout(**PLOT_LAYOUT)
        st.plotly_chart(fig_box, use_container_width=True)
        
        # Summary statistics
        st.subheader(f"Summary Statistics for {selected_variable}")
        stats_df = pd.DataFrame({
            "Statistic": ["Mean", "Median", "Std Dev", "Min", "Max", "Count"],
            "Value": [
                df[selected_variable].mean(),
                df[selected_variable].median(),
                df[selected_variable].std(),
                df[selected_variable].min(),
                df[selected_variable].max(),
                df[selected_variable].count()
            ]
        })
        st.dataframe(stats_df, use_container_width=True)

def display_validation_results() -> None:
    """Display validation results tab"""
    st.subheader("Validation Results")
    
    validation_results = st.session_state.validation_results
    
    if not validation_results:
        st.warning("No validation results available")
        return
    
    # Summary cards.
    #
    # Batch and incremental validation report their record count under the same
    # key, but the dashboard is also used with hand-built result dicts, so the
    # count is read defensively rather than by direct indexing.  A missing key
    # must not take the whole tab down.
    total_records = validation_results.get(
        "total_records", validation_results.get("new_records", 0)
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Records", total_records)
    with col2:
        st.metric("Valid Records", validation_results.get('valid_records', 0))
    with col3:
        st.metric("Invalid Records", validation_results.get('invalid_records', 0))
    with col4:
        st.metric("Quality Score", f"{validation_results['summary']['data_quality_score']:.1f}/100")
    
    st.divider()
    
    # Anomaly breakdown
    st.subheader("Anomaly Breakdown")
    
    anomalies = validation_results['anomalies']
    anomaly_summary = {
        "Anomaly Type": ["Missing Values", "Type Errors", "Bounds Violations", 
                        "Logical Anomalies", "Duplicates"],
        "Count": [
            len(anomalies['missing_values']),
            len(anomalies['type_errors']),
            len(anomalies['bounds_violations']),
            len(anomalies['logical_anomalies']),
            len(anomalies['duplicates'])
        ]
    }
    
    anomaly_df = pd.DataFrame(anomaly_summary)
    st.dataframe(anomaly_df, use_container_width=True)
    
    # Detailed anomalies
    st.subheader("Detailed Anomalies")
    
    anomaly_type = st.selectbox(
        "Select Anomaly Type",
        ["Missing Values", "Type Errors", "Bounds Violations", "Logical Anomalies", "Duplicates"]
    )
    
    anomaly_key = anomaly_type.lower().replace(" ", "_")
    selected_anomalies = anomalies[anomaly_key]
    
    if selected_anomalies:
        # Display anomalies in a dataframe
        anomaly_details = []
        for anomaly in selected_anomalies[:50]:  # Limit to first 50
            anomaly_details.append({
                "Row Index": anomaly['row_index'],
                "Field": anomaly['field'],
                "Severity": anomaly['severity'],
                "Description": anomaly['description'],
                "Suggested Remediation": anomaly['suggested_remediation']
            })
        
        if anomaly_details:
            details_df = pd.DataFrame(anomaly_details)
            st.dataframe(details_df, use_container_width=True)
        else:
            st.info(f"No {anomaly_type} detected")
    else:
        st.success(f"✅ No {anomaly_type} detected")

def display_cost_analysis() -> None:
    """Display cost analysis tab"""
    st.subheader("Cost Analysis: Budget vs Actual")
    
    df = st.session_state.current_data
    
    # Check if required columns exist
    if 'pmb_budget' not in df.columns or 'actual_cost' not in df.columns:
        st.warning("Budget and actual cost columns not found in data")
        return
    
    # Project selection
    if 'project_id' in df.columns:
        projects = df['project_id'].unique()
        selected_projects = st.multiselect("Select Projects", projects, default=projects[:5])
        
        if selected_projects:
            df_filtered = df[df['project_id'].isin(selected_projects)]
        else:
            df_filtered = df
    else:
        df_filtered = df
    
    # Calculate cost variance
    df_filtered = df_filtered.copy()
    df_filtered['cost_variance'] = df_filtered['actual_cost'] - df_filtered['pmb_budget']
    df_filtered['variance_pct'] = (df_filtered['cost_variance'] / df_filtered['pmb_budget'].replace(0, 1)) * 100
    
    # Budget vs Actual chart
    st.subheader("Budget vs Actual Cost by Project")
    
    if 'project_id' in df_filtered.columns and 'time_period' in df_filtered.columns:
        # Group by project and time period
        group_data = df_filtered.groupby(['project_id', 'time_period']).agg({
            'pmb_budget': 'sum',
            'actual_cost': 'sum'
        }).reset_index()
        
        # Order the time axis chronologically (Month-10 must follow Month-2)
        group_data['_period_order'] = period_sort_key(group_data['time_period'])
        group_data = group_data.sort_values(['project_id', '_period_order'])
        group_data = group_data.drop(columns='_period_order')
        
        fig = go.Figure()

        # One hue per project, drawn from the shared ramp, with budget as a
        # solid line and actual as a dashed one.  Encoding the two measures by
        # line style rather than by colour keeps the chart readable when it is
        # printed in greyscale and for viewers who cannot rely on hue.
        for position, project in enumerate(group_data['project_id'].unique()):
            project_data = group_data[group_data['project_id'] == project]
            project_color = SERIES_COLORS[position % len(SERIES_COLORS)]

            fig.add_trace(go.Scatter(
                x=project_data['time_period'],
                y=project_data['pmb_budget'],
                mode='lines+markers',
                name=f'{project} - Budget',
                line=dict(width=2, color=project_color)
            ))
            
            fig.add_trace(go.Scatter(
                x=project_data['time_period'],
                y=project_data['actual_cost'],
                mode='lines+markers',
                name=f'{project} - Actual',
                line=dict(width=2, dash='dash', color=project_color)
            ))
        
        # No Plotly title here on purpose.  The ``st.subheader`` above already
        # labels this chart, and a second title only repeated it.  It also
        # collided with the legend, because a horizontal legend sitting above
        # the plot (y=1.02) wraps onto two rows once every project contributes a
        # Budget and an Actual entry, and the wrapped rows ran straight through
        # the title text.
        #
        # Placing the legend *below* the plot instead keeps all 10 entries
        # readable, stops the overlap, and gives the lines back the top margin
        # that PLOT_LAYOUT reserves.
        fig.update_layout(
            xaxis_title="Time Period",
            yaxis_title="Cost",
            hovermode='x unified',
            height=500,
            legend=dict(orientation="h", yanchor="top", y=-0.18,
                        xanchor="left", x=0, font={"size": 11})
        )
        fig.update_layout(**PLOT_LAYOUT)
        # PLOT_LAYOUT's 45px bottom margin is sized for an x-axis title alone and
        # would clip a legend hanging below the plot.  The margin has to be
        # overridden in a *second* call: passing ``margin`` together with
        # ``**PLOT_LAYOUT`` would be a duplicate keyword argument.
        fig.update_layout(margin={"t": 20, "b": 110, "l": 60, "r": 25})

        st.plotly_chart(fig, use_container_width=True)
    
    # Cost variance distribution
    st.subheader("Cost Variance Distribution")
    
    fig_variance = px.histogram(df_filtered, x='variance_pct', nbins=30,
                               title="Cost Variance Percentage Distribution",
                               color_discrete_sequence=[ACCENT])
    # The budget line is the reference the whole chart is read against, so it
    # is drawn in the muted grey rather than a competing colour.
    fig_variance.add_vline(x=0, line_dash="dash", line_color=NEUTRAL,
                          annotation_text="Budget", annotation_font_color=MUTED)
    fig_variance.update_layout(**PLOT_LAYOUT)
    st.plotly_chart(fig_variance, use_container_width=True)
    
    # Variance by project
    if 'project_id' in df_filtered.columns:
        st.subheader("Cost Variance by Project")
        
        variance_by_project = df_filtered.groupby('project_id').agg({
            'pmb_budget': 'sum',
            'actual_cost': 'sum',
            'cost_variance': 'sum'
        }).reset_index()
        
        variance_by_project['variance_pct'] = (
            variance_by_project['cost_variance'] / variance_by_project['pmb_budget'].replace(0, 1)
        ) * 100
        
        # A red-green diverging scale (RdYlGn) is the conventional choice here
        # but it is the single most colour-blind-hostile palette, and red/green
        # is exactly the distinction being encoded.  This keeps the same
        # under/over-budget meaning using the theme's red and green as *light*
        # endpoints around a neutral centre, which stays legible for viewers
        # with red-green colour vision deficiency.
        variance_scale = [
            [0.0, "#FF3B30"],      # heavily over budget
            [0.35, "#FF9F0A"],     # over budget
            [0.5, "#D2D2D7"],      # on budget
            [0.65, "#66B5FF"],     # under budget
            [1.0, "#34C759"],      # well under budget
        ]

        fig_project = px.bar(variance_by_project, x='project_id', y='variance_pct',
                           title="Cost Variance Percentage by Project",
                           color='variance_pct',
                           color_continuous_scale=variance_scale)
        fig_project.add_hline(y=0, line_dash="dash", line_color=NEUTRAL)
        fig_project.update_layout(**PLOT_LAYOUT, coloraxis_colorbar_title="Variance %")
        st.plotly_chart(fig_project, use_container_width=True)

def display_summary_statistics() -> None:
    """Display summary statistics tab"""
    st.subheader("Summary Statistics")
    
    df = st.session_state.current_data
    
    # Overall summary
    summary = st.session_state.pipeline.get_data_summary()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Total Records", summary['total_records'])
        st.metric("Total Columns", len(summary['columns']))
        st.metric("Memory Usage", f"{summary['memory_usage'] / 1024:.1f} KB")
    
    with col2:
        if 'date_range' in summary and summary['date_range']:
            st.write("Date Ranges:")
            for col, range_info in summary['date_range'].items():
                st.write(f"**{col}:** {range_info['min']} to {range_info['max']}")
    
    st.divider()
    
    # Numeric statistics
    if summary['numeric_summary']:
        st.subheader("Numeric Columns Statistics")
        
        for col, stats in summary['numeric_summary'].items():
            with st.expander(f"{col}"):
                stats_df = pd.DataFrame({
                    "Statistic": ["Mean", "Median", "Std Dev", "Min", "Max"],
                    "Value": [
                        f"{stats['mean']:.2f}" if stats['mean'] is not None else "N/A",
                        f"{stats['median']:.2f}" if stats['median'] is not None else "N/A",
                        f"{stats['std']:.2f}" if stats['std'] is not None else "N/A",
                        f"{stats['min']:.2f}" if stats['min'] is not None else "N/A",
                        f"{stats['max']:.2f}" if stats['max'] is not None else "N/A"
                    ]
                })
                st.dataframe(stats_df, use_container_width=True)
    
    # Categorical statistics
    if summary['categorical_summary']:
        st.subheader("Categorical Columns Statistics")
        
        for col, stats in summary['categorical_summary'].items():
            with st.expander(f"{col}"):
                st.write(f"**Unique Values:** {stats['unique_count']}")
                st.write(f"**Most Common:** {stats['most_common']}")
                
                # Show value counts
                value_counts = df[col].value_counts().head(10)
                st.write("**Top 10 Values:**")
                st.dataframe(value_counts, use_container_width=True)

def display_data_contract() -> None:
    """
    Render the data contract specification as a readable table.

    This replaces an earlier ``st.json()`` dump, which printed nested braces,
    quoted keys and array indices straight into the 300px sidebar.  That is
    machine output: it reads as a debugging aid rather than a specification, and
    it gave no way to tell whether the panel was open or closed.

    The table is built from the same ``get_contract_specification()`` source as
    the raw dump, so the content is unchanged - only the presentation is.  The
    schema's field order is preserved so the fields read in contract order
    rather than alphabetically.
    """
    contract_spec = get_contract_specification()

    field_types = contract_spec.get("field_types", {})
    constraints = contract_spec.get("field_constraints", {})

    # Preserve the contract's own field order, and pick up any field that has a
    # type but is missing from required_fields so nothing is silently dropped.
    ordered_fields = list(contract_spec.get("required_fields", []))
    ordered_fields += [f for f in field_types if f not in ordered_fields]

    # Two columns, not three.  A Field / Type / Constraint table does not fit
    # the ~300px sidebar: the third column was pushed off the right edge and the
    # Type values were clipped mid-word.  Field and Type are the two things a
    # reader actually scans for, and the handful of real constraints are listed
    # below the table where they have room to wrap.
    rows = [
        {
            "Field": name,
            "Type": field_types.get(name, "-"),
        }
        for name in ordered_fields
    ]

    st.dataframe(
        pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Field", "Type"]),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Field": st.column_config.TextColumn("Field", width="medium"),
            "Type": st.column_config.TextColumn("Type", width="small"),
        },
    )

    if constraints:
        st.markdown("**Field constraints**")
        for name, rule in constraints.items():
            st.markdown(f"- `{name}` {rule}")

    st.caption("All fields are required and must be non-null.")

    logical = contract_spec.get("logical_constraints", [])
    if logical:
        st.markdown("**Logical constraints**")
        for rule in logical:
            st.markdown(f"- {rule}")
    
    st.write("### Required Fields")
    for field in contract_spec['required_fields']:
        st.write(f"- {field}")
    
    st.write("### Field Types")
    for field, field_type in contract_spec['field_types'].items():
        st.write(f"- {field}: {field_type}")
    
    st.write("### Field Constraints")
    for field, constraint in contract_spec['field_constraints'].items():
        st.write(f"- {field}: {constraint}")
    
    st.write("### Logical Constraints")
    for constraint in contract_spec['logical_constraints']:
        st.write(f"- {constraint}")

def display_welcome_screen() -> None:
    """Display welcome screen when no data is loaded"""
    st.subheader("Welcome to the Data Quality Dashboard")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.info("""
        ### Getting Started
        
        1. **Upload your data** using the file uploader in the sidebar
        2. **Select processing mode** (Batch for historical analysis, Incremental for new records)
        3. **Click "Process Data"** to run validation and quality checks
        4. **Explore the results** across different tabs:
           - 📊 Data Preview: View your uploaded data
           - 📈 Quality Metrics: See accuracy, completeness, consistency, integrity scores
           - 🎯 Distribution: Analyze data distributions
           - 🔍 Validation Results: Review detected anomalies
           - 📉 Cost Analysis: Compare budget vs actual costs
           - 📋 Summary Statistics: View comprehensive statistics
        """)
    
    with col2:
        st.success("""
        ### Features
        
        ✅ Real-time validation
        ✅ Dual-mode processing
        ✅ Interactive visualizations
        ✅ Comprehensive metrics
        ✅ Anomaly detection
        ✅ Cost variance analysis
        """)
    
    st.divider()
    
    # Sample data format information
    st.subheader("Expected Data Format")
    
    sample_format = pd.DataFrame({
        "Column": ["project_id", "time_period", "pmb_budget", "actual_cost", 
                   "progress_pct", "revenue_claimed", "actual_date", "baseline_start_date"],
        "Type": ["string", "string", "numeric", "numeric", "numeric (0-100)", 
                "numeric", "datetime", "datetime"],
        "Required": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes"],
        "Description": [
            "Unique project identifier",
            "Reporting period (e.g., Week-1)",
            "Planned budget value",
            "Actual cost incurred",
            "Progress percentage (0-100)",
            "Revenue claimed",
            "Date of actual cost",
            "Project baseline start date"
        ]
    })
    
    st.dataframe(sample_format, use_container_width=True)

if __name__ == "__main__":
    main()
