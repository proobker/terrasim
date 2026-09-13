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

- **Frontend**: Vite + React 19 + TypeScript + MapLibre GL, styled with a pixel-art RPG UI (Pokemon FireRed-inspired chrome).
- **Backend**: Python 3.14 + FastAPI (hosted locally, `http://127.0.0.1:8000`).
- **Simulation**: flow-routed volume-conserving flood, earthquake attenuation, suitability/risk zones (NumPy + Shapely).
- **Data**: OpenStreetMap (real building footprints, roads, facilities, rivers) + Copernicus/SRTM elevation, preloaded offline in `data/bundles/`.
- **Map**: real OSM building footprints as 3D extrusions with estimated heights; 3D terrain from Terrarium-encoded DEM tiles; no database.

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
cd backend
uv run --group dev python ../scripts/fetch_data.py --all
```

(`--pbf-buildings` rebuilds only the offline PBF building layer for cities
that use one; `--normalize-water` re-runs water snapping offline.)

---

## API overview

| Method | Endpoint                               | Purpose                                   |
| ------ | -------------------------------------- | ----------------------------------------- |
| GET    | `/api/health`                          | Health check                              |
| GET    | `/api/cities`                          | List available demo areas                 |
| GET    | `/api/cities/{id}`                     | City metadata (bounds, hazard_bounds, valley_cap_m, DEM grid, attribution) |
| GET    | `/api/cities/{id}/layers/{kind}`       | Buildings / roads / facilities / water / rim GeoJSON |
| GET    | `/api/cities/{id}/rivers`              | River summaries for flood hypothesis selection |
| GET    | `/api/cities/{id}/terrain/{z}/{x}/{y}.png` | Terrarium elevation tiles (3D terrain) |
| POST   | `/api/simulate/flood`                  | Flood scenario → extent + exposure        |
| POST   | `/api/simulate/earthquake`             | Earthquake scenario → zones + exposure    |
| POST   | `/api/cities/{id}/suitability`         | New-City suitability (green/yellow/red)   |

A flood scenario accepts exactly one origin per request: a point source
(`source: {lng, lat}`), a selected river (`river_id`, from
`/api/cities/{id}/rivers`), or a planner-drawn channel (`river_path`, from
New City mode). `level_m` is the hypothesized rise in metres above the
river's channel level; `mode` is `rise` (default) or `absolute`;
`include_tributaries` (default true) lets mapped rivers drain into the
chosen one. Optional `assets` replace real OSM assets with a planner's
proposed layout.

Run the test suite:

```bash
cd backend && uv run pytest
```

Frontend typecheck:

```bash
cd frontend && npx tsc --noEmit -p tsconfig.app.json
```

---

## Attribution

- Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)
- Elevation: Copernicus DEM (contains modified Copernicus Sentinel data) / SRTM

This project was built for the hackathon track *Climate Change, Resilience & Sustainability*. See `plans.md` for the full project context.