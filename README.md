# Injuries: UEFA League Injury Database

A Python project for collecting, storing, and analyzing player injury data across 55 UEFA member associations' top-tier football (soccer) leagues.

## Overview

This project consists of two main components:

### 1. **Coverage Probe** (`probe.py`)
A feasibility tool (v0.1) that investigates injury data availability across football APIs.

- **Purpose**: Determines whether injury data exists for UEFA leagues and how far back historical data extends
- **Scope**: Tests across:
  - Big 5 leagues (England, Spain, Germany, Italy, France)
  - 5 small UEFA nations (for sampling edge cases)
  - All 55 UEFA member associations (in full run)
  - Last 3 seasons (2023/24, 2024/25, 2025/26)
- **Data Sources**: 
  - [API-Football](https://www.api-football.com/)
  - [Sportmonks](https://www.sportmonks.com/)
- **Output**: SQLite database with coverage matrix and injury records

### 2. **Web Application** (`app/`)
A FastAPI-based proof-of-concept dashboard for exploring injury data.

**Features:**
- **Coverage Dashboard**: Overview of data availability by league and season
- **Analytics**: Visualizations of injuries by:
  - Player position
  - Age band
  - Injury type
  - Player nationality
  - League
  - Month/temporal trends
- **Injury Lookup**: Searchable, filterable list of all recorded injuries
  - Filter by country, position, injury type
  - Toggle ongoing-only injuries
  - Paginated results
- **Player Timeline**: Detailed injury history for individual players

**Security**: HTTP Basic authentication (credentials required to access all pages and APIs)

## Project Structure

```
injuries/
├── probe.py                    # Feasibility probe tool
├── coverage.db                 # SQLite database from probe runs
├── requirements.txt            # Project dependencies
├── app/
│   ├── main.py                # FastAPI application and routes
│   ├── db.py                  # Database connection and read-only access
│   ├── queries.py             # SQL queries for injury analytics
│   ├── etl.py                 # ETL pipeline for ingesting data
│   ├── app.db                 # Application database with injury records
│   ├── templates/             # Jinja2 HTML templates
│   │   ├── coverage.html
│   │   ├── analytics.html
│   │   ├── injuries.html
│   │   └── player.html
│   └── static/                # CSS, JavaScript, static assets
├── scripts/                   # Sportmonks utility scripts
│   ├── sm_explore.py          # Exploratory data analysis
│   ├── sm_sweep55.py          # Full 55-league coverage sweep
│   ├── sm_resolve_*.py        # Entity and season resolution
│   ├── sm_check_*.py          # Data validation utilities
│   └── ...                    # Additional tools
├── data/                      # Raw/cached data from API sources
├── logs/                      # Detailed logs from probe and ETL runs
└── docs/                      # Documentation
```

## Getting Started

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run the Coverage Probe
Test injury data availability across APIs:
```bash
python probe.py --provider both         # Test both APIs (default)
python probe.py --provider apifootball  # Test API-Football only
python probe.py --provider sportmonks   # Test Sportmonks only
python probe.py --targets all           # Test all 55 UEFA leagues
```

### Start the Web Application
```bash
cd app
uvicorn main:app --reload
```

Then visit `http://localhost:8000` in your browser. You'll be prompted to authenticate.

## Credentials
- **Username**: `fernando`
- **Password**: `1nd3p3nd13nt3` (hardcoded in demo; change in production)

## Database

The project uses SQLite for simplicity:
- `coverage.db`: Results from API feasibility tests
- `app/app.db`: Application database with normalized injury data

## Dependencies

- **FastAPI**: Web framework
- **Uvicorn**: ASGI server
- **requests**: HTTP client for API calls
- **python-dotenv**: Environment variable management
- **SQLite3**: Database (built-in)

See `requirements.txt` for full dependency list with versions.

## Development Notes

- This is a **proof-of-concept** project; the probe is a "throwaway feasibility tool, not an ingestion pipeline"
- Injury data is sourced from external APIs—availability and coverage vary by league and season
- The web app requires authentication and uses read-only database access
- Logs are stored in `logs/` for debugging and audit trails

## License

Private project
