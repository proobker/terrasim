# AGENTS.md

Agent-facing map for **terrasim** — Building Resilient Areas for Climate & Emergencies. Two modes: Existing City (simulate & assess a real area) and New City (plan & validate a layout). The core loop is **PLAN → SIMULATE → IMPROVE** — the money moment of the demo is communicating "we used the simulation to improve the city."

## Where the context lives

- `plans.md` — the master spec. Read it up front; re-read visual identity (§38–41), scientific-honesty rules (§30), judge objections (§31), terminology-to-avoid (§10), and the demo script (§44–47) before UI/claims work.
- `CLAUDE.md` — working notes and aesthetic rules (polished handcrafted pixel-art RPG over a real map, not a generic dashboard).
- `README.md` — user-facing setup, API table, attribution. Do not duplicate it here.

## Repo map

```
backend/
  app/main.py        FastAPI routes; _assets_for() lets a planner's proposed layout
                     override the real OSM assets in a sim.
  app/schemas.py     Pydantic request/response models (FloodScenario, EarthquakeScenario,
                     ScenarioAsset, ...).
  app/datasets.py    Bundle loader. DATA_ROOT default = <repo>/data/bundles.
  app/engine/        Pure simulation, no I/O: grid (DEM), flood, earthquake, suitability,
                     exposure. Response unification lives in main.py, physics here.
  tests/             test_engine.py (fast, no network) + test_api.py (needs bundles present).
frontend/
  src/store.ts       zustand store: city/mode/hazard/params/source/result/placedAssets/...
  src/MapView.tsx    MapLibre GL map + layers; click-to-set source/epicenter; place-move assets.
  src/SidePanel.tsx  Scenario Lab (existing) / Land Planning (new) side panel.
  src/ExposurePanel.tsx  Result stats + per-asset verdicts (flood reads `affected`,
                     quake reads `exposed`).
  src/useSimulate.ts runHazard/planAssets/useSuitability API hooks.
  src/buildings3d.ts synthetic 3D blocks (estimated heights, band tinting) for the toy city.
  src/pixelIcons.ts  canvas-generated pixel sprites; atlasDefinitions() + previewCanvas().
  src/index.css      full pixel/FireRed design system (palette in plans.md §39).
scripts/fetch_data.py  Overpass (OSM) + Terrarium (DEM) fetch pipeline → data/bundles.
data/bundles/<city>/ city.json geometry (+ hazard_bounds/valley_cap_m), dem.meta.json + dem.npz,
                     buildings/roads/facilities.geojson, rim.geojson (only when a genuine
                     valley ring exists for the city)
```

## Commands (definition of done)

- Backend tests: `cd backend && uv run pytest` — must pass before shipping.
- Frontend typecheck: `cd frontend && npx tsc --noEmit -p tsconfig.app.json`
- Frontend prod build: `cd frontend && npm run build` (runs tsc -b + vite build)
- Run servers: backend `cd backend && uv run uvicorn app.main:app --port 8000`; frontend `cd frontend && npm run dev` (localhost:5173). API base env `VITE_API_BASE`, default `127.0.0.1:8000`.
- Rebuild a data bundle: `cd backend && uv run --group dev python ../scripts/fetch_data.py --city <id>` (`--all` for every city). Pillow lives in the `dev` dependency group.

## Data-pipeline gotchas (unwritten in README)

- Overpass bbox order is **lat_min, lng_min, lat_max, lng_max** (S,W,N,E) — reversed boxes silently return nothing.
- Mirrors throttle bursts; `overpass-api.de` is unreachable from this machine. Fetch strategy is a **single tolerant pass**: mirrors tried once (shuffled), 1.5s backoff, `OVERPASS_TIMEOUT=40`; a chunk that fails is skipped by its caller rather than retried hot. Keep it tolerant or builds hang for minutes.
- Buildings are fetched with `out center` — centroid **Point** features per chunk. `out geom` under load returns degenerate 2-point ways that are filtered out → "buildings: 0".
- Roads use `to_features(..., keep_lines=True)`: always LineString, never closed as Polygon. Polygons are wrapped `[ring]` per GeoJSON. 3-point extras are dropped as ambiguous. Non-Zero passes finalize.
- Buildings now carry OSM `id` (+ `height`, `building:levels` when tagged) so the 3D blocks can be tinted per exposed asset.
- `rim.geojson` is written only when the lowland below `valley_cap_m` forms a genuine ring. Open basins (the DEM box connecting to an adjacent plain, e.g. Kathmandu's NW edge) are rejected by the edge-hugging guard — no file, and the frontend hides the "Valley rim" toggle rather than dream up a fake line.
- `city.json` may carry `hazard_bounds` (wider DEM/sim theatre) + `valley_cap_m`; the frontend fits the map to `hazard_bounds ?? bounds` and the engine clips overlays to `elev < valley_cap_m`.

## Conventions (load-bearing)

- **Honesty framing**: every UI string and API field says *estimated / hypothetical / scenario-based / relative / candidate / exposure* — never *predicts / guaranteed / will collapse*. Flood on dry ground reports `dry: true` and the UI says nothing floods. This is not decoration; plans.md §30 and §10.
- **Blocks are illustration, not survey**: 3D building heights/footprints are stylised estimates (OSM tags when present, type defaults otherwise); hover clearly reads "~N m est.". Band colours on blocks mark *scenario exposure*, never damage.
- **Fallbacks feel wrong**: precommitted demo data means the demo works offline-ish; a failed sim or empty overlay is a bug, not an acceptable output.
- **Vibe-check before done**: open the running app and scrutinize as a player. Stock map look, default dev styling, or inconsistent spacing fails the bar. FireRed chrome is a requirement, not a garnish.

## Definition of done (for any change)

1. `uv run pytest` passes (backend).
2. Frontend typecheck and `npm run build` pass.
3. The affected demo flow still walks per plans.md §44 (existing + new city).
4. Honesty framing intact in everything new you wrote.
5. Aesthetic vibe-pass on the running app.