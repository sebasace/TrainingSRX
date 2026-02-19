"""SQLAlchemy models representing core domain tables."""

from __future__ import annotations

from sqlalchemy import Column, Date, Float, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class RawActivity(Base):
    """Raw activity records imported from Garmin exports."""

    __tablename__ = "raw_activities"

    activity_id = Column(String, primary_key=True)
    date = Column(Date, index=True, nullable=False)
    sport = Column(String, index=True, nullable=False)
    duration_min = Column(Float, nullable=True)
    distance_km = Column(Float, nullable=True)
    avg_hr = Column(Float, nullable=True)
    training_load = Column(Float, nullable=True)
    avg_pace = Column(Float, nullable=True)
    avg_power = Column(Float, nullable=True)


class DailyMetric(Base):
    """Daily recovery and readiness metrics."""

    __tablename__ = "daily_metrics"

    date = Column(Date, primary_key=True)
    sleep_hours = Column(Float, nullable=True)
    resting_hr = Column(Float, nullable=True)
    hrv = Column(Float, nullable=True)


class WeeklySummary(Base):
    """Optional materialized weekly summary metrics."""

    __tablename__ = "weekly_summary"

    week_start = Column(Date, primary_key=True)
    total_duration = Column(Float, nullable=True)
    total_training_load = Column(Float, nullable=True)
    total_run_km = Column(Float, nullable=True)
    total_bike_km = Column(Float, nullable=True)
    total_swim_m = Column(Float, nullable=True)
    acwr = Column(Float, nullable=True)
    fatigue_score = Column(Float, nullable=True)
