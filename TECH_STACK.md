# terrasim — Tech Stack for Laypeople

> What terrasim is built from, how the pieces talk to each other, and what the
> "methods" actually do — in plain English. Written for non-engineers who want
> to understand the machine, and for engineers who want one place to look.
>
> Last updated 2026-09-13 — matches the current tree.

---

## 1. The one-paragraph version

terrasim is a website (frontend) that talks to a small server (backend). The
server holds offline map data for demo cities and runs the actual simulations
when you click "Run". The website draws the maps, the flooded areas, the quake
zones and the little pixel-art icons, while the server does the math. The math
is built around a grid of elevation values (a **DEM** — Digital Elevation
Model, i.e. "how high is the ground at every square metre"), because nearly
every question terrasim answers — will water pool here? will the ground shake?
is this land safe to build on? — is really a question about terrain shape.

---

## 2. The two halves

```
terrasim/
├── backend/            Python "server side" — simulation + data API
│   └── app/
│       ├── main.py         the web API (FastAPI routes)
│       ├── schemas.py      the shapes of requests/responses (Pydantic)
│       ├── datasets.py     loads the offline city data bundles
│       └── engine/         the actual science lives here
│           ├── grid.py         1 shared elevation-grid toolbox
│           ├── flood.py        flow-routed, volume-conserving flood engine
│           ├── earthquake.py   simplified quake intensity model
│           ├── suitability.py  "green/yellow/red" land scoring
│           ├── exposure.py     does each building get wet / shaken?
│           └── terrain_tiles.py serves elevation tiles to the map
├── frontend/           TypeScript "website" — the part you see
│   └── src/
│       ├── MapView.tsx      the interactive map (MapLibre GL)
│       ├── SidePanel.tsx    the control panel (Scenario Lab / Land Planning)
│       ├── ExposurePanel.tsx  results + per-building verdicts
│       ├── store.ts         shared app state (zustand)
│       ├── useSimulate.ts   "talking to the API" helpers
│       ├── api.ts           the list of server endpoints the site calls
│       ├── buildings3d.ts   toy 3D city blocks
│       └── pixelIcons.ts    hand-drawn pixel sprites, generated in code
├── scripts/fetch_data.py The "data factory" — downloads + cleans map data
├── data/bundles/        the offline city data files shipped with the repo
└── plans.md             the master spec (read this for "why")
```

---

## 3. Frontend: what makes the screen work

| Piece | What it is | Plain-English job |
| --- | --- | --- |
| **React 19** | UI library (TypeScript) | Builds the panels, buttons and results boxes; re-renders them when state changes. |
| **Vite** | Build tool + dev server | Compiles the frontend code fast during development; produces the final production build. |
| **TypeScript** | A typed layer over JavaScript | Catches mistakes before the app runs ("this button expects a number, you passed text"). |
| **MapLibre GL** | The map engine (WebGL) | Renders the real map, the terrain, the flood/quakes overlays and the 3D blocks in the browser. |
| **zustand** | Tiny state store | One shared "memory" the whole app reads (`store.ts`) so the map, the panel and the results always agree about the current scenario. |
| **Canvas + pixel sprites** | Hand-rolled, no image files | `pixelIcons.ts` draws small pixel-art icons (river, fire station, hospital…) into a sprite atlas at load time — Pokemon FireRed-flavoured chrome without shipping a single image asset. |
| **fill-extrusion layers** | MapLibre 3D building feature | `buildings3d.ts` turns each real OSM building **footprint** into a stylised 3D extrusion whose height is *estimated* from OSM tags (`height`, `building:levels`) or a type guess (clamped 3–60 m). Planned (New City) facilities draw as synthetic squares. |
| **raster-dem + terrain** | 3D ground surface | `MapView.tsx` feeds the DEM to MapLibre's `terrain` mode with **Terrarium** encoding, so the ground itself is bumpy. |
| **oxlint** | Linter | Nags about code smells and style in the frontend. |

Frontend talks to backend over plain HTTP `fetch` (`api.ts`) — every request is
a URL + JSON body, and the base address is `VITE_API_BASE`
(`http://127.0.0.1:8000` by default).

---

## 4. Backend: what does the thinking

| Piece | What it is | Plain-English job |
| --- | --- | --- |
| **Python 3.14** | Programming language | The workhorse language for the simulation. |
| **FastAPI** | Web framework | Turns Python functions into HTTP endpoints the website can call. |
| **uvicorn** | Server runner | The little process that actually listens on the network port and delivers requests to FastAPI. |
| **Pydantic** | Validation library | Declares the exact JSON shape of every request/response (`schemas.py`) and rejects nonsense input ("level_m: -500" is refused). |
| **NumPy** | Number-crunching arrays | Does nearly all simulation math as large tables of numbers instead of slow loops — the entire flood model is array operations. |
| **Shapely** | Geometry library | Turns flood/quake masks into clean GeoJSON polygons and merges boxes (used for the valley rim, hazard overlays). |
| **httpx** | HTTP client | Used by the test suite to call the API and check it works. |
| **pytest** | Test runner | Automatically checks the math (fast, offline) and the API (needs data bundles). |
| **Pillow (dev only)** | Image library | Only used in `scripts/fetch_data.py` to decode the downloaded elevation PNG tiles into numbers. |

Special dependencies: **none**. The server deliberately ships without a
database or a heavyweight geospatial stack — everything it needs is pre-baked
into the offline bundles and loaded from `.geojson`/`.npz` files (`datasets.py`).

---

## 5. The API — every endpoint, in plain English

All under `http://127.0.0.1:8000`. A **POST** takes a JSON "scenario" from the
site and returns results; a **GET** returns data.

| Method | Endpoint | What you get |
| --- | --- | --- |
| GET | `/api/health` | "Am I alive?", version, how many cities are bundled. |
| GET | `/api/cities` | List of demo areas (Kathmandu, Pokhara). |
| GET | `/api/cities/{id}` | Metadata for one city (`bounds`, `hazard_bounds`, `valley_cap_m`, grid size, attribution). |
| GET | `/api/cities/{id}/layers/{kind}` | Buildings / roads / facilities / water / rim as GeoJSON. |
| GET | `/api/cities/{id}/terrain/{z}/{x}/{y}.png` | One elevation tile image (Terrarium-encoded) for the map's 3D terrain — served as regular PNGs with a long cache lifetime. |
| GET | `/api/cities/{id}/rivers` | The pickable rivers (id, name, type) for choosing a flood source. |
| POST | `/api/simulate/flood` | Flood scenario → flooded-area GeoJSON + stats + which assets are estimated to be affected. |
| POST | `/api/simulate/earthquake` | Quake scenario → intensity-band zones + stats + asset exposure. |
| POST | `/api/cities/{id}/suitability` | New-city land scoring → green/yellow/red polygons + areas. |

### Flood request (what you send)

```json
{
  "city_id": "kathmandu",
  "river_id": "sr-bishnumati" | "source": {"lng": ..., "lat": ...} | "river_path": [{"lng": ..., "lat": ...}, ...],
  "level_m": 2.0,
  "mode": "rise",
  "include_tributaries": true,
  "assets": null | [{"kind": "hospital", "id": "...", "name": "...", "lng": ..., "lat": ...}]
}
```

- `river_id` floods along a river's downhill flow path; `source` floods from a
  tapped point; `river_path` floods along a planner-drawn channel (New City
  mode). Exactly one of the three is required (Pydantic enforces it).
- `level_m` is a **hypothetical rise in metres** above the river's channel —
  converted internally into a volume of water, never treated as a "real"
  measured flood depth.
- `assets` lets a planner's proposed hospitals/schools replace the real OSM
  buildings when stress-testing a new layout.

### Flood response highlights

`stats` (all rounded for display): flooded area in km², cells flooded, max/mean
depth, deep-core area, **routed volume (m³)**, number of tributaries fed in,
simulation steps, simulated hours, peak discharge rate; plus a `dry: true`
flag when nothing floods and `overlay` (flood/flood-deep GeoJSON) and
`exposure` (per-kind flooded/total counts + list of affected asset ids).

---

## 6. The star of the flood simulation: the flow-routed engine

`backend/app/engine/flood.py` — this is the feature `feat/flow-routed-flood`
introduces. Understand these terms and you understand the branch:

- **D8 flow direction.** Every grid cell has up to 8 neighbours (the 8 compass
  directions). The engine looks at the elevation in each; whichever neighbour
  is *steepest down* is "downhill", and water is assumed to want to go there.
  This produces a **flow network** covering the whole terrain (`_d8_flow_dir`).
  Cells with no downhill neighbour (pits, plateaus) are *sinks* — water stays
  and ponds.
- **Flow accumulation.** Counts how many cells drain *through* each cell — a
  proxy for "how much river is up there". Rises on a big basin carry more
  water (`_flow_accumulation`).
- **Upstream catchment.** For a chosen river, which cells eventually drain into
  it, and how far (in flow-steps) they are from the channel. Used to **lag**
  tributary inflows — a side-creek's flood arrives later because its water has
  to travel to the main river first (`_upstream_catchment`).
- **Volume conservation.** A `rise_m` is converted into a fixed volume of water
  (`length of reach × assumed inundation width × rise`). Tributary reaches add
  half-volume (`_TRIBUTARY_FACTOR = 0.5`). The routing step can only *move*
  water, never create or destroy it — so the flood paints *until the water
  runs out* instead of flooding the whole valley hypothetically.
- **Transient wave / hydrograph.** Water isn't released all at once. It's
  injected over simulated time in a **triangular hydrograph** (peaks early,
  decays — the way real flood waves behave). Upstream cells flood first,
  downstream later. The reported map is the *peak* state over the whole
  simulation.
- **Flux routing.** Each timestep moves water into lower-or-flooded neighbours
  proportionally to the "head" (height difference) but capped so a cell can
  never export more than it holds (`_flux_ca_step`) — that cap is what keeps
  the math stable and the volume conserved.
- **Flux domain.** The wave is only simulated inside the valley area it can
  actually reach (the river's upstream basin + downstream flow network plus a
  small margin), so run time stays proportional to the valley, not the whole
  grid.

**Honest caveats (kept explicit on purpose):** no rainfall-runoff, no
evaporation, no infiltration, no channel cross-sections, no hydraulic
structures, no erosion, no real velocities. It is a *terrain-based hypothetical
flood extent* — the UI always says "estimated", never "predicted".

Two modes of the same engine: `rise` (add a rise above the river and convert it
to volume) and `absolute` (flood everything below a given height above sea
level).

---

## 7. The other engines

### Earthquake (`earthquake.py`)
A deliberately simple, documented formula instead of real seismology:
`intensity = (M/6)² × (8 / (8 + 3D distance))^1.5`. 3D distance = horizontal km
to the epicentre combined with the stated depth. Every cell is painted into one
of four **relative** intensity bands (high/medium_high/medium/low) — always
described as *estimated relative zones*, never "will collapse". When a city has
a valley rim, the rings are clipped to the valley floor so they trace the real
bowl instead of perfect circles.

### Suitability (`suitability.py`)
Scores every cell 0..1 for "how reasonable is it to build here", as a blend:
52% low-elevation-flood-avoidance + 38% knowing how steep there (flatter=safer)
+ a 10% road-accessbonus. Score ≥ 0.60 → **green**, ≤ 0.42 → **red**, else
**yellow**. It is a *relative planning aid*, not a safety guarantee.

### Exposure (`exposure.py`)
Takes the simulated hazard and asks, for every building/road/facility: "is this
asset inside the estimated hazard footprint?" Line and polygon assets get
sampled at several points along their length so a long road crossing a flood
edge is caught properly.

### Terrain tiles (`terrain_tiles.py`)
Slices the DEM into standard map tiles, encodes each as a **Terrarium** RGB PNG
(elevation hidden in the red/green/blue channels:
`elev = R×256 + G + B/256 − 32768`), and serves them so MapLibre can draw 3D
ground. Written with zero dependencies (hand-rolled PNG writer) so the runtime
server doesn't need Pillow.

---

## 8. Where the data comes from (the pipeline)

`scripts/fetch_data.py` is the "data factory" that produces the offline bundles
in `data/bundles/<city>/`. It is run once per city (`--city kathmandu` or
`--all`); the website never downloads anything live.

1. **OpenStreetMap** — buildings for Kathmandu are extracted from a cached
   **GeoFabrik PBF** extract (`nepal-latest.osm.pbf`, offline, ring-bbox
   overlap); all other cities query the **Overpass API** for buildings, roads,
   facilities and waterways for a city box, split into small chunks because big
   queries make the free mirrors choke. Three mirrors are tried in a fixed
   healthy-first order (mail.ru → kumi.systems → overpass-api.de), once each,
   with quiet backoff ("tolerant pass" — a failed chunk is skipped, never
   retried hot).
2. **Elevation from the Mapzen "Terrarium" tiles** (Copernicus/SRTM-derived).
   A few PNG tiles covering the city are decoded, stitched, and resampled
   (bilinear) onto a regular lat/lng grid at ~30–33 m per cell.
3. **Cleaning.** Buildings under a minimum footprint (40 m²) are dropped; the
   biggest are kept (fetch target up to 4500 per city). Roads are
   forced to stay lines. Facilities are queried per amenity type so one failure
   can't stall the whole bundle.
4. **Water normalisation.** OSM rivers come back chopped
   into hundreds of fragments with mismatched spellings ("Seti", "सेती", gaps
   of kilometres). The script merges fragments of the same physical river using
   a bundled **union–find** algorithm on snap-connectivity (fragments whose
   ends touch), same-stem gaps of up to 20 km for same-named rivers, fuzzy name
   matching (Devanagari-to-Latin transliteration folds like `chh→ch`) and
   family separation (canals never absorb rivers). Output is a handful of
   coherent `MultiLineString` waterways — exactly what makes river-based flood
   seeding work. `--normalize-water` re-runs just this step offline on the
   committed bundles.
5. **Valley rim.** When a city defines a `valley_cap_m`, the cells below that
   height form the "valley bowl". Shapely merges them and the outline is
   emitted as `rim.geojson` — *only* when it is a genuine ring. Open basins
   (the valley spilling off the map edge) are rejected, and the site hides the
   "Valley rim" toggle rather than fake a line. The frontend also clips hazard
   overlays to the real valley shape instead of a rectangle.

**Bundle contents per city:** `city.json`, `dem.meta.json` + `dem.npz`,
`buildings.geojson`, `roads.geojson`, `facilities.geojson`, `water.geojson`,
optionally `rim.geojson`.

**Licensing:** map data © OpenStreetMap contributors (ODbL); elevation is
Copernicus DEM (modified Copernicus Sentinel data) / SRTM, served as Mapzen
Terrarium tiles.

---

## 9. How the frontend renders a simulation

1. You pick a city → the site fetches its layers (GeoJSON) and shows roads,
   buildings (with `~N m est.` hover height) and facilities.
2. You pick a hazard and origin (tap the map, pick a river from a dropdown —
   the selected river lights up with pixel-art arrows `→` showing the flow
   direction — or, in New City mode, **draw a channel** across the land
   yourself). Housing and facilities can be dropped one at a time or stamped
   as a 2×2…5×5 pocket.
3. "Run" → `useSimulate.ts` POSTs the scenario → the server returns GeoJSON
   overlays → MapView adds them as live layers:
   - flood = water polygons with a darker **deep core** band;
   - quake = concentric colour rings plus an animated pulse halo around the
     epicentre (a `requestAnimationFrame` loop, radius/opacity animated);
   - suitability = green/yellow/red patches.
4. `ExposurePanel` shows the headline numbers (km² estimated, m³ routed,
   tributaries) and per-asset verdicts, always phrased as *estimated /
   scenario-based / relative* — never predictive.

Key checkboxes the site carries in `store.ts`: 3D terrain, blocky 3D buildings,
valley rim, roads, facilities, suitability, drawn river.

---

## 10. How correctness is checked

- `cd backend && uv run pytest` — backend: fast engine tests (no network) +
  API tests (needs bundles).
- `cd frontend && npx tsc --noEmit -p tsconfig.app.json` — typecheck.
- `cd frontend && npm run build` — typecheck + production build.

---

## 11. Glossary of the nerdy words, in one breath

- **DEM** — a giant table of "ground height here".
- **GeoJSON** — a text format for describing map shapes (points, lines,
  polygons).
- **Terrarium encoding** — packing elevation numbers into the red/green/blue of
  a PNG so map engines can read "height" from an ordinary image.
- **D8** — "pick the steepest of my 8 neighbours as downhill".
- **Flow accumulation** — "how many cells dump water into me".
- **Catchment / basin / watershed** — "the land whose rain eventually reaches
  this river".
- **Hydrograph** — "how much water is arriving over time" (here: a triangle).
- **Table / run-length → union** — the trick used to merge noisy map fragments
  into one river without a fancy database.
- **Exposure** — "is this thing sitting inside the estimated hazard area?"
  (never "will it be destroyed").
- **Simulation** — what terrasim calls **scenario-based hypothetical
  estimates**; the honest word is always in the UI.