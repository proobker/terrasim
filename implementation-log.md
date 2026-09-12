# Implementation log

Status ledger for terrasim. Most recent at the top. `plans.md` is the spec; this file records what physically exists and what was verified.

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