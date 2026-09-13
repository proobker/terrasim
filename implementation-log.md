# Implementation log

Status ledger for terrasim. Most recent at the top. `plans.md` is the spec; this file records what physically exists and what was verified.

## 2026-09-13 — New-City: draw-a-channel flood origin + grid-stamp bulk placement

**Why**: the demo needs to *plan a layout fast* and then stress it. Land Planning mode now lets you drop a whole pocket of buildings in one tap, and for flood you can draw a hypothetical channel straight onto the land and run the rise along it — the PLAN → SIMULATE → IMPROVE loop gets a sharper "what if the water ran through here?" move.

**Backend.**
- `app/schemas.py`: `FloodScenario` gains `river_path: list[GeoPoint] | None`; the origin validator is now *exactly one of* `source` / `river_id` / `river_path`.
- `app/main.py` `simulate_flood`: new `elif scenario.river_path` branch converts the path to `(lng, lat)` coords and calls `flood.run_river(grid, coords, level_m, mode, None, region=...)` — no OSM tributary inherit for a drawn channel.
- `tests/test_engine.py`: `test_flood_schema_accepts_each_single_origin`, `test_flood_schema_rejects_zero_or_two_origins`, `test_run_river_accepts_drawn_path`.

**Frontend.**
- `store.ts`: `drawnRiver: {path} | null`, `drawingRiver`, `stampGrid` (+ `appendDrawPoint`/`undoDrawPoint`/`clearDrawn`/`setDrawing`/`setStampGrid`). Picking an OSM river clears a drawn channel and vice-versa (single-origin invariant). `selectCity` clears both.
- `MapView.tsx`: new `ts-drawn-river` line layer (gold `#E6C66A`, drawn above the cyan real-river highlight, added to `LAYER_ORDER`); click handler gains a `drawingRiver` branch (append vertex, stay drawing) and a `stampGrid && pendingAsset` branch (drops an n×n grid of the active type at 60 m spacing, unique ids `plan-<ts>-<i>-<j>`, then clears the grid but keeps the asset tool hot). Rubber-band preview segment follows the cursor while drawing. Flood-origin marker is hidden when a channel (drawn or OSM) is the primary origin.
- `SidePanel.tsx` (Land Planning): "Pocket size" 2×2…5×5 picker under the asset grid; "Draw a channel along the land" toggle + Undo / Clear / point count under the flood origin picker. Copy stays honest: *hypothetical channel*, *"the flood rises along it as a scenario, not a forecast"*.
- `useSimulate.ts`: flood origin precedence is now **drawn channel → OSM river → point**; `river_path` is sent when a channel exists.

**Verified live.** `uv run pytest` 37 passed. `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass. Live smoke: `POST /api/simulate/flood` with `river_path` (3 pts across Kathmandu, level 3 m, rise) → 200, `dry:false`, 6618 cells flooded, response carries the drawn `river_path` back in `scenario`.

## 2026-09-12 — Fix: flat terrain/3D chunks at the map edges

**Why**: after real footprints shipped, the city view showed flat regions mixed with properly-elevated ones. Two frontend causes, both in `MapView.tsx`:

1. **DEM `bounds` mismatch** — the raster-dem source was constrained to `city.bounds` (the dense urban-core box) while the camera fits `city.hazard_bounds` (the wider valley theatre = the DEM grid). MapLibre never requests terrain tiles outside the source `bounds`, so the outer valley floor rendered with no mesh → flat terrain chunks around the viewport. Fix: both `applyTerrain()` call sites pass `city.hazard_bounds ?? city.bounds`.
2. **Stale render-to-texture (RTT) terrain composites** — with terrain active, MapLibre renders each tile to a cached texture; fill-extrusion data that lands *after* that composite (buildings fetch, band tints, moved planning assets) leaves some tiles flat until an interaction churns the cache (maplibre-gl#3001). Fix: new `refreshTerrainRTT(map)` helper (`map.terrain.tileManager.releaseAllRTT()` + `map.triggerRepaint()`, both public in 6.9.0) fired after the city-load `Promise.all` settles, on `moveend` of the initial `fitBounds`, after band/asset `setData`, and when toggling `3D terrain` on.

**Verified live.** `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass. Terrain tiles z11–13 across the Kathmandu hazard box confirmed non-flat and all served (backend was healthy; this was client-side).

## 2026-09-12 — Real building footprints replace centroid squares

**Why**: the 3D city was synthetic — `out center` fetches gave centroid **Point** buildings and `buildBlockFeatures()` drew placeholder squares around them. plans.md §10 asks for actual OSM footprints; the map now renders real building shapes as `fill-extrusion`, heights still estimated.

**Backend (`scripts/fetch_data.py`).**
- Buildings fetch switched from `out center 4000` (centroids) to `out geom 3000` on an independent 3×3 chunk grid (9 tiny chunks → mirrors return full rings; small chunks are the codebase's own remedy for `out geom` geometry degradation).
- Buildings `to_features` now emits Polygon geometry (`geom_attr="geometry"`, `keep_lines=False`); the dormant `filter_buildings()` is wired in to drop slivers (<40 m²) and degenerate 2-point ways before the 4500 largest-first cap.

**Frontend.**
- `buildings3d.ts`: `buildBlockFeatures()` passes real Polygon rings straight through as the extrusion footprint (MultiPolygon → first polygon); the centroid-square generation stays only as a fallback for legacy point bundles. `estimateHeight()` untouched — heights remain *estimated* (OSM `height` → `building:levels` → type table, clamp 3–60 m). Hash colours, `applyBands()` tinting and the "~N m est." hover are unchanged.
- `SidePanel.tsx`: infrastructure toggle now reads "3D buildings".

**Data.** kathmandu bundle rebuilt: `buildings.geojson` = 4500 Polygon features (mean ring 6.8 pts; 3 with `height`, 328 with `building:levels`). pokhara not rebuilt (deferred).

**Verified live.** `uv run pytest` 32 passed. `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass. `/api/cities/kathmandu/layers/buildings` serves 4500 Polygons; the map renders real footprints under the FireRed raster treatment, and sim bands still tint exposed blocks by OSM id.

## 2026-09-12 — Valley-wide theatre + stylised 3D city blocks

**Why**: the demo map read as a flat plan-view grid. Now hazards trace the real Kathmandu valley basin (wider DEM grid, overlays clipped to the lowland) and the city reads as a blocky toy-city: every building is a stylised 3D block with estimated height, and a sim run tints exposed blocks in band colours.

**Backend.**
- `scripts/fetch_data.py`:
  - `CITIES["kathmandu"]` gains `hazard_bounds` [85.15, 27.54, 85.47, 27.75] and `valley_cap_m` 1450.0. DEM is fetched over `hazard_bounds` (grid 701×1068, was 534×668); OSM stays on the dense core bounds. `city.json` writes `hazard_bounds` + `valley_cap_m` + the widened grid.
  - Buildings are now fetched with `extra_tags=("height","building:levels")` and `add_id=True` → `buildings.geojson` carries real OSM ids (4500 features; 361 named, 338 with `building:levels`, 13 with explicit `height`).
  - New `rim_geojson()` derives the valley-bowl outline (4-connected lowland below `cap_m` → union of row-run boxes → exterior ring, simplified). It returns `None` — and writes no file — when the ring hugs the DEM border (>35% of ring points on the grid edge) or touches grid corners: an open basin (Kathmandu's NW plain open to the Terai) has no genuine valley ring, and drawing the DEM box as a "valley rim" would be both stock-looking and dishonest.
- `app/engine/grid.py` gains `region_mask(cap_m)`; `earthquake.py` `quake_zones()`/`run()` and `flood.py` `_result()`/`run()`/`run_river()`/`flood_mask()`/`river_flood_mask()` accept an optional boolean region and mask all output shapes through it. `main.py` computes the region from `valley_cap_m` (`_valley_region`) and passes it for both hazards.
- `app/datasets.py` permits `"rim"` as a layer kind (404 when absent).
- `test_engine.py` grows two region-clip tests (quake zones strictly inside basin; flood trims outer extent). 32 tests pass.

**Data.** kathmandu bundle rebuilt: DEM 701×1068 over hazard bounds, `city.json` updated, no `rim.geojson` for kathmandu (correctly — open basin).

**Frontend.**
- New `src/buildings3d.ts`: builds stylised blocks from centroid buildings — deterministic FNV-1a hash drives footprint size (10–22 m) and 0/45° twist; `estimateHeight()` prefers OSM `height`, then `building:levels`, then a type table (always *estimated*, clamped 3–60 m); FireRed palette silhouette colours; `applyBands()` tints blocks by quake band / flood via a `band` property; `buildAssetBlocks()` gives placed assets per-type footprints/heights/colours with selected-highlight.
- `MapView.tsx`: `ts-infra-buildings` is now `fill-extrusion` (block height from `["get","height"]`, band-tinted where exposed, vertical gradient, clamped base 0) instead of the old circle layer; new `ts-valley-rim` dashed Teal line (only when the city ships rim data) and `ts-plan-3d` extrusion under the plan-asset icons; OSM raster first gets a FireRed treatment (`raster-saturation -0.6`, `raster-hue-rotate 55`, opacity 0.55); map starts at `pitch: 55` with `antialias`, plus a themed NavigationControl; `fitBounds` uses `hazard_bounds ?? bounds`; hover tooltip over blocks reads "~N m est." + band tag.
- `store.ts`: `showBlocky3d`, `showValleyRim`, `rimAvailable` (+ setters). `SidePanel.tsx`: "3D blocks" and (when rim data exists) "Valley rim" toggles. `index.css`: `.map-shell`, `.building-tip`, maplibre control/attribution theming. `types.ts`: `CityInfo.hazard_bounds`/`valley_cap_m`, `LayerKind` += `"rim"`.

**Docs.** This entry; AGENTS.md repo map + gotchas; plans.md §44 existing-city beat.

**Verified live.** `uv run pytest` 32 passed. `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass; oxlint clean except a pre-existing ExposurePanel warning. TestClient smoke on the rebuilt bundle: `/api/cities` returns `hazard_bounds` + `valley_cap_m` + 1068×701 grid; buildings layer carries ids; `layers/rim` → 404; Rudramati 3 m `rise` → `dry:false`, 4361 cells (~4.31 km², peak depth 7.4 m); 6.5 M / 10 km quake at city centre → zone shapes clipped to the basin (`area_km2` = high 67.77, medium_high 247.48, medium 43.92, low 0.0 — the low ring falls off-grid and the ridge corners are carved out).

## 2026-09-12 — Water normalisation: fragmented OSM rivers merged into single features

**Why**: flood v2 reads tributary volume off the D8 basins of mapped waterlines. OSM splits one physical river into many short, disjoint ways (Seti gaps measured up to 9 km) — as-is, one river counted as dozens of tiny tributaries and understated reach volume.

**Backend (`scripts/fetch_data.py`).**
- New `normalize_water()` stage runs after the OSM fetch and before `WATER_MAX`:
  - Union-find over features; phase 1 snaps endpoints within ~50 m (`_SNAP_DEG`) → one component; phase 2 merges same-stem, same-family components across unmapped gaps up to 20 km (city extracts are ~20 km wide, so "same named river, anywhere in this extract").
  - Stem keys strip generic hydronyms (`river`, `khola`, `khahare`, `nala`, ...) and apply transliteration folds (`chh→ch`, `ph→f`, `kh→k`, `gh→g`, ...) so transliterated variants still match. Devanagari-only names stay exact-only — "(क)"/"(ख)" branch markers are real distinct watercourses.
  - Canals are a separate family and never absorb `river`/`stream` ways; unnamed segments only join a group when they share a snap point (connect-only adoption). Canonical display name = longest-segment member.
  - New `--normalize-water` CLI flag re-runs it on committed bundles with no network (`normalize_existing()`); existing full `build_city` path calls it too.
- Merged output actually shrunk the committed `WATER_MAX` headroom, but the point is fidelity, not count:
  - **kathmandu** `water.geojson`: 206 → 114 features.
  - **pokhara** `water.geojson`: 300 → 210 features.

**Docs.** None beyond this entry — plans.md §8 already matches the flood v2 model this underpins.

**Verified live.** `cd backend && uv run --group dev python ../scripts/fetch_data.py --normalize-water` on the committed bundles re-emits the same counts (kathmandu 114, pokhara 210) and the same feature geometries — but in a different order, so it is count-stable, not byte-identical. Re-run only when you intend to rewrite a bundle; bundles are committed in their build order and the revert path is `git checkout -- data/bundles/<id>/water.geojson`.

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