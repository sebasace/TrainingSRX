"""Garmin data ingestion services (CSV + Garmin Connect)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from app.db import get_session, init_db
from app.models import RawActivity

try:
    from garminconnect import Garmin
except ImportError:  # pragma: no cover - optional dependency at runtime
    Garmin = None

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize incoming Garmin-style columns to canonical schema names."""
    normalized = {col: col.strip().lower().replace(" ", "_") for col in df.columns}
    df = df.rename(columns=normalized)

    alias_map = {
        "activity_id": "activity_id",
        "id": "activity_id",
        "activity_type": "sport",
        "type": "sport",
        "sport_type": "sport",
        "date": "date",
        "start_time": "date",
        "start_date": "date",
        "duration": "duration_min",
        "duration_min": "duration_min",
        "moving_time": "duration_min",
        "distance": "distance_km",
        "distance_km": "distance_km",
        "avg_hr": "avg_hr",
        "average_heart_rate": "avg_hr",
        "training_load": "training_load",
        "exercise_load": "training_load",
        "avg_pace": "avg_pace",
        "average_pace": "avg_pace",
        "avg_power": "avg_power",
        "average_power": "avg_power",
    }

    renamed = {}
    for col in df.columns:
        renamed[col] = alias_map.get(col, col)
    return df.rename(columns=renamed)


def _coerce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dataframe to target schema types and defaults."""
    expected = [
        "activity_id",
        "date",
        "sport",
        "duration_min",
        "distance_km",
        "avg_hr",
        "training_load",
        "avg_pace",
        "avg_power",
    ]

    for col in expected:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[expected].copy()

    df["activity_id"] = df["activity_id"].fillna("").astype(str).str.strip()
    missing_id_mask = df["activity_id"] == ""
    if missing_id_mask.any():
        df.loc[missing_id_mask, "activity_id"] = [str(uuid4()) for _ in range(missing_id_mask.sum())]

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df["sport"] = df["sport"].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")

    numeric_cols = ["duration_min", "distance_km", "avg_hr", "training_load", "avg_pace", "avg_power"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Convert potential meters into kilometers if values appear unrealistically large.
    if "distance_km" in df.columns and df["distance_km"].dropna().gt(500).any():
        df["distance_km"] = df["distance_km"] / 1000.0

    df = df.dropna(subset=["date"])  # Required for downstream date-based metrics.
    return df


def _insert_records(records: list[dict[str, Any]]) -> dict[str, int]:
    """Insert prepared records into raw_activities while skipping duplicates."""
    if not records:
        return {"inserted": 0, "skipped_duplicates": 0, "total_rows": 0}

    incoming_ids = [rec["activity_id"] for rec in records]
    with get_session() as session:
        existing_ids = {
            activity_id
            for (activity_id,) in session.query(RawActivity.activity_id)
            .filter(RawActivity.activity_id.in_(incoming_ids))
            .all()
        }
        to_insert = [rec for rec in records if rec["activity_id"] not in existing_ids]
        if to_insert:
            session.bulk_insert_mappings(RawActivity, to_insert)

    return {
        "inserted": len(to_insert),
        "skipped_duplicates": len(records) - len(to_insert),
        "total_rows": len(records),
    }


def import_garmin_csv(file_path: str) -> dict[str, Any]:
    """Import Garmin CSV records into raw_activities, skipping duplicate activity IDs.

    Args:
        file_path: Path to a Garmin CSV export.

    Returns:
        Summary dict with inserted/skipped counters.
    """
    init_db()

    csv_path = Path(file_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    raw_df = pd.read_csv(csv_path)
    if raw_df.empty:
        return {"inserted": 0, "skipped_duplicates": 0, "total_rows": 0}

    prepared_df = _coerce_schema(_normalize_columns(raw_df))
    if prepared_df.empty:
        return {"inserted": 0, "skipped_duplicates": len(raw_df), "total_rows": len(raw_df)}

    return _insert_records(prepared_df.to_dict(orient="records"))


def _to_float(value: Any) -> float | None:
    """Convert value to float; return None for invalid values."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_nested(data: dict[str, Any], key: str, nested_key: str) -> Any:
    """Safely get nested dict value."""
    nested = data.get(key)
    if isinstance(nested, dict):
        return nested.get(nested_key)
    return None


def _sport_name(activity_type: Any) -> str:
    """Extract sport name from Garmin activity type payload."""
    if isinstance(activity_type, dict):
        return str(activity_type.get("typeKey") or activity_type.get("typeId") or "Unknown")
    if isinstance(activity_type, str):
        return activity_type
    return "Unknown"


def _garmin_activity_to_record(activity: dict[str, Any]) -> dict[str, Any]:
    """Map a Garmin Connect activity payload to raw_activities schema."""
    activity_id = str(activity.get("activityId") or uuid4())
    date_value = activity.get("startTimeLocal") or activity.get("startTimeGMT") or activity.get("date")
    sport = _sport_name(activity.get("activityType"))

    duration_sec = _to_float(activity.get("duration") or _get_nested(activity, "summaryDTO", "duration"))
    distance_m = _to_float(activity.get("distance") or _get_nested(activity, "summaryDTO", "distance"))
    avg_hr = _to_float(activity.get("averageHR") or _get_nested(activity, "summaryDTO", "averageHR"))
    avg_power = _to_float(activity.get("averagePower") or _get_nested(activity, "summaryDTO", "averagePower"))
    avg_speed = _to_float(activity.get("averageSpeed") or _get_nested(activity, "summaryDTO", "averageSpeed"))

    training_load = _to_float(
        activity.get("activityTrainingLoad")
        or activity.get("trainingLoad")
        or _get_nested(activity, "summaryDTO", "trainingLoad")
    )

    avg_pace = _to_float(activity.get("averagePace") or _get_nested(activity, "summaryDTO", "averagePace"))
    if avg_pace is None and avg_speed and avg_speed > 0:
        avg_pace = 1000.0 / (avg_speed * 60.0)  # minutes per km, speed in m/s.

    return {
        "activity_id": activity_id,
        "date": date_value,
        "sport": sport,
        "duration_min": (duration_sec / 60.0) if duration_sec is not None else None,
        "distance_km": (distance_m / 1000.0) if distance_m is not None else None,
        "avg_hr": avg_hr,
        "training_load": training_load,
        "avg_pace": avg_pace,
        "avg_power": avg_power,
    }


def import_garmin_connect(
    email: str,
    password: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Import Garmin activities directly from Garmin Connect.

    Args:
        email: Garmin Connect account email.
        password: Garmin Connect account password.
        start_date: Inclusive start date (defaults to last 30 days).
        end_date: Inclusive end date (defaults to today).

    Returns:
        Summary dict with inserted/skipped counters.
    """
    init_db()

    if Garmin is None:
        raise ImportError("Missing dependency: garminconnect. Install requirements first.")
    if not email.strip() or not password:
        raise ValueError("Garmin Connect email and password are required.")

    end_date = end_date or date.today()
    start_date = start_date or (end_date - timedelta(days=30))
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date.")

    # TODO: Replace direct credential flow with backend token exchange for API migration.
    client = Garmin(email=email.strip(), password=password)
    try:
        client.login()
        activities = client.get_activities_by_date(
            startdate=start_date.isoformat(),
            enddate=end_date.isoformat(),
        )
    except Exception as exc:
        raise RuntimeError(f"Garmin Connect sync failed: {exc}") from exc

    if not isinstance(activities, list) or not activities:
        return {"inserted": 0, "skipped_duplicates": 0, "total_rows": 0}

    raw_records = [_garmin_activity_to_record(activity) for activity in activities if isinstance(activity, dict)]
    prepared_df = _coerce_schema(pd.DataFrame(raw_records))
    if prepared_df.empty:
        return {"inserted": 0, "skipped_duplicates": len(raw_records), "total_rows": len(raw_records)}

    return _insert_records(prepared_df.to_dict(orient="records"))
