"""Comprehensive Garmin Connect data fetcher for Claude AI integration."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

try:
    from garminconnect import Garmin
except ImportError:
    Garmin = None


def fetch_all_garmin_data(
    email: str,
    password: str,
    days: int = 7,
) -> dict[str, Any]:
    """Authenticate and fetch all available Garmin data for the last `days` days.

    Each endpoint is fetched independently so a single failure doesn't abort
    the entire collection.

    Args:
        email: Garmin Connect account email.
        password: Garmin Connect account password.
        days: Number of days of history to fetch (default 7).

    Returns:
        Dict with keys: summary, heart_rate, sleep, stress, body_battery,
        spo2, respiration, hrv, training_readiness, training_status,
        intensity_minutes, activities, steps, body_composition,
        personal_records, errors.
    """
    if Garmin is None:
        raise ImportError("Missing dependency: garminconnect. Run: pip install garminconnect")
    if not email.strip() or not password:
        raise ValueError("Garmin Connect email and password are required.")

    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    date_strs = [d.isoformat() for d in dates]
    start_str = date_strs[0]
    end_str = date_strs[-1]

    client = Garmin(email=email.strip(), password=password)
    try:
        client.login()
    except Exception as exc:
        raise RuntimeError(f"Garmin Connect login failed: {exc}") from exc

    data: dict[str, Any] = {
        "summary": {},
        "heart_rate": {},
        "sleep": {},
        "stress": {},
        "body_battery": {},
        "spo2": {},
        "respiration": {},
        "hrv": {},
        "training_readiness": {},
        "training_status": {},
        "intensity_minutes": {},
        "activities": [],
        "steps": [],
        "body_composition": [],
        "personal_records": [],
        "errors": [],
        "date_range": {"start": start_str, "end": end_str, "days": days},
    }

    # --- Per-day endpoints ---
    for d in date_strs:
        try:
            data["summary"][d] = client.get_user_summary(d)
        except Exception as exc:
            data["errors"].append(f"summary {d}: {exc}")

        try:
            data["heart_rate"][d] = client.get_heart_rates(d)
        except Exception as exc:
            data["errors"].append(f"heart_rate {d}: {exc}")

        try:
            data["sleep"][d] = client.get_sleep_data(d)
        except Exception as exc:
            data["errors"].append(f"sleep {d}: {exc}")

        try:
            data["stress"][d] = client.get_all_day_stress(d)
        except Exception as exc:
            data["errors"].append(f"stress {d}: {exc}")

        try:
            data["body_battery"][d] = client.get_body_battery(d, d)
        except Exception as exc:
            data["errors"].append(f"body_battery {d}: {exc}")

        try:
            data["spo2"][d] = client.get_spo2_data(d)
        except Exception as exc:
            data["errors"].append(f"spo2 {d}: {exc}")

        try:
            data["respiration"][d] = client.get_respiration_data(d)
        except Exception as exc:
            data["errors"].append(f"respiration {d}: {exc}")

        try:
            data["hrv"][d] = client.get_hrv_data(d)
        except Exception as exc:
            data["errors"].append(f"hrv {d}: {exc}")

        try:
            data["training_readiness"][d] = client.get_training_readiness(d)
        except Exception as exc:
            data["errors"].append(f"training_readiness {d}: {exc}")

        try:
            data["training_status"][d] = client.get_training_status(d)
        except Exception as exc:
            data["errors"].append(f"training_status {d}: {exc}")

        try:
            data["intensity_minutes"][d] = client.get_intensity_minutes_week(d)
        except Exception as exc:
            data["errors"].append(f"intensity_minutes {d}: {exc}")

    # --- Range endpoints ---
    try:
        data["activities"] = client.get_activities_by_date(
            startdate=start_str,
            enddate=end_str,
        )
    except Exception as exc:
        data["errors"].append(f"activities: {exc}")

    try:
        data["steps"] = client.get_daily_steps(start_str, end_str)
    except Exception as exc:
        data["errors"].append(f"steps: {exc}")

    try:
        data["body_composition"] = client.get_body_composition(start_str, end_str)
    except Exception as exc:
        data["errors"].append(f"body_composition: {exc}")

    try:
        data["personal_records"] = client.get_personal_record()
    except Exception as exc:
        data["errors"].append(f"personal_records: {exc}")

    return data
