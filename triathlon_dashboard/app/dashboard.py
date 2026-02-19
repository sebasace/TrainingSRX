"""Streamlit dashboard presentation layer."""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure `app` package imports resolve when launched from different working directories.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import GARMIN_EMAIL, GARMIN_PASSWORD
from app.db import init_db
from app.ingestion import import_garmin_connect, import_garmin_csv
from app.metrics import (
    compute_acwr,
    compute_efficiency_trend,
    compute_fatigue_score,
    compute_weekly_totals,
    load_activities_df,
    load_daily_metrics_df,
)


def _apply_theme() -> None:
    """Apply minimalist dark dashboard styling."""
    st.markdown(
        """
        <style>
            .stApp {
                background-color: #0f1117;
                color: #e6e8ef;
            }
            [data-testid="stMetricValue"] {
                color: #e6e8ef;
            }
            .dashboard-title {
                font-size: 1.6rem;
                font-weight: 700;
                letter-spacing: 0.02rem;
                margin-bottom: 0.5rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _fatigue_color(level: str) -> str:
    return {"Green": "#2ecc71", "Yellow": "#f1c40f", "Red": "#e74c3c"}.get(level, "#95a5a6")


def _render_acwr_gauge(acwr: float) -> go.Figure:
    """Build ACWR gauge chart."""
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=acwr,
            title={"text": "ACWR"},
            gauge={
                "axis": {"range": [0, 2.0]},
                "bar": {"color": "#00bcd4"},
                "steps": [
                    {"range": [0, 0.8], "color": "#1b4332"},
                    {"range": [0.8, 1.3], "color": "#6b5e00"},
                    {"range": [1.3, 2.0], "color": "#5b1a1a"},
                ],
            },
        )
    )
    fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=40, b=20), height=240)
    return fig


def _render_training_load_chart(weekly: pd.DataFrame) -> go.Figure:
    """Weekly training load line chart with rolling average."""
    df = weekly.copy()
    if df.empty:
        return go.Figure().update_layout(template="plotly_dark", title="Weekly Training Load")

    df["rolling_4w"] = df["total_training_load"].rolling(4, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["week_start"],
            y=df["total_training_load"],
            mode="lines+markers",
            name="Weekly Load",
            line=dict(color="#00bcd4", width=2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["week_start"],
            y=df["rolling_4w"],
            mode="lines",
            name="4W Rolling Avg",
            line=dict(color="#f39c12", width=2, dash="dash"),
        )
    )
    fig.update_layout(template="plotly_dark", title="Weekly Training Load", height=320, margin=dict(l=20, r=20, t=50, b=20))
    return fig


def _render_discipline_breakdown(activities_df: pd.DataFrame) -> go.Figure:
    """Stacked bar chart for weekly discipline volume."""
    if activities_df.empty:
        return go.Figure().update_layout(template="plotly_dark", title="Volume by Discipline")

    frame = activities_df.copy()
    frame["sport_group"] = "Other"
    sport_lc = frame["sport"].astype(str).str.lower()
    frame.loc[sport_lc.str.contains("run"), "sport_group"] = "Running"
    frame.loc[sport_lc.str.contains("bike|cycl"), "sport_group"] = "Cycling"
    frame.loc[sport_lc.str.contains("swim"), "sport_group"] = "Swimming"

    weekly = (
        frame.groupby(["week_start", "sport_group"], as_index=False)["distance_km"]
        .sum()
        .sort_values("week_start")
    )

    fig = go.Figure()
    color_map = {
        "Running": "#00bcd4",
        "Cycling": "#27ae60",
        "Swimming": "#3498db",
        "Other": "#7f8c8d",
    }

    for sport in ["Running", "Cycling", "Swimming", "Other"]:
        sport_df = weekly[weekly["sport_group"] == sport]
        if not sport_df.empty:
            fig.add_trace(
                go.Bar(
                    x=sport_df["week_start"],
                    y=sport_df["distance_km"],
                    name=sport,
                    marker_color=color_map[sport],
                )
            )

    fig.update_layout(
        template="plotly_dark",
        title="Volume by Discipline (km)",
        barmode="stack",
        height=320,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def _render_efficiency_chart(efficiency_df: pd.DataFrame) -> go.Figure:
    """Efficiency trend line for the last 8 weeks."""
    if efficiency_df.empty:
        return go.Figure().update_layout(template="plotly_dark", title="Zone 2 Efficiency Trend")

    fig = go.Figure(
        go.Scatter(
            x=efficiency_df["week_start"],
            y=efficiency_df["efficiency"],
            mode="lines+markers",
            line=dict(color="#e67e22", width=2),
            name="Efficiency",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title="Zone 2 Efficiency Trend (Pace / HR)",
        height=320,
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def main() -> None:
    """Render triathlon performance dashboard."""
    st.set_page_config(page_title="Triathlon Performance Dashboard", layout="wide")
    _apply_theme()
    init_db()

    st.markdown('<div class="dashboard-title">Triathlon Performance Dashboard</div>', unsafe_allow_html=True)

    with st.sidebar:
        st.subheader("Garmin Connect Sync")
        email = st.text_input("Garmin Email", value=GARMIN_EMAIL)
        password_input = st.text_input("Garmin Password", type="password")
        password = password_input or GARMIN_PASSWORD
        default_end = date.today()
        default_start = default_end - timedelta(days=30)
        start_date = st.date_input("Start Date", value=default_start)
        end_date = st.date_input("End Date", value=default_end)
        sync_clicked = st.button("Sync Activities", type="primary")

        if sync_clicked:
            try:
                result = import_garmin_connect(
                    email=email,
                    password=password,
                    start_date=start_date,
                    end_date=end_date,
                )
                st.success(
                    f"Synced {result['inserted']} activities; "
                    f"skipped {result['skipped_duplicates']} duplicates."
                )
            except Exception as exc:
                st.error(str(exc))

        if GARMIN_EMAIL:
            st.caption("Using GARMIN_EMAIL from .env (editable above).")
        if GARMIN_PASSWORD and not password_input:
            st.caption("Using GARMIN_PASSWORD from .env.")

        with st.expander("Fallback: CSV Upload"):
            upload = st.file_uploader("Upload Garmin CSV", type=["csv"])
            if upload is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                    tmp.write(upload.getbuffer())
                    temp_path = Path(tmp.name)

                try:
                    result = import_garmin_csv(str(temp_path))
                    st.success(
                        f"Imported {result['inserted']} activities; "
                        f"skipped {result['skipped_duplicates']} duplicates."
                    )
                except Exception as exc:
                    st.error(f"Import failed: {exc}")
                finally:
                    temp_path.unlink(missing_ok=True)

    activities_df = load_activities_df()
    daily_metrics_df = load_daily_metrics_df()

    weekly = compute_weekly_totals(activities_df)
    acwr = compute_acwr(activities_df)
    fatigue = compute_fatigue_score(acwr=acwr, daily_metrics_df=daily_metrics_df)
    efficiency = compute_efficiency_trend(activities_df)

    latest_week = weekly.iloc[-1] if not weekly.empty else None
    weekly_hours = (float(latest_week["total_duration"]) / 60.0) if latest_week is not None else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Weekly Training Hours", f"{weekly_hours:.1f}h")
    with col2:
        st.plotly_chart(_render_acwr_gauge(acwr), use_container_width=True)
    with col3:
        st.metric("Fatigue", fatigue.level, f"Score {fatigue.score:.2f}")
        st.markdown(
            f"<div style='color:{_fatigue_color(fatigue.level)};font-size:0.9rem;'>"
            f"Fatigue status: {fatigue.level}</div>",
            unsafe_allow_html=True,
        )
    col4.metric("Compliance", "--", "TODO")

    st.plotly_chart(_render_training_load_chart(weekly), use_container_width=True)

    lower_left, lower_right = st.columns(2)
    with lower_left:
        st.plotly_chart(_render_discipline_breakdown(activities_df), use_container_width=True)
    with lower_right:
        st.plotly_chart(_render_efficiency_chart(efficiency), use_container_width=True)


if __name__ == "__main__":
    main()
