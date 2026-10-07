# Implementation log

Status ledger for terrasim. Most recent at the top. `plans.md` is the spec; this file records what physically exists and what was verified. Entries follow the development-log template (Goal / What we did / Problem / Solution / Result / Evidence) and only record what actually happened.

## 2026-10-07 — Whole-valley roads + facilities, and faster loads

### Goal
1. Roads stopped about halfway up the Kathmandu valley. Cover the whole valley.
2. Make the live site load faster.

### What we did
- **Data (`scripts/fetch_data.py`).**
  - New `roads_from_pbf` and `facilities_from_pbf` read the cached GeoFabrik PBF over `city_feature_bounds`: the union of `bounds`, `building_bounds` and `hazard_bounds`, i.e. `[85.15, 27.54, 85.47, 27.78]` for Kathmandu.
  - New `--pbf-infra` flag, and `build_city` uses these extractors for PBF cities.
  - Roads are simplified with Douglas-Peucker (~2 m) and stored at 5 decimals.
  - Kathmandu roads: 5,538 → **27,342** (6.6 MB raw, 1.26 MB gzipped).
  - Kathmandu facilities: 500 → **4,045**: 2,275 schools, 489 colleges, 427 clinics, 266 hospitals, 215 community centres, 201 shelters, 152 police, 16 universities, 4 fire stations.
- **Backend: exposure (`exposure.py`, `datasets.py`).**
  - `PointAssets` takes an optional `starts` (CSR offsets), so one asset can own many sample points. `line_assets` densifies roads with the same sampling as the per-feature path.
  - Flood uses `np.logical_or.reduceat` across a road's points and quake uses `np.minimum.reduceat` (most severe band).
  - Road arrays are cached per bundle (`datasets._road_assets`), and `_warm_caches` builds them at startup.
- **Backend: bug fix.** The per-feature quake path reported a multi-point asset's *least* severe band: it took the max of `BANDS.index + 1`, and BANDS runs high → low. It now takes the most severe band.
- **Backend: API.** Added `GZipMiddleware` (≥1 KB, level 5). Responses that already carry `Content-Encoding` (layers, building tiles) pass through untouched.
- **Frontend: map styling (`MapView.tsx`).**
  - Road width and opacity now depend on OSM class and zoom: motorway/trunk/primary/secondary stay bold, residential lanes fade in.
  - Facility icons collide instead of stacking (`icon-allow-overlap: false`). `symbol-sort-key` puts hospital, then fire, then police, then clinic, then shelter, then school.
- **Frontend: boot screen (`App.tsx`, `store.ts`).** Against a non-local API, the first failed city fetch switches the boot screen to a steady "waking up the sim engine… Ns" message with a progress bar. Before, it flickered every 2.5 s between "connecting" and the dev-only `uv run uvicorn` hint. The first failure time is stored as `bootFailedAt` in the store.
- **Infra.**
  - New `.github/workflows/keep-warm.yml` pings `/api/health` every 10 min.
  - `render.yaml` serves `/assets/*` (content-hashed) with `Cache-Control: public, max-age=31536000, immutable`.
- **Tests.**
  - `test_road_assets_exposure_matches_per_feature_path[kathmandu|pokhara]`
  - `test_quake_exposure_takes_most_severe_band_along_a_road`
- **Docs.** README (deploy cold starts, `--pbf-infra`), AGENTS.md (PBF infra gotcha) and TECH_STACK.md.

### Problem
- **Roads.** The Overpass pass split `bounds` into 2×2 chunks, capped each at `out geom 3000`, and stopped once `ROAD_MAX=4500` was reached. That happened after the two southern chunks, so the north was never queried. It also only covered the core box, not the valley.
- **Facilities.** The whole set was capped at `FACILITY_MAX=500`, and hospitals and clinics alone used all 500 slots.
- **Load time.** A live profile from a fresh browser:
  - `/api/cities` failed for **~46 s** while the sleeping free-tier API woke (`x-render-routing: hibernate-wake-error` / `no-deploy`, 502/503). The page revealed at 63 s.
  - With the API up, the rest of boot took **~2.5 s**. The frontend was never the bottleneck.
- **Quake runs.** A Kathmandu quake response was 16 MB of uncompressed JSON. With 5× the roads, the per-feature road loop pushed a quake run from 4.8 s to 8.3 s.

### Solution
- Extract roads and facilities from the PBF the buildings already come from.
- Vectorise road exposure the same way buildings were.
- Gzip API responses.
- Keep the API awake and say so honestly while it wakes.
- Cache the hashed assets forever.

### Result
Measured locally:

| | before | after |
|---|---|---|
| Kathmandu quake M7.0, warm | 4.8 s (half the roads) | **0.8 s** (all roads) |
| quake response on the wire | 16.0 MB | **1.34 MB** gzipped |
| server memory after a quake | peak 311 MB | peak 284 MB |
| local boot to reveal | — | 3.3 s |

The roads layer download grows from 0.62 MB to 1.26 MB gzipped for 5× the roads.

### Evidence
Verified live:
- Live profile via Chrome DevTools against `terrasim.rabidahal.com.np` before the change: reveal at 62.9 s, with `/api/cities` failing until 46.6 s. A second load failed for 33 s, then revealed 2.5 s after the API answered.
- Checks on the new code and data:
  - `uv run pytest`: 58 passed.
  - `npx tsc -b` and `npm run lint` are clean (the one ExposurePanel warning was already there).
  - Local Vite + uvicorn screenshots: whole-valley roads with arterials emphasised at valley zoom, and the full street grid north of the Ring Road at z14.6.
- Not yet verified on the live site after deploy. The keep-warm workflow only proves itself after it has run on schedule.

## 2026-10-07 — One failed building tile no longer kills the map

### Goal
The live site showed a "Map failed to start: AJAXError: NetworkError … /tiles/buildings/13/6039/3441.pbf" toast. One building tile had failed while the API was unreachable. That can happen during a free-tier cold start, or during the redeploy that each push to `main` triggers.

### What we did
- **Frontend (`MapView.tsx`, `map.on("error")`).** Errors that carry `tile` or `sourceId`, i.e. tile and source load failures, are now always logged as `console.warn`. Only other errors raised before the style finishes loading show the "Map failed to start" toast.
- No backend changes.

### Problem
The handler decided an error was fatal using `!map.isStyleLoaded()`. MapLibre's `Style.loaded()` returns false while any tile manager still has tiles in flight. So during the initial tile burst, a single failed tile counted as a startup failure. The comment above the handler had already intended tile failures to be warnings.

### Solution
Classify errors by their payload rather than by load state. MapLibre fires tile load errors as `ErrorEvent(err, {tile})`, which is tagged with `sourceId` once forwarded through the style.

### Result
A tile fetch that fails while the API is waking up leaves only a gap in the building layer. That tile fills in when the map re-requests it (pan or zoom), and the toast no longer appears.

### Evidence
Verified live:
- `curl https://terrasim-api.onrender.com/api/health` returned 200 (0.6 s).
- The same tile with `Origin: https://terrasim.rabidahal.com.np` returned 200 `application/x-protobuf` with a matching `access-control-allow-origin`, so CORS is fine and the failure was transient.
- `npx tsc -b` and `npm run build` passed.
- Not yet re-checked in a browser after this deploy.

## 2026-10-07 — Custom domain showed nothing (Render www redirect)

### Goal
Get `https://terrasim.rabidahal.com.np` to serve the frontend. Cloudflare DNS already pointed it at Render.

### What we did
- **Diagnosis.**
  - DNS was correct: `terrasim.rabidahal.com.np` → CNAME `terrasim.onrender.com` (DNS only).
  - `https://terrasim.onrender.com` returned 200.
  - The custom domain returned `301 → https://www.terrasim.rabidahal.com.np/`, and that host was NXDOMAIN.
- **Infra (Render dashboard, done by hand).** Removed the auto-added `www.` custom domain so the bare domain serves the site directly.
- **Docs.** The README "Deploy on Render → Custom domain" step now explains the `www` trap, gives the Cloudflare CNAME fallback and the `curl -I` check, and says to keep the record DNS only.
- No code, test, bundle or `render.yaml` changes. `CORS_ORIGINS` already listed the domain.

### Problem
Render reads `.com.np` as a TLD, so it treated `terrasim.rabidahal.com.np` as a root domain: it added a `www.` variant and redirected the bare domain to it. The `www` host had no DNS record, so browsers ended up with nothing.

### Solution
Drop the `www` entry on Render so there's no redirect. The fallback, if Render insists on the `www` entry, is a DNS-only `www.terrasim` CNAME in Cloudflare.

### Result
`https://terrasim.rabidahal.com.np` serves the app directly.

### Evidence
Verified live:
- `curl -I https://terrasim.rabidahal.com.np` → `HTTP/1.1 200 OK`.
- The page `<title>` is "terrasim — Building Resilient Areas".

## 2026-10-07 — Scenario exposure reads buildings from the npz (1004 → 272 MB peak)

### Goal
Fix the issue flagged on 2026-10-06: every flood/quake run re-parsed `buildings.geojson` through `load_assets`. That peaked around 1 GB, more than Render's 512 MB free tier, so the first scenario run would have killed the instance.

### What we did
- **Backend: npz (`building_tiles.py`).** `pack` now also stores each building's exposure point as `alng`/`alat`, chosen by `_exposure_point` with the same rule exposure used on the raw GeoJSON: a polygon's `centroid` property, otherwise a point's own coordinate, otherwise shapely `representative_point`. `CACHE_VERSION` is 1 → 2. The new `points(city_id)` loads only those arrays plus ids and names (lru-cached).
- **Backend: exposure (`exposure.py`).** New `PointAssets`, which holds the buildings as arrays. `evaluate_flood_exposure` and `evaluate_quake_exposure` handle it in one numpy pass (vectorised `DemGrid.cell` and `quake_zones_at` + `band_for`). Counts and listed ids come out in the same order as before. Roads, facilities and planner-supplied assets keep the per-feature path.
- **Backend: `datasets.load_assets`.** Buildings are now a `PointAssets` built from the npz. Roads and facilities still come from their (small) GeoJSON.
- **Data.** Regenerated both npz files: Kathmandu 16.5 → 20.4 MB, Pokhara 148 → 205 KB.
- **Tests.**
  - New `test_point_assets_exposure_matches_per_feature_path[kathmandu|pokhara]` checks the vectorised path against the dict path, for quake and flood.
  - The `city` fixture in `test_engine.py` set `datasets.DATA_ROOT` globally and never restored it, so every later test saw the synthetic bundle. It now uses `monkeypatch.setattr`.
- **Docs.** The AGENTS.md npz gotcha now covers exposure points and the `src_size` freshness rule.

### Problem
`load_assets` called `load_layer("buildings")`, i.e. `json.load` of 101 MB. Then it built 362k asset dicts and classified them one by one, calling `quake_zones_at` once per building.

### Solution
Each building already needs only one exposure point, an id and a name, so ship those in the npz that's committed anyway and classify every building in a single array pass.

### Result
| Kathmandu M7.0 quake (cold process, after warm-up) | before | after |
|---|---|---|
| peak working set | 1004 MB | 272 MB |
| request time (local) | 13.0 s | 4.8 s |

- Kathmandu flood: 8.8 → 3.8 s.
- The response is the same 13 MB, because the per-building `exposed` list is unchanged (the frontend tints by it). Shrinking it is a separate job.

### Evidence
- Snapshot script over 4 scenarios (Kathmandu and Pokhara × quake and flood): the `exposure` JSON is **identical** before and after (sha256 `d34caecf…`, `af47f5ec…`, `bb441a01…`, `719fe4aa…`).
- Peak memory: Win32 `PeakWorkingSetSize` read in a cold process. The old code was measured with the matching v1 npz.
- `uv run pytest` (backend): 55 passed.

## 2026-10-07 — Deploy: stop the fresh-checkout npz rebuild that OOM-killed Render

### Goal
Get the backend live on Render again. The auto-deploy of `0400b0a` (building tiles) failed after 4m35s, so `terrasim-api` kept serving the old build (`64b7bd0`), which has no `/tiles/buildings` endpoint.

### What we did
- **Backend (`app/engine/building_tiles.py`).** `ensure_cache` no longer compares mtimes. It trusts `buildings.blocks.npz` when `version == CACHE_VERSION` and the stored `src_size` matches the GeoJSON's byte size. A rebuild now writes `src_size` into the npz.
- **Data.** Regenerated both committed npz files so they carry `src_size` (Kathmandu 101,384,487, Pokhara 564,123). Every other array is byte-identical to the previous commit.
- **Tests.** Added `test_committed_cache_is_fresh_regardless_of_mtime[kathmandu|pokhara]`, which backdates the npz below the GeoJSON's mtime and asserts `pack` is never called.
- **Blueprint (`render.yaml`).** Fixed the `VITE_API_BASE` typo `https://terrasim-api.onrender.com.github/` → `https://terrasim-api.onrender.com`. The live bundle already used the correct URL, so a dashboard value was masking it; the next blueprint sync would have broken it.

### Problem
A fresh `git clone` stamps files in checkout order. In a clean clone, `kathmandu/buildings.blocks.npz` has mtime `…989.38` and `buildings.geojson` has `…989.88`, so the npz looked stale. On boot, `_warm_caches` called `ensure_cache`, which re-parsed the 97 MB GeoJSON (~900 MB peak, per the 2026-10-06 entry) on a 512 MB free instance. The instance was killed before the health check passed.

### Solution
Fingerprint the source by content size, which a checkout preserves, instead of by timestamps, which it does not.

### Result
The committed caches are accepted as-is on any checkout, so boot only loads the npz (~132 MB peak) instead of the GeoJSON.

### Evidence
- `uv run pytest` (backend): all pass, `tests/test_building_tiles.py` 16 passed.
- Fresh-clone mtime check reproduced the inverted ordering above.
- Before push: `GET https://terrasim-api.onrender.com/api/health` → 200 (old build, 34 s cold start); the live frontend bundle points at `https://terrasim-api.onrender.com`.
- Not verified live: the Render deploy itself (no dashboard or log access from this session; Docker isn't running locally).

## 2026-10-06 — Map: one-colour imagery, buildings as vector tiles, 6.5 s cold boot

### Goal
Fix the "incomplete loading" in the user's screenshot of the opening view. A hard horizontal colour seam crossed the valley, and buildings and roads hadn't appeared yet. Make the boot reveal a finished city quickly.

### What we did
- **Frontend: imagery seam (`MapView.tsx`).** `satellite` now has `minzoom: 12` (`SATELLITE_LO_MAXZOOM + 1`), so the sharp layer only ever shows Esri's z12+ mosaic. The `ts-satellite-lo` underlay (z≤11, now the distant ground) is colour-matched to it: `raster-saturation -0.2`, `raster-contrast -0.06`, `raster-brightness-min 0.08`.
- **Backend: layer endpoint (`main.py`, `datasets.py`).** `/api/cities/{id}/layers/{kind}` ships the bundle file's bytes, gzipped once and cached (`datasets.layer_gzip`, keyed by mtime), with an `ETag` and a 304 on match. It no longer `json.load`s the file for FastAPI to re-encode. A start-up thread (`_warm_caches`) pre-gzips the small layers.
- **Backend: building vector tiles (`app/engine/building_tiles.py`, new).**
  - `GET /api/cities/{id}/tiles/buildings/{z}/{x}/{y}.pbf` serves Mapbox Vector Tiles at z13–15: gzip, `Cache-Control: public, max-age=3600`, 204 for an empty, out-of-range or unknown tile.
  - Each building lands in exactly one tile, by its centroid, so there's no clipping and no double draws.
  - `estimate_height` and `tint` (FNV-1a over UTF-16, `RANDOM_TINTS`) are ported from `buildings3d.ts` and bake each block's height and colour into the tile.
  - The MVT/protobuf encoder is hand-written and vectorised with numpy, with no new dependency.
  - Footprints are packed once into `data/bundles/<city>/buildings.blocks.npz` (int32 coords at 1e-7°): Kathmandu 15.7 MB, Pokhara 145 KB, committed with the bundles. It rebuilds when older than the GeoJSON or when `CACHE_VERSION` changes.
  - `_warm_caches` loads the index and encodes z13 tiles over `hazard_bounds` and z14 over `bounds`.
- **Frontend: buildings source.** `ts-infra-buildings` is now a `vector` source (`minzoom 13`, `maxzoom 15`, tiles set per city with `setTiles`) with `source-layer: "buildings"`. Hazard bands tint blocks through **feature state** (`setFeatureState` on numeric OSM ids, tracked in `bandedRef`) instead of re-`setData`-ing every block. The tooltip reads the band from `f.state`.
  - `buildBlockFeatures`, `estimateHeight`, `typeDef`, `num`, `polygonCoords`, `ringCentroid` and `RANDOM_TINTS` are removed from `buildings3d.ts` (now dead). Planned assets keep `buildAssetBlocks` and `applyBands`.
- **Frontend: boot gate.** The boot screen waits for the core tile preload *and* the city's layers to be drawn (20 s cap), with staged text ("terrain & imagery", "city layers", "building the city"). `onLoadProgress(fraction, stage)` is the new signature. A pulsing `.map-loading-chip` ("loading city layers…", `index.css`) shows while layers are still in flight after the reveal or after a city switch.
- **Docs.** AGENTS.md lists `buildings.blocks.npz` and has a gotcha on regenerating and committing it.

### Problem
- **Seam:** maplibre drew z12 Esri tiles near the camera and z11 farther off, and Esri grades those zooms as different mosaics. Mean tile RGB over the valley was z11 `[66,68,30]` vs z12 `[78,78,61]`, with the blue channel about half, so a tile row became a hard yellow/grey line.
- **Missing buildings:** the 362,022-footprint layer was 101 MB of JSON. The API re-encoded it in ~25 s, then the page spent 1.0 s in `JSON.parse` plus a 4.2 s main-thread task cloning it into maplibre's worker, then ~7.5 s tiling it. Buildings showed ~17–19 s after load.
  - Splitting into 4 GeoJSON sources only cut the tiling (10.1 → 5.9 s).
  - Loading by URL doesn't help either: maplibre v6's worker posts the parsed data *back* to the main thread (`maplibre-gl-worker-dev.mjs:683`, `result.data = params.data`).
  - So any GeoJSON source means a whole-city structured clone.
- The first tile prototype took 41 s to index with an 893 MB peak (`json.load`) and up to 42 s per z12 tile (per-ring numpy calls).

### Solution
- **Seam:** keep the two mosaics apart by zoom and colour-correct the far one. The paint values are a least-squares fit of 15 z11 tiles against their z12 children, as drawn with the sharp layer's own paint.
- **Buildings:** serve them pre-cut and pre-styled as vector tiles, so the browser fetches only the few tiles in view. Pack the footprints into an npz once, and vectorise the encoder across all rings of a tile (dedupe, closing point, shoelace winding, deltas and command stream in numpy; one varint pass).

### Result
- No seam: one continuous colour from foreground to horizon at the opening view.
- Cold boot (empty cache) reveals at **6.5 s** with nothing left loading. The last GeoJSON build took ~17–19 s.
- At z15 over the centre, 87,781 blocks render with real footprints, the same tints, and the hover tooltip working ("Khulla Bazar · ~7 m est.").
- A quake run tints blocks via feature state (71,011 high + 16,770 medium-high in view) without re-uploading geometry.
- Tile encode: busiest z13 tile 0.73 s (52,774 blocks, 0.83 MB gz), z14 0.22 s, z15 0.06 s, all cached. The npz index loads in 0.42 s with a 132 MB peak.
- Not fixed, flagged: `/api/simulate/earthquake` still takes ~17 s and returns 13 MB, because `load_assets` re-parses `buildings.geojson` on every run (~900 MB peak, likely too much for Render's free tier). The frontend tint waits on it.

### Evidence
Verified live on a local backend (8000) and Vite (5173) in Chrome via DevTools, in fresh isolated browser contexts:
- **Seam:** screenshot of the default opening view before and after; mean tile RGB per zoom measured in-page.
- **Layer endpoint:** buildings layer 200 at 18.1 MB gz in 0.25 s, 304 on revalidate, rim still 404.
- **Boot:** timeline sampled from the boot screen; `queryRenderedFeatures` on `ts-infra-buildings` / `ts-infra-roads`; per-tile encode timings in Python.
- **Parity:** Python height, colour and id vs the TS `buildBlockFeatures` for all 362,022 Kathmandu buildings: 0 mismatches.
- **Checks.** `uv run pytest`: 51 passed (37 + 14 new in `tests/test_building_tiles.py`: height/tint parity cases, tiles decoded back to source footprints within 0.75 units with MVT winding, one-tile-per-building, endpoint 200/204, gzip cache). `npx tsc -b` passes. `npm run lint` passes (only the existing `ExposurePanel.tsx` warning). `npm run build` passes.

## 2026-10-06 — Map: no see-through holes while panning + forced tile preload

### Goal
Fix the glitch in the user's screen recording: while dragging the 3D map, tile-sized patches went see-through (dark-green page background), and neighbouring tiles hung stretched-imagery "curtains" into the gap. Also make the first load feel solid by preloading tiles behind the boot screen.

### What we did
- **Frontend: imagery fallback (`MapView.tsx`).** Two layers now sit under `ts-satellite`. `ts-ground` is a `background` layer (`#6b6a4c`). `ts-satellite-lo` uses a new `satellite-lo` source: the same Esri URL (now `SATELLITE_TILES`), capped at `maxzoom` 11 (`SATELLITE_LO_MAXZOOM`), with the same paint as the sharp layer.
- **Frontend: DEM cap.** The `dem` source `maxzoom` drops from 15 to 12 (`DEM_MAXZOOM`). SRTM is ~30 m and terrarium z12 is ~34 m/px at Nepal's latitude, so z13–15 were upsampled copies of the same data.
- **Frontend: forced preload (`prefetch.ts`, new).** `tileUrls()` lists the slippy tiles over a bounds and zoom range. `prefetch()` fetches them with bounded concurrency into the browser HTTP cache. S3 sends a 2017 `Last-Modified` and Esri sends `max-age=86400`, so maplibre then reads them from cache.
  - Per city, the **core** set (Kathmandu 86 tiles: 55 underlay z8–11 over the hazard bounds padded 100%, 31 DEM z8–11 padded 50%) is preloaded first, underlay before DEM.
  - The **detail** set (Kathmandu 498 tiles: DEM z12, imagery z12–13 padded 50%, imagery z14 over the hazard bounds) streams at concurrency 4 after the core set finishes. Pokhara is 47 core and 212 detail.
- **Frontend: boot gate.** `onReady` no longer fires when the map is constructed. On the first city it fires once the core preload is done *and* the opening view is idle, with an 8 s overall cap. The new `onLoadProgress` prop drives the boot screen: `App.tsx`'s `BootScreen` shows "loading terrain & imagery… N%" with a real bar instead of a fixed 70%.
- **Frontend: WebGL context loss.** `webglcontextlost` sets `mapLoaded` false; `webglcontextrestored` sets it back true after `style.load`. Previously any effect after a context loss called into `map.style === null` and React unmounted the whole app (blank page). `webgl2Available()` now releases its probe context (`WEBGL_lose_context`) instead of leaking one per mount.

### Problem
Under terrain, maplibre composites each terrain tile's draped layers into a render-to-texture. While panning into new ground, the Esri tiles for that area weren't loaded and no lower-zoom parent was cached, so the composite was transparent. The page background showed through, and the skirts of tiles behind it, normally hidden, read as stretched curtains.

A per-frame probe over a cold-cache scripted pan found terrain tiles with no imagery in **74% of frames (201/271), up to 23 tiles at once**. The DEM was not the culprit: 0 tiles fell back to the flat 0 m DEM. A separate blank-page crash seen during testing was a WebGL context loss ("Too many active WebGL contexts", with several map tabs open) followed by an effect touching the destroyed style.

### Solution
Always have *something* to drape. A coarse z11 copy of the same imagery covers the valley in about 55 tiles and is cached before the reveal, so a still-loading tile shows blurry ground instead of a hole. A background colour covers the far horizon, where maplibre's raster coverage stops short of the terrain's. Preloading puts the sharp z12–14 fallback in cache, so the sharp layer fills in from cache (~14 ms) rather than the network (85–150 ms Esri, 1–4 s S3).

### Result
- Mid-pan screenshots over unvisited ground and over the city show no see-through tiles and no curtains. Freshly entered ground is briefly blurry, Google Earth-style, then sharpens.
- Near-camera tiles with no imagery went from 74% of frames to **0**. The only imagery-less tiles left are z≤10 tiles on the far horizon, outside maplibre's raster covering range; they now paint `ts-ground` under the haze.
- Cold-cache boot revealed at 7.1 s and 8.2 s from navigation in two runs. An earlier draft that blocked on all 304 tiles took 19 s.
- Forcing a context loss with `WEBGL_lose_context`, toggling a layer checkbox while lost, then restoring gives back all 21 layers, terrain, and the building data, with no errors and the app still mounted.

### Evidence
Verified live on a local backend (8000) and Vite (5173) in Chrome via DevTools, using fresh isolated browser contexts (cold HTTP cache) and one map tab:
- **Frame probe.** Per `render`, terrain tiles from `terrain.tileManager.getRenderableTiles()` were checked against `renderToTexture._coordsAscending` for loaded `satellite` / `satellite-lo` tiles and a DEM via `getSourceTile(…, true)`. Same 4-pose `easeTo` route as the baseline. Before: 201/271 frames with imagery-less tiles, max 23. After: 0 near-camera, 0 flat-DEM frames, 40% of frames with at least one blurry fallback tile.
- **Resource timing** (buffer raised to 10 000) during a pan inside the preloaded ring: Esri z10–14 p50 11–22 ms (cache), z15–17 p50 85–148 ms (network); DEM z11–12 4–23 ms.
- **Checks.** `npx tsc -b` passes. `npm run lint` passes (only the existing `ExposurePanel.tsx` warning). `npm run build` passes (existing >500 kB chunk warning).

## 2026-10-06 — Map: Google Earth-style terrain, no more white walls/spikes

### Goal
Kill the 3D-map glitches (white translucent band across the city, white wedge, white "cracks", a tall spike at the edge) and make the terrain read like Google Earth: real imagery over real mountains with the Himalaya on the horizon.

### What we did
- **Frontend (`MapView.tsx`).** The `dem` raster-dem source now points at the global, keyless AWS Terrain Tiles (`elevation-tiles-prod/terrarium`, 256 px, maxzoom 15) instead of `/api/cities/{id}/terrain`. `DEM_PAD`/`padBounds` and the per-city `setTiles` are gone, and `applyTerrain(map, enabled)` lost its city/bounds args. Exaggeration is now 1.2 (was 1.3).
- **Base map.** Esri World Imagery replaces the hue-rotated OSM raster. Paint is `raster-saturation 0.1`, `raster-contrast 0.08`, `raster-fade-duration 0`.
- **Sky.** Blue zenith `#3f7fc4`, pale horizon `#d6e6f2`, haze fog `#c9dbe8`, `fog-ground-blend 0.6`, and `atmosphere-blend` interpolated by zoom (1 → 0.4 from z10 to z14). `maxPitch` raised to 75.
- **Camera fit.** `fitBounds` gets right padding equal to how much the floating Scenario Lab panel covers the map (capped at 45% of the map width), so the valley is no longer framed under the panel.
- **Overlay refresh.** New `sourcedata` hook: when a `ts-*` GeoJSON source finishes a `content` update, the terrain RTT is released on the next `idle`. Previously the post-`setData` refresh ran before the worker had parsed the data, so quake zones stayed invisible until the camera moved.
- **Overlay legibility.** Quake band `fill-opacity` raised from 0.34 to 0.46 so the medium and medium-high rings show over the tan valley imagery.
- **Attribution.** Moved to bottom-left and no longer compact ("Terrain © Mapzen/AWS | Imagery © Esri, Maxar, Earthstar Geographics"). The bottom-right spot sat under the panel, and maplibre's white background now loses to a higher-specificity dark style (`index.css`).
- **Dev hook.** `window.__terrasimMap` is set in dev builds only (`import.meta.env.DEV`) so browser smoke tests can drive the camera. `api.terrainUrl` was removed because nothing uses it.
- **Docs.** README attribution adds AWS Terrain Tiles and Esri imagery. TECH_STACK notes that the map no longer renders from `terrain_tiles.py`.

### Problem
The backend DEM endpoint only covers the city DEM plus a 50% pad, and the pad is edge-clamped. Past the pad, tiles 404, so maplibre falls back to a flat 0 m plane. That left a ~1300 m cliff at the coverage edge. With fog on, its walls rendered as the white band and wedge, and the edges showed as spikes and cracks. The bundle DEM itself is clean (Kathmandu 819–2832 m, Pokhara 587–2143 m, no NaN), so the bug was coverage, not data.

### Solution
Render from a global DEM so there is no coverage edge left to fall off. The simulations still run on the bundle DEM, and both datasets are SRTM lineage, so the draped results still line up with the ground.

### Result
No walls, wedges, spikes or cracks at any tested angle. In Kathmandu and Pokhara the Himalaya and Annapurna ranges are visible on the horizon, and the city sits beside the panel instead of under it. Earthquake zones drape onto the terrain without a camera nudge, and the suitability zones in Pokhara follow the hills. Turning 3D terrain off and back on works.

### Evidence
Verified live on a local backend (8000) and Vite (5173, strictPort) in Chrome via DevTools:
- **Cliff test.** A scripted check sampled `queryTerrainElevation` on 60×60 and 50×50 grids at 8 camera poses (z9–13.5, pitch 55–75, bearings 0/45/120/180/-90). The steepest step between neighbouring samples was 0.77–1.26 (≈ 38–52°, real mountain slope), with 0 missing samples. A 0 m cliff would score ≥ 5.
- **Interaction.** Pointer-event pan and right-drag rotate were screenshotted mid-load with no walls.
- **Scenario.** An M6.5 earthquake run in Kathmandu rendered 8 zones without moving the camera.
- **Console.** Only errors were the existing `layers/rim` 404s.
- **Checks.** `npm run build` and `npm run lint` pass (one existing warning in `ExposurePanel.tsx`). `uv run pytest`: 37 passed.

## 2026-09-24 — Deploy: Render blueprint + GitHub hardening

### Goal
Host the demo publicly (free tier) and make the GitHub repo contributor-ready: a reproducible backend image, a static frontend build wired to a live API base, CORS that accepts a custom domain, CI that gates PRs, and a real issue/feature backlog.

### What we did
- **Backend.** `app/main.py`: CORS origins now come from a `CORS_ORIGINS` env var (comma-separated, appended to the localhost defaults); no origin lost when deployed.
- **Deploy.** `Dockerfile.backend`: `ghcr.io/astral-sh/uv:python3.14-bookworm-slim`, `uv sync --frozen --no-dev`, uvicorn on `0.0.0.0:${PORT:-8000}`; `DATA_ROOT` resolves to the committed `data/bundles/` absolute path, so no env needed in the container. `.dockerignore` skips `.git`, `frontend/node_modules`, `frontend/dist`, `data/fetch`, `*.egg-info`. `render.yaml` blueprint: `terrasim-api` (docker web, health check `/api/health`, `CORS_ORIGINS=https://terrasim.rabidahal.com.np`) + `terrasim` (static, `cd frontend && npm ci && npm run build`, publish `./frontend/dist`, `NODE_VERSION=22` for Vite 8, `VITE_API_BASE=https://api.terrasim.rabidahal.com.np`). README gains a "Deploy on Render" section (blueprint flow, custom-domain CNAMEs, free-tier cold-start note).
- **GitHub.** `.github/workflows/ci.yml`: backend job (setup-uv py3.14 → `uv sync --frozen` → `uv run pytest`) + frontend job (Node 22 → `npm ci` → `oxlint` → `tsc --noEmit` → `npm run build`) on push/PR. Issue templates (bug + feature) and a PR template mirror the AGENTS.md definition of done and honesty framing. Removed the accidentally committed `backend/terrasim_backend.egg-info/` from git and ignored `*.egg-info/`.

### Problem
The app only ran locally: CORS hardcoded to localhost, no container/blueprint, Vite 8 would fail on Render's default Node, committed `egg-info` polluted the tree, and the repo had no CI or issue scaffolding.

### Solution
A Render blueprint with a uv-based Docker backend and a static frontend whose build-time `VITE_API_BASE` points at the API service under the custom domain, plus CI and issue/PR templates.

### Result
`uv run pytest` 37 passed. `npm run lint`, `npx tsc --noEmit -p tsconfig.app.json`, `npm run build` pass. Native boot check of the container command: `/api/health` → `{"status":"ok","version":"0.1.0","cities":2}`; CORS preflight + GET with `Origin: https://terrasim.rabidahal.com.np` both return `Access-Control-Allow-Origin: https://terrasim.rabidahal.com.np`. Docker image build not run locally (no Docker daemon on this machine) — Render performs it on deploy.

### Evidence
implementation-log entry (this one); commit + push + created GitHub issues following.

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