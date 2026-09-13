# Implementation log

Status ledger for terrasim. Most recent at the top. `plans.md` is the spec; this file records what physically exists and what was verified. Entries follow the development-log template (Goal / What we did / Problem / Solution / Result / Evidence) and only record what actually happened.

## 2026-09-13 — New-City: draw-a-channel flood origin + grid-stamp bulk placement

### Goal
Let Land Planning mode move fast in the demo: drop a whole pocket of facilities in one tap, and draw a hypothetical channel straight onto the land so a flood rise can be run along it — a sharper "what if the water ran through here?" move in the PLAN → SIMULATE → IMPROVE loop.

### What we did
- **Backend.** `app/schemas.py`: `FloodScenario` gains `river_path: list[GeoPoint] | None`; the origin validator is now *exactly one of* `source` / `river_id` / `river_path`. `app/main.py` `simulate_flood`: new `elif scenario.river_path` branch converts the path to `(lng, lat)` coords and calls `flood.run_river(...)` with no OSM tributary inherit for a drawn channel. `tests/test_engine.py` gains `test_flood_schema_accepts_each_single_origin`, `test_flood_schema_rejects_zero_or_two_origins`, `test_run_river_accepts_drawn_path`.
- **Frontend.** `store.ts`: `drawnRiver: {path} | null`, `drawingRiver`, `stampGrid` (+ `appendDrawPoint`/`undoDrawPoint`/`clearDrawn`/`setDrawing`/`setStampGrid`); picking an OSM river clears a drawn channel and vice-versa; `selectCity` clears both. `MapView.tsx`: new gold `ts-drawn-river` line layer in `LAYER_ORDER`; click handler gains a `drawingRiver` branch (append vertex, stay drawing) and a `stampGrid && pendingAsset` branch (drops an n×n grid at 60 m spacing with ids `plan-<ts>-<i>-<j>`); rubber-band preview follows the cursor; the flood-origin marker is hidden when a channel is the primary origin. `SidePanel.tsx` (Land Planning): "Pocket size" 2×2…5×5 picker; "Draw a channel along the land" toggle + Undo / Clear / point count; copy stays honest (*hypothetical channel*, "a scenario, not a forecast"). `useSimulate.ts`: flood origin precedence is now drawn channel → OSM river → point; `river_path` is sent when a channel exists.

### Problem
The demo needs to *plan a layout fast* and then stress-test it, but flood origins were limited to tapping the map or picking an OSM river, and placing facilities one at a time was too slow.

### Solution
Grid-stamp bulk placement plus a drawable hypothetical channel sent to the API as `river_path` and run through the same volume-conserving river engine as a real waterway.

### Result
`uv run pytest` 37 passed. `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass. Live smoke: `POST /api/simulate/flood` with `river_path` (3 pts across Kathmandu, 3 m, rise) → 200, `dry:false`, 6618 cells flooded, response echoes the drawn `river_path` in `scenario`.

### Evidence
implementation-log entry (this one); worktree change pending commit.

## 2026-09-12 — Fix: flat terrain/3D chunks at the map edges

### Goal
Fix the city view showing flat regions mixed with properly-elevated ones after real footprints shipped.

### What we did
- **Frontend (`MapView.tsx`).** Both `applyTerrain()` call sites now pass `city.hazard_bounds ?? city.bounds`. New `refreshTerrainRTT(map)` helper (`map.terrain.tileManager.releaseAllRTT()` + `map.triggerRepaint()`, both public in maplibre-gl 6.9.0) fired after the city-load `Promise.all` settles, on `moveend` of the initial `fitBounds`, after band/asset `setData`, and when toggling "3D terrain" on.

### Problem
Two frontend causes:
1. **DEM `bounds` mismatch** — the raster-dem source was constrained to `city.bounds` (the dense urban-core box) while the camera fits `city.hazard_bounds` (the wider valley theatre = the DEM grid). MapLibre never requests terrain tiles outside the source `bounds`, so the outer valley floor rendered with no mesh → flat terrain chunks around the viewport.
2. **Stale render-to-texture (RTT) terrain composites** — with terrain active, MapLibre renders each tile to a cached texture; fill-extrusion data that lands *after* that composite leaves some tiles flat until an interaction churns the cache (maplibre-gl#3001).

### Solution
Correct DEM source bounds on both terrain call sites, plus explicit RTT refresh after every dataset-changing moment.

### Result
Terrain tiles z11–13 across the Kathmandu hazard box confirmed non-flat and all served (backend was healthy; this was client-side). `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass.

### Evidence
`MapView.tsx` `refreshTerrainRTT`; maplibre-gl#3001; implementation-log entry.

## 2026-09-12 — Real building footprints replace centroid squares

### Goal
Render actual OSM building footprints instead of synthetic centroid squares, per plans.md §10 — real shapes as `fill-extrusion`, heights still estimated.

### What we did
- **Backend (`scripts/fetch_data.py`).** Buildings fetch switched from `out center 4000` (centroids) to `out geom 3000` on an independent 3×3 chunk grid (9 tiny chunks → mirrors return full rings; small chunks are the codebase's own remedy for `out geom` geometry degradation). Buildings `to_features` now emits Polygon geometry (`geom_attr="geometry"`, `keep_lines=False`); the dormant `filter_buildings()` is wired in to drop slivers (<40 m²) and degenerate 2-point ways before the 4500 largest-first cap.
- **Frontend.** `buildings3d.ts`: `buildBlockFeatures()` passes real Polygon rings straight through as the extrusion footprint (MultiPolygon → first polygon); the centroid-square generation stays only as a fallback for legacy point bundles. `estimateHeight()` untouched — heights remain *estimated* (OSM `height` → `building:levels` → type table, clamp 3–60 m). Hash colours, `applyBands()` tinting and the "~N m est." hover are unchanged. `SidePanel.tsx`: infrastructure toggle now reads "3D buildings".
- **Data.** kathmandu bundle rebuilt: `buildings.geojson` = 4500 Polygon features (mean ring 6.8 pts; 3 with `height`, 328 with `building:levels`). pokhara not rebuilt (deferred).

### Problem
`out center` fetches gave centroid **Point** buildings and `buildBlockFeatures()` drew placeholder squares around them — the 3D city was synthetic.

### Solution
Chunked `out geom` fetching to obtain genuine Polygon footprints, passed straight through as real extrusion bases.

### Result
`uv run pytest` 32 passed. `npx tsc --noEmit -p tsconfig.app.json` and `npm run build` pass. `/api/cities/kathmandu/layers/buildings` serves 4500 Polygons; the map renders real footprints under the FireRed raster treatment, and sim bands still tint exposed blocks by OSM id.

### Evidence
Commit `c9eb100` "feat: add all buildings to kathmandu bundle and implement flow routed flood"; implementation-log entry.

## 2026-09-12 — Valley-wide theatre + stylised 3D city blocks

### Goal
Make hazards trace the real Kathmandu valley basin (wider DEM grid, overlays clipped to the lowland) and make the city read as a blocky toy-city: stylised 3D blocks with estimated height, tinted by sim exposure.

### What we did
- **Backend.** `scripts/fetch_data.py`: `CITIES["kathmandu"]` gains `hazard_bounds` [85.15, 27.54, 85.47, 27.75] and `valley_cap_m` 1450.0; DEM fetched over `hazard_bounds` (grid 701×1068, was 534×668); OSM stays on the dense core bounds; `city.json` writes `hazard_bounds` + `valley_cap_m` + the widened grid. Buildings now fetched with `extra_tags=("height","building:levels")` and `add_id=True` → `buildings.geojson` carries real OSM ids (4500 features; 361 named, 338 with `building:levels`, 13 with explicit `height`). New `rim_geojson()` derives the valley-bowl outline (4-connected lowland below `cap_m` → union of row-run boxes → exterior ring, simplified); it returns `None` — and writes no file — when the ring hugs the DEM border (>35% of ring points on the grid edge) or touches grid corners. `app/engine/grid.py` gains `region_mask(cap_m)`; `earthquake.py` `quake_zones()`/`run()` and `flood.py` `_result()`/`run()`/`run_river()`/`flood_mask()`/`river_flood_mask()` accept an optional boolean region and mask all output shapes through it; `main.py` computes the region from `valley_cap_m` (`_valley_region`) and passes it for both hazards. `app/datasets.py` permits `"rim"` as a layer kind (404 when absent). `test_engine.py` grows two region-clip tests. 32 tests pass.
- **Data.** kathmandu bundle rebuilt: DEM 701×1068 over hazard bounds, `city.json` updated, no `rim.geojson` for kathmandu (correctly — open basin).
- **Frontend.** New `src/buildings3d.ts`: stylised blocks from centroid buildings — deterministic FNV-1a hash drives footprint size (10–22 m) and 0/45° twist; `estimateHeight()` prefers OSM `height`, then `building:levels`, then a type table (always *estimated*, clamped 3–60 m); FireRed palette silhouette colours; `applyBands()` tints blocks by quake band / flood via a `band` property; `buildAssetBlocks()` gives placed assets per-type footprints/heights/colours with selected-highlight. `MapView.tsx`: `ts-infra-buildings` is now `fill-extrusion` instead of the old circle layer; new `ts-valley-rim` dashed Teal line (only when the city ships rim data) and `ts-plan-3d` extrusion under the plan-asset icons; OSM raster gets a FireRed treatment (`raster-saturation -0.6`, `raster-hue-rotate 55`, opacity 0.55); map starts at `pitch: 55` with `antialias`; `fitBounds` uses `hazard_bounds ?? bounds`; hover tooltip over blocks reads "~N m est." + band tag. `store.ts`: `showBlocky3d`, `showValleyRim`, `rimAvailable` (+ setters). `SidePanel.tsx`: "3D blocks" and (when rim data exists) "Valley rim" toggles. `types.ts`: `CityInfo.hazard_bounds`/`valley_cap_m`, `LayerKind` += `"rim"`.

### Problem
The demo map read as a flat plan-view grid: hazards were rectangular boxes over a flat surface rather than the real valley shape, and the map was not aesthetically demo-ready.

### Solution
Widen the DEM theatre to the hazard bounds, clip hazard overlays to the valley bowl via a region mask, derive a valley rim only for genuine rings, and render a stylised 3D city with band-tintable blocks.

### Result
`uv run pytest` 32 passed; typecheck and build pass; oxlint clean except a pre-existing ExposurePanel warning. TestClient smoke on the rebuilt bundle: `/api/cities` returns `hazard_bounds` + `valley_cap_m` + 1068×701 grid; buildings layer carries ids; `layers/rim` → 404; Rudramati 3 m `rise` → `dry:false`, 4361 cells (~4.31 km², peak depth 7.4 m); 6.5 M / 10 km quake at city centre → zone shapes clipped to the basin (`area_km2` = high 67.77, medium_high 247.48, medium 43.92, low 0.0 — the low ring falls off-grid and the ridge corners are carved out).

### Evidence
implementation-log entry; `test_quake_region_clip_limits_zones_to_basin` / `test_flood_region_clip_trims_outer_extent`.

## 2026-09-12 — Water normalisation: fragmented OSM rivers merged into single features

### Goal
Make river-based flood seeding and tributary reads work: flood v2 reads tributary volume off the D8 basins of mapped waterlines, and OSM splits one physical river into many short, disjoint ways.

### What we did
- **Backend (`scripts/fetch_data.py`).** New `normalize_water()` stage runs after the OSM fetch and before `WATER_MAX`: union-find over features; phase 1 snaps endpoints within ~50 m (`_SNAP_DEG`) → one component; phase 2 merges same-stem, same-family components across unmapped gaps up to 20 km. Stem keys strip generic hydronyms (`river`, `khola`, `khahare`, `nala`, ...) and apply transliteration folds (`chh→ch`, `ph→f`, `kh→k`, `gh→g`, ...) so transliterated variants still match; Devanagari-only names stay exact-only ("(क)"/"(ख)" branch markers are real distinct watercourses). Canals are a separate family and never absorb `river`/`stream` ways; unnamed segments only join a group when they share a snap point (connect-only adoption). Canonical display name = longest-segment member. New `--normalize-water` CLI flag re-runs it on committed bundles with no network (`normalize_existing()`); the full `build_city` path calls it too.

### Problem
OSM splits one physical river into many short ways (Seti gaps measured up to 9 km) — as-is, one river counted as dozens of tiny tributaries and understated reach volume.

### Solution
Bundle-time union-find merge so one physical river becomes one coherent feature set.

### Result
Merged output shrunk the committed headroom — fidelity, not count: **kathmandu** `water.geojson` 206 → 114 features; **pokhara** `water.geojson` 300 → 210 features.

### Evidence
Commit `3666b09` "data: updated water data for kathmandu and pokhara"; `cd backend && uv run --group dev python ../scripts/fetch_data.py --normalize-water` on committed bundles re-emits the same counts (kathmandu 114, pokhara 210) and the same geometries — count-stable, not byte-identical (bundles are committed in their build order; revert path is `git checkout -- data/bundles/<id>/water.geojson`).

## 2026-09-12 - Flood engine v2: transient, volume-conserving, tributary-aware

### Goal
Replace the graded-surface flood ("raise the whole channel, pond-fill the basin"), which read as one flat blob no matter the river, with a researched, simpler-but-directional routing model and surface the resulting volume in the UI.

### What we did
- **Backend.** `app/engine/flood.py` rewritten as a volume-conserving transient model: D8 flow directions stay; a `rise` is translated into a conserved *volume* (reach length x assumed inundation width) rather than a global surface. The volume is released as a triangular hydrograph over simulated steps (`_SLOPE_STEPS_PER_CELL` assume ~0.8 m/s bank flow, clipped to 120–700 steps); cells flood when the wave front arrives, so upstream floods first and the extent reported is the peak over the run. Head-driven 8-neighbour flux step (`_flux_ca_step`) moves water between cells while preserving total volume; the grid edge is an infinite wall. The sim runs inside the D8 downstream/upstream closures plus a 12-cell margin, cutting kathmandu runtime from ~34 s to ~1.3 s. Tributaries: any mapped waterline whose D8 basin drains into the chosen river contributes volume (0.5x per tributary cell), lagged by its flow distance to the junction; new `FloodScenario.include_tributaries` (default true) gates it; `main.py` loads `water` features and reuses the engine's `mask` for exposure (no double simulation). New stats: `volume_m3`, `sim_steps`, `sim_hours`, `peak_discharge_m3s`, `tributaries`, `reach_cells`; `water_surface_m` is now the max peak water surface, and `flood-deep` depth bands are derived from the per-cell peak surface raster (was: graded mean). `test_engine.py` grew to cover catchment distances, flow accumulation, flux-step volume conservation, plan volume match, tributary contribution, directional downhill routing, and ridge overtopping. Total 30 tests pass.
- **Frontend.** `types.ts` FloodStats gains the new optional fields; `ExposurePanel.tsx` shows a routed-volume stat (M m³, est.) and an honest note citing the wave's modelled hours/peak discharge and any tributaries.
- **Docs.** `plans.md` section 8 rewritten to match the transient/volume model and its limitations.

### Problem
The old model ignored direction, volume and tributaries, so every river produced the same flat flood shape and the result was not trustworthy as a "what if" layer.

### Solution
A volume-conserving transient routing model with catchment-limited flux domain and tributary contributions.

### Result
kathmandu Seti: 2 m rise over ~9 h yields ~1.5 km² extent, ~0.93M m³ routed, 76 overlay features; run ≈1.3 s. 30 engine tests pass.

### Evidence
Commits `12de76b` "feat: flow-routed flood engine (D8 + graded surface + ponding)" and `fc09629` "flood: transient volume-conserving routing with tributaries"; `test_erosion_flux_step_conserves_volume`.

## 2026-09-12 — MVP cut-in: end-to-end demo runnable

### Goal
Make the PLAN → SIMULATE → IMPROVE demo fully runnable on two real cities — tolerant data pipeline, simulation backend, and a complete frontend — on committed offline data.

### What we did
- **Both cities fetch and bundle.** `scripts/fetch_data.py` reworked into a tolerant pipeline driven by Overpass chunking: `chunk_bboxes()` splits the city bbox; `merge_elements()` keeps the richest geometry per element id. `post_overpass()` is a single tolerant pass: mirrors tried once, 1.5 s backoff, `OVERPASS_TIMEOUT=40`, raises on empty when `min_elements>0`; callers skip failed chunks instead of retrying hot. Buildings fetched with `out center` per chunk → centroid Point features, capped at 4500. Roads through `to_features(..., keep_lines=True)`: always LineString; closed-Polygon wrapping is now correctly `[ring]` per GeoJSON (was flat ring → crashed shaped read in exposure). Facilities per-type with graceful skip. Bundles committed to `data/bundles/` (`data/fetch/` raw cache stays gitignored): kathmandu buildings 4500, roads 5525, facilities 500, DEM; pokhara buildings 4500, roads 4324, facilities 500, DEM.
- **Backend.** `ScenarioAsset` (kind/id/name/lng/lat) + optional `assets` on both scenario models; `_assets_for()` in `main.py` substitutes the planner's proposed layout for real OSM assets (per-`kind`). Flood response returns `dry: true` and flags no assets on dry ground; response includes `exposure.assets` + `exposure.affected`. Earthquake response unified into a merged `zones` FeatureCollection (each feature carries its band `class`) plus `bands` and `area_km2`; exposure via `exposure.assets` + `exposure.exposed`. Tests: `test_engine.py` (8, no network) + new `test_api.py` (5, bundle-backed). Total 13 pass.
- **Frontend (Vite + React + TS + MapLibre GL + zustand).** Full scaffold, no template leftovers: `types.ts`, `api.ts`, `store.ts`, `pixelIcons.ts` (canvas pixel sprites + atlas + previews), `MapView.tsx` (OSM raster, GeoJSON sources/layers, click-to-pick source/epicenter, place/move planned assets, infra toggles), `Topbar.tsx`, `SidePanel.tsx` (Scenario Lab / Land Planning + asset grid), `ExposurePanel.tsx` (result stats + per-asset verdicts; flood reads `affected`, quake reads `exposed`), `useSimulate.ts`, `App.tsx` (boot screen, map hint, facility chip, error toast), `index.css` (full FireRed palette from plans.md §39). Typecheck `tsc --noEmit` and `npm run build` both pass. First-paint flash fixed: `index.html` carries inline critical CSS (branded boot splash) so the page never shows a bare dark frame before React mounts; the map frame has a green→teal gradient until tiles arrive.

### Problem
The pieces existed as separate scaffolding but nothing was connected end-to-end; the buildings layer kept returning empty and the demo was not runnable.

### Solution
A single tolerant Overpass pass with committed offline bundles, planned-asset override in the API, unified hazard responses, and a full map UI wired to both scenario modes.

### Result
`GET /api/health` (2 cities); flood kathmandu (80.6 km² extent, 2093 overlay polys, 285/500 facilities estimated flooded); earthquake kathmandu (7534 zone polys, 338 facilities in high band); pokhara suitability (2678/5480/2822 green/yellow/red); planned-assets quake + flood on pokhara evaluated the proposed hospital/school per-asset verdicts. Known limits (all "estimated", per plans.md §30): buildings are point centroids, not footprints — exposure is per-centroid; flood/quake results are relative exposure layers on the DEM, not engineering collapse predictions; bundles rely on Overpass snapshot quality — a throttling mirror can silently reduce a layer (callers skip failed chunks).

### Evidence
Commit `5f6a91e` "feat: MVP - simulate and plan modes, offline data bundles, full frontend"; implementation-log entry.

## 2026-09-12 — before: feature scaffolding

### Goal
Lay the foundations for the project: repo, backend venv + simulation engine, data pipeline first pass, frontend template.

### What we did
- Repo initialisation; backend venv + engine modules; data pipeline first pass; frontend template.

### Problem
Nothing existed yet — this is the foundations milestone.

### Solution
Created the repo skeleton and wired the initial module layout.

### Result
Repo buildable and ready for the MVP cut-in.

### Evidence
`git log` — e.g. commit `d27b4c8` "feat: scaffold project structure".