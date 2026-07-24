# Injury Data POC

FastAPI POC showcasing the Sportmonks injury dataset: coverage, quality, and analytical linkage.

## Setup and build

```bash
uv venv --python 3.14
uv pip install -r app/requirements.txt
uv run --python 3.14 -m app.etl
```

`app/app.db` is derived from `data/raw/sportmonks/fixtures/` and `coverage.db`; building it requires no network access.

## Run and test

```bash
uv run --python 3.14 -m uvicorn app.main:app --reload --port 8000
uv run --python 3.14 -m pytest tests/ -v
```

- `http://localhost:8000/` — coverage and quality
- `http://localhost:8000/analytics` — linked aggregations
- `http://localhost:8000/injuries` — explorable injury records
- `http://localhost:8000/docs` — API documentation
