# Implementation log

Status ledger for terrasim. Most recent at the top. `plans.md` is the spec; this file records what physically exists and what was verified.

## 2026-09-12 - Flood engine v2: transient, volume-conserving, tributary-aware

**Why**: the graded-surface flood ("raise the whole channel, pond-fill the basin") read as one flat blob no matter the river. Replaced with a researched, simpler-but-directional routing model and surfaced the resulting volume in the UI.

**Backend.**
- `app/engine/flood.py` rewritten as a volume-conserving transient model:
  - D8 flow directions stay; a `rise` is now translated into a conserved *volume* (reach length x assumed inundation width) rather than a global surface.
  - The volume is released as a triangular hydrograph over simulated steps (`_SLOPE_STEPS_PER_CELL` assume ~0.8 m/s bank flow, clipped to 120-700 steps); cells flood when the wave front arrives, so upstream floods first and the extent reported is the peak over the run.
  - Head-driven 8-neighbour flux step (`_flux_ca_step`) moves water between cells while preserving total volume; the grid edge is an infinite wall (water never leaks off). The sim runs inside the D8 downstream/upstream closures plus a 12-cell margin, which cut kathmandu runtime from ~34s to ~1.3s.
  - Tributaries: any mapped waterline whose D8 basin drains into the chosen river contributes volume (0.5x per tributary cell), lagged by its flow distance to the junction. New `FloodScenario.include_tributaries` (default true) gates it; `main.py` loads `water` features and reuses the engine's `mask` for exposure (no double simulation).
  - New stats: `volume_m3`, `sim_steps`, `sim_hours`, `peak_discharge_m3s`, `tributaries`, `reach_cells`; `water_surface_m` is now the max peak water surface, and `flood-deep` depth bands are derived from the per-cell peak surface raster (was: graded mean).
  - `test_engine.py` grew to cover catchment distances, flow accumulation, flux-step volume conservation, plan volume match, tributary contribution, directional downhill routing, and ridge overtopping. Total 30 tests pass.

**Frontend.**
- `types.ts` FloodStats gains the new optional fields; `ExposurePanel.tsx` shows a routed-volume stat (M m3, est.) and an honest note citing the wave's modelled hours/peak discharge and any tributaries.

**Docs.** `plans.md` section 8 rewritten to match the transient/volume model and its limitations.

**Verified live.** kathmandu Seti: 2 m rise over ~9 h yields ~1.5 km2 extent, ~0.93M m3 routed, 76 overlay features; runoff ~1.3s. Flood copy, labels and arrows already flow-routed from the earlier UI pass.

## 2026-09-12 — MVP cut-in: end-to-end demo runnable

**Both cities fetch and bundle.**
- `scripts/fetch_data.py` reworked into a tolerant pipeline driven by Overpass chunking:
  - `chunk_bboxes()` splits the city bbox; `merge_elements()` keeps the richest geometry per element id.
  - `post_overpass()` is a single tolerant pass: mirrors tried once (shuffled), 1.5s backoff, `OVERPASS_TIMEOUT=40`, raises on empty when `min_elements>0`; callers skip failed chunks instead of retrying hot.
  - Buildings are fetched with `out center` per chunk → centroid **Point** features, capped at 4500. Rationale: `out geom` under mirror load returns degenerate 2-point ways that got filtered → "buildings: 0". A stale duplicate `fetch_osm` (full-bbox `out geom`) was shadowing the chunked one — removed; that was the root cause of the persistent empty buildings layer.
  - Roads through `to_features(..., keep_lines=True)`: always LineString; closed-Polygon wrapping is now correctly `[ring]` per GeoJSON (was flat ring → crashed shaped read in exposure).
  - Facilities per-type with graceful skip.
- Bundles committed to `data/bundles/` so the demo is runnable offline-ish (`data/fetch/` raw cache stays gitignored):
  - **kathmandu**: buildings 4500, roads 5525, facilities 500, DEM.
  - **pokhara**: buildings 4500, roads 4324, facilities 500, DEM.

**Backend.**
- `ScenarioAsset` (kind/id/name/lng/lat) + optional `assets` on both scenario models; `_assets_for()` in `main.py` substitutes the planner's proposed layout for real OSM assets (per-`kind`). Both hazards honor it.
- Flood response now returns `dry: true` and the engine flags no assets on dry ground; response includes `exposure.assets` + `exposure.affected`.
- Earthquake split response unified into a merged `zones` FeatureCollection (each feature carries its band `class`) plus `bands` and `area_km2`; exposure via `exposure.assets` + `exposure.exposed`.
- Tests: `test_engine.py` (8, no network) + new `test_api.py` (5, bundle-backed). Total 13 pass.

**Frontend (Vite + React + TS + MapLibre GL + zustand).**
- Full scaffold, no template leftovers: `types.ts`, `api.ts`, `store.ts`, `pixelIcons.ts` (canvas pixel sprites + atlas + previews), `MapView.tsx` (OSM raster, GeoJSON sources/layers, click-to-pick source/epicenter, place/move planned assets, infra toggles), `Topbar.tsx`, `SidePanel.tsx` (Scenario Lab / Land Planning + asset grid), `ExposurePanel.tsx` (result stats + per-asset verdicts; flood reads `affected`, quake reads `exposed`), `useSimulate.ts`, `App.tsx` (boot screen, map hint, facility chip, error toast), `index.css` (full FireRed palette from plans.md §39).
- Typecheck `tsc --noEmit` and `npm run build` both pass; dev server serves all modules.
- First-paint flash fixed: `index.html` carries inline critical CSS (branded boot splash) so the page never shows a bare dark frame before React mounts; the map frame has a green→teal gradient until tiles arrive.

**Verified live.** `GET /api/health` (2 cities); flood kathmandu (80.6 km² extent, 2093 overlay polys, 285/500 facilities estimated flooded); earthquake kathmandu (7534 zone polys, 338 facilities in high band); pokhara suitability (2678/5480/2822 green/yellow/red); planned-assets quake + flood on pokhara evaluated the proposed hospital/school per-asset verdicts.

**Known limits (all "estimated", per plans.md §30):**
- Buildings are point centroids, not footprints — exposure is per-centroid.
- Flood/quake results are relative exposure layers on the DEM, not engineering collapse predictions.
- Bundles rely on Overpass snapshot quality; a mirror that throttles can silently reduce a layer (callers skip failed chunks).

## 2026-09-12 — before: feature scaffolding

- Repo, backend venv + engine, data pipeline first pass, frontend template. See `git log`.