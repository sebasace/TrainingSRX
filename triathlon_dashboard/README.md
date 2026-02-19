# Triathlon Performance Dashboard (MVP)

Production-minded local MVP for triathlon performance monitoring, designed with modular components that can later migrate to FastAPI, PostgreSQL, and cloud deployment.

## Project Structure

```
triathlon_dashboard/
├── app/
│   ├── __init__.py
│   ├── dashboard.py
│   ├── config.py
│   ├── db.py
│   ├── models.py
│   ├── metrics.py
│   ├── ingestion.py
├── data/
│   ├── raw/
│   └── processed/
├── database/
│   └── triathlon.db
├── requirements.txt
└── README.md
```

## Features

- Garmin Connect ingestion via `python-garminconnect` (`import_garmin_connect(...)`)
- CSV ingestion fallback (`import_garmin_csv(file_path: str)`)
- SQLite storage with deduplication by `activity_id`
- Metrics:
  - Weekly totals (duration, load, run/bike/swim volume)
  - ACWR (7-day acute / 28-day chronic weekly average)
  - Fatigue score (training + resting HR + sleep deltas)
  - 4-week rolling load averages
  - Running efficiency trend (`avg_pace / avg_hr`) for last 8 weeks
- Streamlit dark dashboard with Plotly charts

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create environment file for Garmin credentials:

```bash
cp .env.example .env
```

Edit `.env` and set:
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`

4. Run the dashboard from inside `triathlon_dashboard`:

```bash
streamlit run app/dashboard.py
```

## Data Ingestion

Use the sidebar sync form to pull activities directly from Garmin Connect.
Credentials are loaded from `.env` automatically and can be overridden in the UI.

CSV upload remains available as a fallback.

Expected canonical fields (aliases handled automatically):
- `activity_id`
- `date`
- `sport`
- `duration_min`
- `distance_km`
- `avg_hr`
- `training_load`
- `avg_pace`
- `avg_power`

Duplicate `activity_id` rows are skipped.

## Database Tables

- `raw_activities`
- `daily_metrics`
- `weekly_summary` (optional materialization table for future use)

Tables are auto-created on first run.

## Architecture Notes

- Business logic is isolated in `metrics.py` and `ingestion.py`
- Presentation logic is isolated in `dashboard.py`
- SQLAlchemy models and DB session handling support future backend extraction
- TODO markers indicate planned FastAPI/PostgreSQL/cloud migration points

## Future Migration Path

- Replace SQLite URL in `app/config.py` with PostgreSQL DSN
- Expose `ingestion.py` + `metrics.py` via FastAPI service layer
- Move dashboard authentication and user profiles into backend
- Deploy DB + API to cloud with managed services
