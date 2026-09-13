### Development log template

``` text
## [DATE/TIME] — [MILESTONE]

### Goal
...

### What we did
...

### Problem
...

### Solution
...

### Result
...

### Evidence
[Screenshot / Git commit / issue]
```

Do not invent timestamps or events. Fill this with what actually
happened.

------------------------------------------------------------------------

# 22. Development Log

Actual development milestones for terrasim, in the template's format and in
order. Dates follow `implementation-log.md`; no timestamps below the day are
invented. All numbers are from verified live runs or the passing test suite.

## 2026-09-12 — MVP cut-in: end-to-end demo runnable

### Goal
A complete PLAN → SIMULATE → IMPROVE demo on two real cities: a data pipeline
that fetches and bundles real map data, a simulation backend, and a frontend
that runs both modes.

### What we did
- Reworked `scripts/fetch_data.py` into a tolerant Overpass pipeline:
  chunked bbox queries, mirrors tried once in shuffled order with 1.5 s
  backoff, failed chunks skipped instead of retried hot.
- Buildings fetched as centroid Points per chunk, capped at 4500; roads forced
  to LineString; facilities fetched per amenity type with graceful skip.
- Committed offline bundles so the demo is runnable offline-ish: **kathmandu**
  (4500 buildings, 5525 roads, 500 facilities, DEM) and **pokhara** (4500,
  4324, 500, DEM).
- Backend: `ScenarioAsset` + optional `assets` on both scenario models so a
  planner's proposed layout substitutes for real OSM assets; flood returns
  `dry: true` + `exposure.assets/affected`; quake returns merged `zones` +
  `bands` + `area_km2`.
- Frontend: full scaffold (Vite + React + TS + MapLibre GL + zustand),
  pixel-art sprite atlas, Scenario Lab / Land Planning panels, exposure panel.
- Tests: 8 engine tests (no network) + 5 API tests (bundle-backed) = 13.

### Problem
The pieces existed as separate scaffolding but nothing was connected end to
end, and the buildings layer came back empty (see Challenges).

### Solution
Tolerant chunked fetch, committed offline bundles, planned-asset override in
the API, and a full map UI wired to both scenario modes.

### Result
Both modes demo on committed data without live network: flood kathmandu 80.6
km² extent (2093 overlay polys, 285/500 facilities estimated flooded); quake
kathmandu 7534 zone polys (338 facilities in the high band); pokhara
suitability 2678/5480/2822 green/yellow/red.

### Evidence
Commit `5f6a91e` "feat: MVP - simulate and plan modes, offline data bundles,
full frontend"; implementation-log.md "MVP cut-in" entry.

## 2026-09-12 — Flood engine v2: transient, volume-conserving, tributary-aware

### Goal
Replace the graded-surface flood ("raise the whole channel, pond-fill the
basin"), which painted one flat blob no matter which river was chosen, with a
researched, direction-aware routing model and surface the resulting volume in
the UI.

### What we did
- D8 flow directions stay; a `rise` is translated into a *conserved volume*
  (reach length x assumed inundation width) instead of a global surface.
- Volume released as a triangular hydrograph over simulated steps (upstream
  floods first; extent reported = peak over the run).
- Head-driven 8-neighbour flux step moves water between cells while conserving
  total volume; the grid edge is an infinite wall.
- Tributaries: any mapped waterline draining into the chosen river contributes
  volume (0.5x per tributary cell), lagged by flow distance to the junction.
- New stats: `volume_m3`, `sim_steps`, `sim_hours`, `peak_discharge_m3s`,
  `tributaries`, `reach_cells`; new `include_tributaries` scenario flag.

### Problem
The old model ignored direction and volume, so every river flooded the same
flat shape, and the simulation was slow.

### Solution
Volume-conserving transient routing, plus a flux domain culled to the river's
D8 downstream/upstream closures + 12-cell margin (kathmandu runtime fell from
~34 s to ~1.3 s).

### Result
Kathmandu Seti, 2 m rise over ~9 h: ~1.5 km² extent, ~0.93M m³ routed, 76
overlay features. Test suite grown to 30 engine tests; all pass.

### Evidence
Commits `12de76b` (flow-routed engine) and `fc09629` (transient + tributaries);
`test_erosion_flux_step_conserves_volume`, `test_flow_accumulation_weighted_upstream`.

## 2026-09-12 — Water normalisation: fragmented OSM rivers merged

### Goal
Make river-based flood seeding work: OSM splits one physical river into
hundreds of short, disjoint, inconsistently-spelled ways.

### What we did
- `normalize_water()`: union-find over features — snap-connect endpoints within
  ~50 m; merge same-stem, same-family components across unmapped gaps up to
  20 km.
- Stem keys strip generic hydronyms and apply transliteration folds
  (`chh→ch`, `ph→f`, `kh→k`, `gh→g`); Devanagari-only names stay exact-only.
- Canals are a separate family; unnamed segments only join via a snap point.
- New `--normalize-water` CLI flag re-runs it on committed bundles offline.

### Problem
The Seti's fragments (gaps measured up to 9 km) counted as dozens of tiny
tributaries and understated reach volume.

### Solution
Bundle a union-find merge stage so one physical river becomes one coherent
`MultiLineString`.

### Result
kathmandu `water.geojson` 206 → 114 features; pokhara 300 → 210.

### Evidence
Commit `3666b09`; `--normalize-water` re-runs reproduce the same counts (114 /
210) on committed bundles.

## 2026-09-12 — Valley-wide theatre + stylised 3D city blocks

### Goal
The demo map read as a flat plan-view grid. The hazards should trace the real
Kathmandu valley basin and the city should read as a blocky toy-city.

### What we did
- `kathmandu` gains `hazard_bounds` [85.15, 27.54, 85.47, 27.75] and
  `valley_cap_m` 1450; DEM regridded to 701×1068. Overlays clipped to the
  lowland via a region mask.
- `rim_geojson()` derives the valley-bowl outline and emits `rim.geojson`
  *only* when the lowland forms a genuine ring.
- Buildings carry OSM ids; new `buildings3d.ts` draws stylised 3D blocks with
  estimated heights; sim bands tint exposed blocks; valley-rim toggle;
  FireRed raster treatment; map starts at `pitch: 55`.

### Problem
Hazards were rectangular boxes over a flat grid instead of the real valley
shape, and the map wasn't aesthetically demo-ready.

### Solution
Widen the DEM theatre, clip hazard shapes to the valley bowl, and render a
stylised 3D city with band-tintable blocks.

### Result
kathmandu bundle rebuilt; `rim.geojson` correctly absent for the open basin
(honest 404, frontend hides the toggle); quake zones clipped to the basin;
32 tests pass.

### Evidence
Quake 6.5 M / 10 km at city centre → `area_km2` high 67.77, medium_high
247.48, medium 43.92, low 0.0 (low ring falls off-grid); `test_quake_region_clip_limits_zones_to_basin`.

## 2026-09-12 — Real building footprints replace centroid squares

### Goal
plans.md §10 asks for actual OSM footprints; the 3D city was synthetic
centroid squares.

### What we did
- Backend: buildings fetch switched from `out center 4000` (centroids) to
  `out geom 3000` on an independent 3x3 chunk grid (small chunks → full rings);
  `to_features` emits Polygon geometry; `filter_buildings()` wired in to drop
  slivers <40 m² and degenerate 2-point ways before the 4500 cap.
- Frontend: `buildBlockFeatures()` passes real Polygon rings straight through
  as the extrusion footprint; heights stay *estimated* (OSM tag → type table,
  clamp 3–60 m).

### Problem
The map rendered placeholder squares around centroid points rather than the
real building shapes.

### Solution
Chunked `out geom` fetch for genuine Polygon footprints with honest hover
("~N m est.").

### Result
kathmandu `buildings.geojson` = 4500 Polygon features (mean ring 6.8 pts; 3
with `height`, 328 with `building:levels`); `/api/cities/kathmandu/layers/buildings`
serves them and sim bands still tint by OSM id.

### Evidence
Commit `c9eb100`; `/api/cities/kathmandu/layers/buildings` returns 4500
Polygons; `npx tsc --noEmit` + `npm run build` pass.

## 2026-09-12 — Fix: flat terrain / 3D chunks at the map edges

### Goal
Fix flat regions mixed with properly-elevated 3D terrain near the viewport
edges.

### What we did
- Both `applyTerrain()` call sites pass `city.hazard_bounds ?? city.bounds`.
- New `refreshTerrainRTT(map)` helper (`map.terrain.tileManager.releaseAllRTT()`
  + `map.triggerRepaint()`) fired after the city-load `Promise.all`, on
  `moveend` of the initial `fitBounds`, after band/asset `setData`, and on the
  "3D terrain" toggle.

### Problem
Two frontend causes: (1) the DEM source was constrained to `city.bounds`
(dense core) while the camera fits `hazard_bounds` (wider valley = the DEM
grid), so outer tiles were never requested and rendered flat; (2) stale
render-to-texture terrain composites left fill-extrusion tiles flat until an
interaction churned the cache (maplibre-gl#3001).

### Solution
Correct DEM source bounds on both terrain call sites, plus explicit RTT
refresh after every dataset-changing moment.

### Result
Terrain tiles z11–13 across the Kathmandu hazard box confirmed non-flat and
all served; typecheck and build pass.

### Evidence
`MapView.tsx` `refreshTerrainRTT`; maplibre-gl#3001; implementation-log.md
"Fix: flat terrain/3D chunks" entry.

------------------------------------------------------------------------

# 23. Team Contributions

The team has four coding members.

  Member          Responsibility                                      
  --------------- ----------------------------------------------------- 
  Biplab Basnet   Preparing Documentation (project spec, plans.md,     
                  report, demo narrative)                              
  Rabi Dahal      Preparing the backend (simulation engine: flood /    
                  earthquake / suitability / exposure; data pipeline;  
                  tests; implementation log)                           
  Ignaz Bhatta    Preparing the frontend (map rendering and terrain,    
                  3D city blocks, pixel-art UI, app state; typecheck /  
                  build)                                                
  Saksham Karna   Preparing the presentation (slide narrative and       
                  pitch per plans.md §36–43)                           

Use actual names and contributions. Git history credits the active commits to
Rabi Dahal (`proobker`) for the backend/data pipeline and Ignaz Bhatta
(`IgnazBhatta`) for the frontend, matching the roles above.

------------------------------------------------------------------------

# 24. Challenges & Failed Attempts

For each real problem:

``` text
## Challenge: [TITLE]

### Problem
...

### Initial approach
...

### Why it failed
...

### What changed
...

### Result
...

### Evidence
...
```

Examples to document if they actually occur:

-   API/data failure,
-   DEM processing,
-   coordinate-system errors,
-   slow simulation,
-   spatial intersection bugs,
-   deployment problems,
-   UI confusion,
-   model behavior problems.

Do not hide failures. The goal is to demonstrate actual development and
learning.

The following are the real failures and recoveries from `implementation-log.md`.

## Challenge: Buildings layer kept coming back empty (API/data failure)

### Problem
The frontend consistently showed "buildings: 0" and bundle builds produced no
building features.

### Initial approach
Fetch buildings with `out geom` over the full city bbox in one query.

### Why it failed
Under Overpass mirror load, `out geom` returns degenerate 2-point ways that
`filter_buildings()` then dropped — "buildings: 0". On top of that, a stale
duplicate `fetch_osm` (full-bbox `out geom`) was shadowing the chunked fetch,
so the chunked results never made it into the bundle. Free mirrors also
throttle or dead-end big queries.

### What changed
Removed the shadowing call; switched to chunked `out center` per small box,
capped at 4500; made the pipeline a single tolerant pass (mirrors tried once,
shuffled, 1.5 s backoff, failed chunks skipped).

### Result
Buildings layer populated (4500 per city). Later upgraded to real Polygon
footprints via a 3x3 chunk grid `out geom`.

### Evidence
`scripts/fetch_data.py` rewrite; implementation-log.md "MVP cut-in" and "Real
building footprints" entries.

## Challenge: Flood read as one flat blob no matter the river (model behavior)

### Problem
The graded-surface flood ("raise the whole channel, pond-fill the basin")
painted a single flat flooded area regardless of which river was chosen; the
UI could not differentiate flood behavior.

### Initial approach
Raise the channel elevation and flood all cells below a graded surface.

### Why it failed
No flow direction, no volume conservation and no tributaries; a 2 m "rise"
naively flooded valley-wide, and the flat stroke contradicted the honest
"estimated extent" framing.

### What changed
Rewrote `flood.py` as a transient volume-conserving D8 routing model: rise →
conserved volume, triangular hydrograph, head-driven 8-neighbour flux step
that conserves total volume, catchment-limited domain.

### Result
River-specific extents and volumes; upstream floods first. Seti 2 m → ~1.5
km², ~0.93M m³ routed.

### Evidence
Commits `12de76b` and `fc09629`; `test_erosion_flux_step_conserves_volume`.

## Challenge: Fragmented, inconsistently-spelled OSM rivers (data failure)

### Problem
One physical river counted as dozens of short disjoint ways and understated
reach volume; spellings varied ("Seti", "सेती", with gaps up to 9 km).

### Initial approach
Use the raw OSM water lines as-is for tributary detection.

### Why it failed
The fragments read as dozens of fake tributaries and transliterations split
the same river into many names.

### What changed
Added `normalize_water()`: union-find snap-connect (~50 m), same-stem gap merge
up to 20 km, transliteration folds (`chh→ch`, `ph→f`, `kh→k`, `gh→g`), canal /
river family separation; `--normalize-water` re-run flag.

### Result
kathmandu `water.geojson` 206 → 114 features; pokhara 300 → 210.

### Evidence
Commit `3666b09`; count-stable re-run of `--normalize-water`.

## Challenge: Flood simulation too slow (slow simulation)

### Problem
A whole-grid transient cellular-automaton flood took ~34 s for kathmandu —
too slow for a live demo.

### Initial approach
Simulate the wave across the entire 701×1068 DEM grid every timestep.

### Why it failed
Flushing water over ~750k cells each step is wasteful: reaches propagate only
inside the river's drainage area.

### What changed
Restricted the flux domain to the river's D8 downstream/upstream closures plus
a 12-cell margin.

### Result
Kathmandu flood runtime dropped from ~34 s to ~1.3 s.

### Evidence
implementation-log.md "Flood engine v2" entry; `test_erosion_flux_step_conserves_volume`.

## Challenge: Flat terrain chunks at the map edges (rendering / coordinate bug)

### Problem
With 3D terrain enabled, flat regions appeared mixed with properly-elevated
chunks near the viewport edges — the map looked half-broken.

### Initial approach
Bind the raster-dem source to `city.bounds` and configure terrain once.

### Why it failed
Two causes: terrain tiles are only requested inside the source `bounds` (the
dense urban core) while the camera fits `hazard_bounds` (the wider DEM grid),
so the outer valley had no elevation mesh; and stale render-to-texture terrain
composites left some fill-extrusion tiles flat until an interaction churned
the cache (maplibre-gl#3001).

### What changed
Both `applyTerrain()` sites now pass `hazard_bounds ?? bounds`; added
`refreshTerrainRTT()` (releaseAllRTT + triggerRepaint) after load, initial
`fitBounds`, dataset changes and the terrain toggle.

### Result
Outer valley renders non-flat; terrain tiles z11–13 across the Kathmandu
hazard box confirmed served and elevated.

### Evidence
`MapView.tsx` `refreshTerrainRTT`; maplibre-gl#3001.

## Challenge: No genuine valley rim exists for Kathmandu (geometry edge case)

### Problem
Wanted a dashed "valley rim" line, but the derived outline hugged the DEM box
edge — a fake boundary. Kathmandu's basin is open to the Terai on its NW edge.

### Initial approach
Always emit `rim.geojson` from the cells below `valley_cap_m`.

### Why it failed
An edge-hugging ring misrepresents an open basin as a closed bowl, which would
be dishonest per the project's honesty framing.

### What changed
Added an edge-hugging guard: rings with >35% of points on the grid edge, or
touching grid corners, are rejected — no file is written and the frontend
hides the "Valley rim" toggle.

### Result
Honest 404 for `/api/cities/kathmandu/layers/rim`; the toggle never appears
for an open basin.

### Evidence
`rim_geojson()` guard; TestClient smoke of the rebuilt bundle.

------------------------------------------------------------------------

# 25. Testing

  ------------------------------------------------------------------------
  ID          Test             Input                         Expected              Actual                            Status
  ----------- ---------------- ---------------------------- --------------------- --------------------------------- ----------------
  T01         Flood            Kathmandu, Seti river, rise  Flooded extent         ~1.5 km² extent, ~0.93M m³        PASS
                               2 m                          seeded along the       routed, 76 overlay polys, ~9 h
                                                             river's downhill       wave; dry:false
                                                             flow path
  T02         Earthquake       Kathmandu, M 6.5, depth      4 relative bands;      high 67.77 / medium_high           PASS
                               10 km, epicentre at city     zones clipped to       247.48 / medium 43.92 /
                               centre                       the valley basin       low 0.0 km² (low ring off-
                                                                                   grid)
  T03         Infrastructure   Flood + quake on kathmandu   Per-kind                Flood 285/500 facilities          PASS
              exposure         (500 facilities, 4500        flooded/exposed        estimated flooded; quake 338
                               buildings)                   counts                 in the high band; blocks tinted
                                                                                   by OSM id
  T04         Hospital         Planned hospital (plan-1)    Per-asset verdict      API returns exposure.assets +      PASS
              placement        on kathmandu flood;          returned for the       affected incl. plan-1 / plan-9;
                               planned school (plan-9)      proposed asset         verdicts follow the plan
                               on kathmandu quake                                  location
  T05         Plan             Pokhara suitability +        green/yellow/red       2678/5480/2822 green/yellow/red    PASS
              comparison       hospital moved across a      areas stable;          cells; verdict flips when the
                               hazard boundary              moving an asset        asset crosses the boundary
                                                             changes its verdict
  ------------------------------------------------------------------------

Total: 32 backend tests pass (`cd backend && uv run pytest`) plus frontend
`npx tsc --noEmit -p tsconfig.app.json` and `npm run build`.

## Sanity checks

The checks below are asserted in the test suite:

-   Raising the flood `level_m` from 2 m to 50 m on the same river must not
    shrink the modeled flooded area (`test_river_flood_seeds_channel`,
    `test_rivers_in_separate_valleys_stay_disjoint_until_overtopped`) — PASS.
-   Earthquake results behave consistently with the implemented attenuation
    relationship: intensity and band radii stay monotonic with distance
    (`test_quake_intensity_decays_with_distance`,
    `test_quake_radii_monotonic_by_severity`) — PASS.
-   Moving a planned asset across a hazard boundary changes its exposure
    verdict (`test_flood_uses_planned_assets`, `test_quake_uses_planned_assets`)
    — PASS.
-   D8 flow never routes uphill and the flux step conserves total volume
    (`test_d8_flow_direction_points_downhill`,
    `test_erosion_flux_step_conserves_volume`) — PASS.

These are checks of model behavior, not proof of real-world accuracy.

------------------------------------------------------------------------

# 26. Validation

Validation asks:

> Does the prototype behave consistently with its stated assumptions?

Evidence produced during development:

-   **Controlled scenarios** — a synthetic "bowl" city bundle in
    `test_engine.py` exercises flood, earthquake, suitability and terrain in
    isolation: a flood stays one connected component, and the valley-region
    clip reduces both quake and flood extents (`test_quake_region_clip...`,
    `test_flood_region_clip...`).
-   **Manually checked locations** — Kathmandu Seti and Rudramati flood runs
    and the 6.5 M quake were run via TestClient against the real bundle and
    the extents confirmed sensible (Seti 2 m → ~1.5 km²; Rudramati 3 m →
    dry:false, 4361 cells ~4.31 km², peak depth 7.4 m).
-   **Elevation sanity checks** — terrain-tile centre pixels match a direct
    DEM sample to <1 m (Terrarium roundtrip, Mercator row and encoder all
    agree), and sampling a DEM cell centre returns that cell's elevation
    (`test_terrain_tile_roundtrips_terrarium`,
    `test_terrain_sample_hits_cell_centres`).
-   **Before/after layouts** — a proposed hospital/school is evaluated on
    kathmandu flood and quake scenarios and the verdict tracks the asset's
    location (planned-assets API override).
-   **Comparison with reference datasets** — 4500 real OSM Polygon footprints
    and the Copernicus/SRTM DEM (over the hazard theatre) replace the earlier
    centroid squares; heights remain explicitly estimated.

The prototype therefore behaves consistently with its stated assumptions;
everything remains framed as estimated / scenario-based exposure per plans.md
§30.

------------------------------------------------------------------------

# 28. Deployment

### Frontend

Not yet deployed to a public host — it runs as the local Vite dev server at
`http://localhost:5173` (`cd frontend && npm run dev`). The production bundle
(`npm run build`) is built and verified locally.

### Backend

Not yet deployed to a public host — it runs locally on uvicorn at
`http://127.0.0.1:8000` (`cd backend && uv run uvicorn app.main:app --port
8000`). The frontend reaches it via `VITE_API_BASE`
(`http://127.0.0.1:8000` by default).

### Database

None. The backend deliberately ships without a database; all demo data is
pre-baked into `data/bundles/` and loaded at runtime.

### External services

List only the services actually used. Both are build-time only — the runtime
demo is offline-ish:

-   Overpass API — OpenStreetMap data fetch (build / bundle regeneration).
-   Mapzen "Terrarium" elevation tiles (Copernicus/SRTM) — DEM fetch.

### Environment variables

Document variable names without publishing secret values (there are none):

-   `VITE_API_BASE` — frontend API base, default `http://127.0.0.1:8000`.
-   `OVERPASS_TIMEOUT` — Overpass query timeout for `scripts/fetch_data.py`
    (default 40 s).

------------------------------------------------------------------------

# 29. Reproducibility

A technical judge should be able to understand how to run the project.

### Prerequisites

-   Python ≥ 3.14 with [`uv`](https://docs.astral.sh/uv/) (backend).
-   Node.js and npm (frontend).
-   No API keys or secrets required.

### Data setup

Demo data for kathmandu and pokhara ships committed in `data/bundles/`, so the
demo runs without network. To regenerate bundles from upstream sources:

``` bash
cd backend
uv sync --group dev
uv run --group dev python ../scripts/fetch_data.py --all
```

### Run the demo

``` bash
git clone https://github.com/proobker/terrasim
Then go to Terrasim or change directory to terrasim
cd backend
uv sync          # create venv + install deps
uv run uvicorn app.main:app --reload --port 8000

cd frontend

```

Then:

``` bash
npm install
npm run dev
```

Open `http://localhost:5173`; health check at `http://127.0.0.1:8000/api/health`.

### Tests

``` bash
cd backend && uv run pytest                      # engine + API tests
cd frontend && npx tsc --noEmit -p tsconfig.app.json   # typecheck
cd frontend && npm run build                     # typecheck + production build
```

### Deployment

Currently local-only (see §28): start the backend with uvicorn and the
frontend with `npm run dev` / a built bundle served over any static host, with
the API base pointed at the backend via `VITE_API_BASE`. No database or
external runtime service is required.