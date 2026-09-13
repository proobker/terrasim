flowchart TD
    subgraph Data["data/bundles/<city>/"]
        CJ["city.json (meta, bounds, valley_cap)"]
        DEM["dem.npz + meta (elevation grid)"]
        GEO["*.geojson: buildings / roads / facilities / water / rim"]
    end

    subgraph FE["Frontend (React + MapLibre)"]
        Store["zustand store (source, params, placed assets, result)"]
        Map["MapView: layers, terrain tiles, overlays"]
        Panel["SidePanel: scenario controls / planner"]
        Exposure["ExposurePanel: stats + per-asset verdicts"]
        Hook["useSimulate / useRivers / useSuitability"]
        Api["api.ts fetch layer"]
    end

    subgraph BE["Backend (FastAPI)"]
        route["/api/cities/*, /api/simulate/*, /suitability"]
        assets["_assets_for(): real OSM or planner override"]
        engine["pure engine: grid / flood / earthquake / suitability / exposure"]
    end

    Boot((Boot)) --> Api -->|GET /api/cities| route
    route -->|city.json| CJ
    CJ --> Map

    Panel --> Store
    Map -->|tap source / epicenter / draw river / place asset| Store
    Store --> Hook

    Hook -->|"POST /api/simulate/flood | earthquake (scenario + assets)"| route
    route --> assets --> engine
    route -->|"POST suitability"| engine
    route -->|"GET rivers / terrain / layers"| GEO
    engine -->|"DEM grid"| DEM
    engine -->|"flooded/zone overlays, stats, exposure"| route
    route -->|GeoJSON result| Api
    Api --> Store
    Store --> Map
    Store --> Exposure
Summary of the loop:
- Sources: city bundles (DEM + OSM GeoJSON) are the single truth; the backend never fetches live data.
- Request: useSimulate POSTs a scenario; in new-city mode the placed assets override real OSM assets (_assets_for).
- Compute: all physics in backend/app/engine/ (pure, no I/O); overlays return as GeoJSON.
- Render: setResult → MapView renders bands, ExposurePanel renders verdicts.
Want me to write this into a file in the repo (e.g. docs/dataflow.md), or adjust the level of detail?