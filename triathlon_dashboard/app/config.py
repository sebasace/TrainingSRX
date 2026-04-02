"""Application configuration and path helpers."""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional runtime dependency
    load_dotenv = None

# TODO: Replace with environment-based settings for FastAPI/cloud deployments.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "triathlon.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
ENV_PATH = BASE_DIR / ".env"

# Load local environment variables for development.
if load_dotenv is not None:
    load_dotenv(ENV_PATH)

GARMIN_EMAIL = os.getenv("GARMIN_EMAIL", "")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def ensure_directories() -> None:
    """Create required local directories if they do not already exist."""
    for directory in (DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, DATABASE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
