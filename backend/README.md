# terrasim backend

FastAPI simulation + data API for the terrasim frontend. Pure simulation engines
in `app/engine/` (no I/O), route glue in `app/main.py`. Ships without a database
or heavy geospatial stack — everything is loaded in memory from the offline
bundles in `data/bundles/<city>/`.

## Stack

- Python 3.14
- FastAPI + uvicorn + Pydantic
- NumPy (DEM/array math) + Shapely (vector geometry)

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Health check: `http://127.0.0.1:8000/api/health`

## Tests

```bash
uv run pytest
```

Engine tests (`tests/test_engine.py`) run fast with no network; API tests
(`tests/test_api.py`) need the bundles present (they are committed).

## Layout

```
app/
  main.py         FastAPI routes + response unification
  schemas.py      Pydantic request/response models (FloodScenario, EarthquakeScenario, ScenarioAsset, ...)
  datasets.py     Offline bundle loader (DATA_ROOT default = <repo>/data/bundles)
  engine/         Pure simulation, no I/O
    grid.py           shared elevation-grid toolbox
    flood.py          flow-routed, volume-conserving flood
    earthquake.py     simple attenuation proxy (relative intensity bands)
    suitability.py    green/yellow/red land scoring
    exposure.py       per-asset hazard verdicts
    terrain_tiles.py  Terrarium-encoded elevation PNG server (zero deps)
tests/
  test_engine.py  fast, offline physics tests
  test_api.py     bundle-backed endpoint tests
```

## Endpoints

See `../README.md` for the full API table. Highlights:

- `GET /api/cities/{id}/terrain/{z}/{x}/{y}.png` — elevation tiles for 3D terrain.
- `POST /api/simulate/flood` — origin is exactly one of `source` (point),
  `river_id` (mapped river), or `river_path` (planner-drawn channel).
- `POST /api/cities/{id}/suitability` — New-City land scoring.