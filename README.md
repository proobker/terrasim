# terrasim

**Building Resilient Areas for Climate & Emergencies**

> Simulate today's risks. Plan tomorrow's resilient cities.

terrasim is a geospatial disaster-risk simulation and urban-planning platform. It has two modes:

1. **Existing City — Simulate & Assess**: pick a real area, run a hypothetical flood or earthquake scenario, and visualize estimated exposure of buildings, roads, and critical facilities.
2. **New City — Plan & Validate**: analyze an undeveloped area, place hospitals, schools, and housing, then stress-test the proposed layout — change the plan and simulate again.

The core loop is **PLAN → SIMULATE → IMPROVE**.

> **Disclaimer:** terrasim is a decision-support prototype. Scenario outputs are *estimated exposure layers*, not exact predictions of damage.

---

## Stack

- **Frontend**: Vite + React + TypeScript + MapLibre GL, styled with a pixel-art RPG UI (Pokemon FireRed-inspired chrome).
- **Backend**: Python + FastAPI (hosted locally, `http://127.0.0.1:8000`).
- **Simulation**: DEM-based flood fill, earthquake attenuation model, suitability/risk zones (NumPy + Shapely).
- **Data**: OpenStreetMap (buildings, roads, facilities, rivers) + Copernicus/SRTM elevation, preloaded offline in `data/bundles/`.

```
terrasim/
  backend/    FastAPI simulation API + pytest suite
  frontend/   Vite + React + TS SPA
  data/       bundled demo datasets (OSM + DEM)
  scripts/    data fetch/preprocess pipeline
```

---

## Local setup

### 1. Backend (FastAPI on localhost:8000)

```bash
cd backend
uv sync          # create venv + install deps
uv run uvicorn app.main:app --reload --port 8000
```

Health check: `http://127.0.0.1:8000/api/health`

### 2. Frontend (Vite dev server on localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 3. Data bundles

Bundled demo data ships in the repo (`data/bundles/`). To regenerate it from upstream sources:

```bash
python scripts/fetch_data.py --all
```

---

## API overview

| Method | Endpoint                          | Purpose                                   |
| ------ | --------------------------------- | ----------------------------------------- |
| GET    | `/api/health`                     | Health check                              |
| GET    | `/api/cities`                     | List available demo areas                 |
| GET    | `/api/cities/{id}/layers/{kind}`  | Buildings / roads / facilities / water GeoJSON |
| GET    | `/api/cities/{id}/rivers`         | River summaries for flood hypothesis selection |
| GET    | `/api/cities/{id}/dem`            | Elevation raster metadata + tiles         |
| POST   | `/api/simulate/flood`             | Flood scenario → extent + exposure        |
| POST   | `/api/simulate/earthquake`        | Earthquake scenario → zones + exposure    |
| POST   | `/api/suitability`                | New-City suitability (green/yellow/red)   |

A flood scenario floods either from a clicked source point (`source: {lng, lat}`) or
from a selected river (`river_id`, from `/api/cities/{id}/rivers`), with
`level_m` as the hypothesized rise in meters above the river's channel level.

Run the test suite:

```bash
cd backend && uv run pytest
```

---

## Attribution

- Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
- Elevation: Copernicus DEM (contains modified Copernicus Sentinel data) / SRTM

This project was built for the hackathon track *Climate Change, Resilience & Sustainability*. See `plans.md` for the full project context.