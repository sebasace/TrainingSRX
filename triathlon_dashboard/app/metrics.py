"""Performance metric computation service layer."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.db import ENGINE, init_db


@dataclass
class FatigueResult:
    """Fatigue score output for dashboard display."""

    score: float
    level: str


def _normalize_component(value: float | None, min_value: float, max_value: float, invert: bool = False) -> float:
    """Normalize scalar value to 0-1 interval with optional inversion."""
    if value is None or np.isnan(value):
        return 0.5
    clipped = float(np.clip(value, min_value, max_value))
    normalized = (clipped - min_value) / (max_value - min_value)
    return float(1.0 - normalized if invert else normalized)


def load_activities_df() -> pd.DataFrame:
    """Load activity table as a DataFrame for metric calculations."""
    init_db()
    query = text("SELECT * FROM raw_activities")
    df = pd.read_sql(query, ENGINE)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    numeric_cols = ["duration_min", "distance_km", "avg_hr", "training_load", "avg_pace", "avg_power"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date"])
    df["week_start"] = df["date"].dt.to_period("W-MON").apply(lambda x: x.start_time)
    return df


def load_daily_metrics_df() -> pd.DataFrame:
    """Load daily recovery metrics table."""
    init_db()
    query = text("SELECT * FROM daily_metrics")
    df = pd.read_sql(query, ENGINE)
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["sleep_hours", "resting_hr", "hrv"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date"])


def compute_weekly_totals(activities_df: pd.DataFrame) -> pd.DataFrame:
    """Compute weekly duration, load, and discipline-specific distance totals."""
    if activities_df.empty:
        return pd.DataFrame(
            columns=[
                "week_start",
                "total_duration",
                "total_training_load",
                "total_run_km",
                "total_bike_km",
                "total_swim_m",
            ]
        )

    base = activities_df.copy()
    base["sport_lc"] = base["sport"].astype(str).str.lower()

    weekly = (
        base.groupby("week_start", as_index=False)
        .agg(total_duration=("duration_min", "sum"), total_training_load=("training_load", "sum"))
        .sort_values("week_start")
    )

    run_km = (
        base[base["sport_lc"].str.contains("run")]
        .groupby("week_start")["distance_km"]
        .sum()
        .rename("total_run_km")
    )
    bike_km = (
        base[base["sport_lc"].str.contains("bike|cycl")]
        .groupby("week_start")["distance_km"]
        .sum()
        .rename("total_bike_km")
    )
    swim_m = (
        base[base["sport_lc"].str.contains("swim")]
        .groupby("week_start")["distance_km"]
        .sum()
        .mul(1000.0)
        .rename("total_swim_m")
    )

    weekly = weekly.merge(run_km, on="week_start", how="left")
    weekly = weekly.merge(bike_km, on="week_start", how="left")
    weekly = weekly.merge(swim_m, on="week_start", how="left")

    return weekly.fillna(0.0)


def compute_acwr(activities_df: pd.DataFrame, as_of_date: pd.Timestamp | None = None) -> float:
    """Compute Acute:Chronic Workload Ratio using 7d acute and 28d chronic windows."""
    if activities_df.empty:
        return 0.0

    data = activities_df[["date", "training_load"]].copy()
    data["date"] = pd.to_datetime(data["date"]).dt.floor("D")
    daily_load = data.groupby("date", as_index=False)["training_load"].sum().sort_values("date")

    if as_of_date is None:
        as_of_date = daily_load["date"].max()

    as_of_date = pd.to_datetime(as_of_date).floor("D")
    acute_start = as_of_date - pd.Timedelta(days=6)
    chronic_start = as_of_date - pd.Timedelta(days=27)

    acute_load = daily_load.loc[daily_load["date"].between(acute_start, as_of_date), "training_load"].sum()
    chronic_28d_load = daily_load.loc[daily_load["date"].between(chronic_start, as_of_date), "training_load"].sum()
    chronic_weekly_avg = chronic_28d_load / 4.0

    if chronic_weekly_avg <= 0:
        return 0.0
    return float(acute_load / chronic_weekly_avg)


def compute_fatigue_score(acwr: float, daily_metrics_df: pd.DataFrame) -> FatigueResult:
    """Compute fatigue score and status from training and recovery deltas."""
    if daily_metrics_df.empty:
        score = float(0.6 * acwr + 0.4 * 0.5)
        return FatigueResult(score=score, level=_fatigue_level(score))

    daily = daily_metrics_df.sort_values("date").copy()
    latest = daily.iloc[-1]
    last_14 = daily.tail(14)

    hr_14_avg = float(last_14["resting_hr"].mean()) if not last_14["resting_hr"].dropna().empty else np.nan
    sleep_14_avg = float(last_14["sleep_hours"].mean()) if not last_14["sleep_hours"].dropna().empty else np.nan

    hr_delta = float(latest.get("resting_hr", np.nan) - hr_14_avg) if not np.isnan(hr_14_avg) else np.nan
    sleep_delta = float(latest.get("sleep_hours", np.nan) - sleep_14_avg) if not np.isnan(sleep_14_avg) else np.nan

    hr_component = _normalize_component(hr_delta, min_value=-8, max_value=8, invert=False)
    sleep_component = _normalize_component(sleep_delta, min_value=-3, max_value=3, invert=True)

    score = float((0.6 * acwr) + (0.2 * hr_component) + (0.2 * sleep_component))
    return FatigueResult(score=score, level=_fatigue_level(score))


def _fatigue_level(score: float) -> str:
    """Map fatigue score to traffic-light level."""
    if score < 0.9:
        return "Green"
    if score < 1.2:
        return "Yellow"
    return "Red"


def compute_efficiency_trend(activities_df: pd.DataFrame) -> pd.DataFrame:
    """Compute running efficiency trend for recent weeks.

    Efficiency definition: avg_pace / avg_hr for running activities.
    """
    if activities_df.empty:
        return pd.DataFrame(columns=["week_start", "efficiency"])

    runs = activities_df.copy()
    runs = runs[runs["sport"].astype(str).str.lower().str.contains("run")]
    runs = runs.dropna(subset=["avg_pace", "avg_hr", "week_start"])
    runs = runs[runs["avg_hr"] > 0]

    if runs.empty:
        return pd.DataFrame(columns=["week_start", "efficiency"])

    runs["efficiency"] = runs["avg_pace"] / runs["avg_hr"]
    weekly = runs.groupby("week_start", as_index=False)["efficiency"].mean().sort_values("week_start")
    return weekly.tail(8)
