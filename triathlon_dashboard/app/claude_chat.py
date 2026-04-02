"""Claude AI client and Garmin data formatter for training analysis."""

from __future__ import annotations

import json
from typing import Any

try:
    import anthropic
except ImportError:
    anthropic = None

_SYSTEM_PROMPT = """\
You are an expert triathlon coach and sports scientist with deep knowledge of \
endurance training, recovery science, and performance optimization.

The athlete has provided their Garmin Connect data below. Use this data to give \
specific, evidence-based coaching advice. Reference actual numbers from their data \
when making recommendations. Be concise but thorough.

{data_context}
"""


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict/list structures."""
    current = obj
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        elif isinstance(current, list) and isinstance(key, int):
            try:
                current = current[key]
            except IndexError:
                return default
        else:
            return default
    return current if current is not None else default


def _fmt(value: Any, unit: str = "", precision: int = 0) -> str:
    """Format a numeric value or return '--' if missing."""
    if value is None:
        return "--"
    try:
        v = float(value)
        if precision == 0:
            return f"{int(round(v))}{unit}"
        return f"{v:.{precision}f}{unit}"
    except (TypeError, ValueError):
        return "--"


def _extract_sleep_hours(sleep_day: dict) -> str:
    """Extract total sleep hours from Garmin sleep payload."""
    if not isinstance(sleep_day, dict):
        return "--"
    # Try dailySleepDTO first, then top-level
    dto = sleep_day.get("dailySleepDTO") or sleep_day
    seconds = dto.get("sleepTimeSeconds") or dto.get("totalSleepSeconds")
    if seconds:
        return f"{seconds / 3600:.1f}h"
    return "--"


def _extract_sleep_score(sleep_day: dict) -> str:
    if not isinstance(sleep_day, dict):
        return "--"
    score = _safe_get(sleep_day, "dailySleepDTO", "sleepScores", "overall", "value")
    if score is None:
        score = _safe_get(sleep_day, "sleepScores", "overall", "value")
    return _fmt(score)


def _extract_avg_stress(stress_day: Any) -> str:
    """Extract average stress from all-day stress payload."""
    if isinstance(stress_day, dict):
        avg = stress_day.get("avgStressLevel") or stress_day.get("averageStressLevel")
        return _fmt(avg)
    if isinstance(stress_day, list):
        values = [
            item.get("stressLevel", 0) for item in stress_day
            if isinstance(item, dict) and item.get("stressLevel", -1) >= 0
        ]
        if values:
            return _fmt(sum(values) / len(values))
    return "--"


def _extract_body_battery(bb_day: Any) -> str:
    """Extract body battery start/end from payload."""
    entries = bb_day if isinstance(bb_day, list) else []
    if not entries:
        if isinstance(bb_day, dict):
            entries = bb_day.get("bodyBatteryValuesArray") or []
    if entries:
        charged = [e for e in entries if isinstance(e, (list, dict))]
        values = []
        for e in charged:
            if isinstance(e, list) and len(e) >= 2:
                values.append(e[1])
            elif isinstance(e, dict):
                v = e.get("value") or e.get("bodyBatteryLevel")
                if v is not None:
                    values.append(v)
        if values:
            return f"start={values[0]}, end={values[-1]}"
    return "--"


def _extract_hrv(hrv_day: dict) -> str:
    if not isinstance(hrv_day, dict):
        return "--"
    summary = hrv_day.get("hrvSummary") or hrv_day
    rmssd = summary.get("rmssd") or summary.get("lastNight5MinHighHrv")
    weekly = summary.get("weeklyAvg")
    parts = []
    if rmssd:
        parts.append(f"nightly={_fmt(rmssd)}ms")
    if weekly:
        parts.append(f"weekly_avg={_fmt(weekly)}ms")
    return ", ".join(parts) if parts else "--"


def _extract_training_readiness(tr_day: Any) -> str:
    if isinstance(tr_day, dict):
        score = tr_day.get("score") or tr_day.get("trainingReadinessScore")
        level = tr_day.get("level") or tr_day.get("trainingReadinessLevel") or ""
        if score is not None:
            return f"{_fmt(score)} ({level})" if level else _fmt(score)
    if isinstance(tr_day, list) and tr_day:
        return _extract_training_readiness(tr_day[0])
    return "--"


def _extract_training_status(ts_day: Any) -> str:
    if isinstance(ts_day, dict):
        status = ts_day.get("trainingStatusPhrase") or ts_day.get("trainingStatus") or ""
        load = ts_day.get("trainingLoad") or ts_day.get("latestTrainingLoad")
        if status:
            return f"{status} (load={_fmt(load)})" if load else status
    if isinstance(ts_day, list) and ts_day:
        return _extract_training_status(ts_day[0])
    return "--"


def _extract_spo2(spo2_day: dict) -> str:
    if not isinstance(spo2_day, dict):
        return "--"
    avg = spo2_day.get("averageSpO2") or spo2_day.get("avgSpO2")
    return f"{_fmt(avg)}%" if avg else "--"


def _extract_respiration(resp_day: dict) -> str:
    if not isinstance(resp_day, dict):
        return "--"
    avg = resp_day.get("avgBreathingRate") or resp_day.get("averageRespirationValue")
    return f"{_fmt(avg, ' breaths/min')}" if avg else "--"


def _extract_intensity_minutes(im_day: Any) -> str:
    if isinstance(im_day, dict):
        moderate = im_day.get("moderateIntensityMinutes", 0) or 0
        vigorous = im_day.get("vigorousIntensityMinutes", 0) or 0
        return f"moderate={moderate}min, vigorous={vigorous}min"
    return "--"


def _format_activity(act: dict) -> str:
    """Format a single activity as a compact text line."""
    sport = act.get("activityType", {})
    if isinstance(sport, dict):
        sport = sport.get("typeKey") or sport.get("typeId") or "Activity"
    sport = str(sport).replace("_", " ").title()

    duration_sec = act.get("duration") or 0
    duration_min = int(duration_sec / 60) if duration_sec else 0

    dist_m = act.get("distance") or 0
    dist_km = dist_m / 1000.0 if dist_m else 0

    avg_hr = act.get("averageHR") or act.get("avgHr")
    training_load = act.get("activityTrainingLoad") or act.get("trainingLoad")
    avg_power = act.get("averagePower") or act.get("avgPower")

    parts = [f"{sport} {duration_min}min"]
    if dist_km > 0.1:
        parts.append(f"{dist_km:.1f}km")
    if avg_hr:
        parts.append(f"HR={_fmt(avg_hr)}bpm")
    if training_load:
        parts.append(f"load={_fmt(training_load)}")
    if avg_power:
        parts.append(f"power={_fmt(avg_power)}W")
    return "  - " + ", ".join(parts)


def format_garmin_context(data: dict[str, Any]) -> str:
    """Convert raw Garmin data dict into a readable text block for Claude.

    Args:
        data: Output from fetch_all_garmin_data().

    Returns:
        Human-readable multi-line string summarising all Garmin data.
    """
    lines: list[str] = []
    date_range = data.get("date_range", {})
    days = date_range.get("days", "?")
    start = date_range.get("start", "")
    end = date_range.get("end", "")
    lines.append(f"## Garmin Data: {start} to {end} ({days} days)\n")

    # --- Daily data ---
    all_dates = sorted(data.get("summary", {}).keys())
    activities_by_date: dict[str, list[dict]] = {}
    for act in (data.get("activities") or []):
        if isinstance(act, dict):
            act_date = (act.get("startTimeLocal") or act.get("startTimeGMT") or "")[:10]
            activities_by_date.setdefault(act_date, []).append(act)

    for d in all_dates:
        lines.append(f"=== {d} ===")

        # Summary
        summary = data.get("summary", {}).get(d) or {}
        steps = summary.get("totalSteps") or summary.get("steps")
        calories = summary.get("totalKilocalories") or summary.get("activeKilocalories")
        dist_m = summary.get("totalDistanceMeters")
        dist_km = (dist_m / 1000.0) if dist_m else None
        resting_hr = summary.get("restingHeartRate")

        step_str = _fmt(steps)
        cal_str = _fmt(calories, " kcal")
        dist_str = _fmt(dist_km, "km", 1) if dist_km else "--"
        rhr_str = _fmt(resting_hr, " bpm")
        lines.append(f"Steps: {step_str} | Calories: {cal_str} | Distance: {dist_str} | Resting HR: {rhr_str}")

        # HR & HRV
        hr_day = data.get("heart_rate", {}).get(d) or {}
        rhr2 = hr_day.get("restingHeartRate")
        if rhr2 and not resting_hr:
            lines.append(f"Resting HR: {_fmt(rhr2, ' bpm')}")

        hrv_str = _extract_hrv(data.get("hrv", {}).get(d))
        if hrv_str != "--":
            lines.append(f"HRV: {hrv_str}")

        # Sleep
        sleep_day = data.get("sleep", {}).get(d) or {}
        sleep_hrs = _extract_sleep_hours(sleep_day)
        sleep_score = _extract_sleep_score(sleep_day)
        if sleep_hrs != "--":
            lines.append(f"Sleep: {sleep_hrs} | Sleep score: {sleep_score}")

        # Body Battery & Stress
        bb_str = _extract_body_battery(data.get("body_battery", {}).get(d))
        stress_str = _extract_avg_stress(data.get("stress", {}).get(d))
        if bb_str != "--":
            lines.append(f"Body Battery: {bb_str}")
        if stress_str != "--":
            lines.append(f"Stress avg: {stress_str}")

        # SpO2 & Respiration
        spo2_str = _extract_spo2(data.get("spo2", {}).get(d) or {})
        resp_str = _extract_respiration(data.get("respiration", {}).get(d) or {})
        if spo2_str != "--":
            lines.append(f"SpO2: {spo2_str}")
        if resp_str != "--":
            lines.append(f"Respiration: {resp_str}")

        # Training readiness / status
        tr_str = _extract_training_readiness(data.get("training_readiness", {}).get(d))
        ts_str = _extract_training_status(data.get("training_status", {}).get(d))
        if tr_str != "--":
            lines.append(f"Training Readiness: {tr_str}")
        if ts_str != "--":
            lines.append(f"Training Status: {ts_str}")

        # Intensity minutes
        im_str = _extract_intensity_minutes(data.get("intensity_minutes", {}).get(d))
        if im_str != "--":
            lines.append(f"Intensity Minutes: {im_str}")

        # Activities that day
        day_acts = activities_by_date.get(d, [])
        if day_acts:
            lines.append("Activities:")
            for act in day_acts:
                lines.append(_format_activity(act))

        lines.append("")

    # --- Body composition (latest available) ---
    bc_data = data.get("body_composition")
    if bc_data:
        if isinstance(bc_data, dict):
            entries = bc_data.get("dateWeightList") or bc_data.get("totalAverage") or []
        else:
            entries = bc_data if isinstance(bc_data, list) else []
        if entries:
            latest = entries[-1] if isinstance(entries, list) else entries
            if isinstance(latest, dict):
                weight = latest.get("weight") or latest.get("weightInGrams")
                if weight and weight > 500:
                    weight = weight / 1000.0  # grams to kg
                bmi = latest.get("bmi")
                body_fat = latest.get("bodyFat") or latest.get("bodyFatPercent")
                parts = []
                if weight:
                    parts.append(f"weight={_fmt(weight, 'kg', 1)}")
                if bmi:
                    parts.append(f"BMI={_fmt(bmi, precision=1)}")
                if body_fat:
                    parts.append(f"body_fat={_fmt(body_fat, '%', 1)}")
                if parts:
                    lines.append(f"## Body Composition (latest): {', '.join(parts)}\n")

    # --- Personal records ---
    prs = data.get("personal_records") or []
    if prs and isinstance(prs, list):
        lines.append("## Personal Records")
        for pr in prs[:20]:  # cap at 20 to avoid excessive context
            if not isinstance(pr, dict):
                continue
            pr_type = pr.get("typeId") or pr.get("activityType") or "Record"
            value = pr.get("value")
            unit = pr.get("unit") or ""
            activity = pr.get("activityName") or ""
            pr_date = (pr.get("prStartTimeGmt") or pr.get("prStartTimeLocal") or "")[:10]
            line = f"  - {pr_type}: {_fmt(value)} {unit}"
            if activity:
                line += f" ({activity})"
            if pr_date:
                line += f" on {pr_date}"
            lines.append(line)
        lines.append("")

    # --- Fetch errors (informational) ---
    errors = data.get("errors") or []
    if errors:
        lines.append(f"## Data Notes")
        lines.append(f"{len(errors)} endpoint(s) returned no data (normal for some Garmin devices/plans).")
        lines.append("")

    return "\n".join(lines)


def send_message(
    messages: list[dict[str, str]],
    garmin_context: str,
    user_message: str,
    api_key: str,
    days: int = 7,
) -> str:
    """Send a message to Claude with Garmin data as context.

    Args:
        messages: Prior conversation history (list of role/content dicts).
        garmin_context: Formatted Garmin data string from format_garmin_context().
        user_message: The new user message to send.
        api_key: Anthropic API key.
        days: Number of days of data (used in system prompt).

    Returns:
        Claude's response text.
    """
    if anthropic is None:
        raise ImportError("Missing dependency: anthropic. Run: pip install anthropic")
    if not api_key.strip():
        raise ValueError("ANTHROPIC_API_KEY is required.")

    system = _SYSTEM_PROMPT.format(data_context=garmin_context)

    client = anthropic.Anthropic(api_key=api_key.strip())
    all_messages = messages + [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system,
        messages=all_messages,
    )
    return response.content[0].text
