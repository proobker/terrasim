"""terrasim backend API.

FastAPI server hosting the simulation + data layer. Run locally:

    uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, datasets
from app.engine import earthquake, exposure, flood, suitability, terrain_tiles
from app.schemas import EarthquakeScenario, FloodScenario, SuitabilityRequest


def _assets_for(scenario: FloodScenario | EarthquakeScenario) -> dict[str, list[dict]]:
    """Real OSM assets, or the planner's proposed layout when supplied."""
    if scenario.assets is not None:
        assets: dict[str, list[dict]] = {}
        for a in scenario.assets if isinstance(scenario.assets, list) else []:
            assets.setdefault(a.kind, []).append(
                {
                    "type": "Feature",
                    "properties": {"kind": a.kind, "id": a.id, "name": a.name},
                    "geometry": {"type": "Point", "coordinates": [a.lng, a.lat]},
                }
            )
        return assets
    return datasets.load_assets(scenario.city_id)

app = FastAPI(
    title="terrasim",
    version=__version__,
    description="Building Resilient Areas for Climate & Emergencies — scenario-based geospatial decision-support API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "cities": len(datasets.list_cities())}


@app.get("/api/cities")
def cities() -> dict:
    return {"cities": datasets.list_cities()}


@app.get("/api/cities/{city_id}")
def city(city_id: str) -> dict:
    try:
        return datasets.city_meta(city_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/cities/{city_id}/layers/{kind}")
def city_layer(city_id: str, kind: str) -> dict:
    try:
        return datasets.load_layer(city_id, kind)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/cities/{city_id}/terrain/{z}/{x}/{y}.png")
def terrain_tile(city_id: str, z: int, x: int, y: int) -> Response:
    """Terrarium-encoded DEM tile for the 3D terrain layer."""
    try:
        data = terrain_tiles.tile_bytes(city_id, z, x, y)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if data is None:
        raise HTTPException(status_code=404, detail="terrain tile outside DEM coverage")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/cities/{city_id}/rivers")
def city_rivers(city_id: str) -> dict:
    """Lightweight river summaries for hypothesis selection (id/name/type)."""
    rivers = datasets.rivers(city_id)
    if not rivers:
        try:
            datasets.city_meta(city_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"rivers": rivers}


@app.post("/api/simulate/flood")
def simulate_flood(scenario: FloodScenario) -> dict:
    try:
        grid = datasets.load_city_dem(scenario.city_id)
        assets = _assets_for(scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if scenario.river_id is not None:
        geometry = datasets.river_geometry_by_ref(scenario.city_id, scenario.river_id)
        if geometry is None:
            raise HTTPException(status_code=404, detail=f"unknown river: {scenario.river_id}")
        coords = datasets.line_vertices(geometry)
        if not coords:
            raise HTTPException(status_code=400, detail=f"river has no usable geometry: {scenario.river_id}")
        water_features = None
        if scenario.include_tributaries:
            try:
                water_features = datasets.load_layer(scenario.city_id, "water").get("features") or None
            except FileNotFoundError:
                water_features = None
        result = flood.run_river(grid, coords, scenario.level_m, scenario.mode, water_features)
    else:
        assert scenario.source is not None
        result = flood.run(
            grid,
            scenario.source.lng,
            scenario.source.lat,
            scenario.level_m,
            scenario.mode,
        )
    response = {
        "kind": "flood",
        "scenario": scenario.model_dump(),
        "stats": result["stats"],
        "overlay": result["flooded"],
        "dry": result["dry"],
    }
    if not result["dry"]:
        response["exposure"] = exposure.evaluate_flood_exposure(grid, assets, result["mask"])
    return response


@app.post("/api/simulate/earthquake")
def simulate_earthquake(scenario: EarthquakeScenario) -> dict:
    try:
        grid = datasets.load_city_dem(scenario.city_id)
        assets = _assets_for(scenario)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = earthquake.run(
        grid,
        scenario.epicenter.lng,
        scenario.epicenter.lat,
        scenario.magnitude,
        scenario.depth_km,
    )
    hazard = {
        "kind": "earthquake",
        "epicenter_lng": scenario.epicenter.lng,
        "epicenter_lat": scenario.epicenter.lat,
        "magnitude": scenario.magnitude,
        "depth_km": scenario.depth_km,
    }
    zones_features = [
        feature for band_fc in result["zones"].values() for feature in band_fc.get("features", [])
    ]
    return {
        "kind": "earthquake",
        "scenario": scenario.model_dump(),
        "zones": {"type": "FeatureCollection", "features": zones_features},
        "bands": result["bands"],
        "area_km2": result["area_km2"],
        "radii_km": result["radii_km"],
        "exposure": exposure.evaluate(grid, assets, hazard),
    }


@app.post("/api/cities/{city_id}/suitability")
def city_suitability(city_id: str, _body: SuitabilityRequest | None = None) -> dict:
    try:
        grid = datasets.load_city_dem(city_id)
        segments = datasets.road_points(city_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    road_points = [pt for seg in segments for pt in seg]
    if not road_points:
        road_points = None
    return suitability.run(grid, road_points)