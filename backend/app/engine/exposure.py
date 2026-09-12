"""Asset exposure: intersecting infrastructure with simulated hazard layers.

Output is always framed as *estimated exposure* — "N facilities fall within
the estimated high-exposure zone" — never as deterministic damage.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import shape

from app.engine import earthquake
from app.engine.earthquake import quake_zones_at
from app.engine.grid import DemGrid

_BAND_LABELS = {"high": "high", "medium_high": "medium_high", "medium": "medium", "low": "low"}


def _densify(points, step_deg: float):
    out = []
    for a, b in zip(points, points[1:]):
        ax, ay = a
        bx, by = b
        dist = max(abs(bx - ax), abs(by - ay))
        n = max(1, int(dist / step_deg))
        for i in range(n + 1):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    if points:
        out.append(points[-1])
    return out


def _asset_points(geometry: Any, step_deg: float) -> list[tuple[float, float]]:
    geom = shape(geometry) if isinstance(geometry, dict) else geometry
    gtype = geom.geom_type
    if gtype == "Point":
        return [geom.coords[0]]
    if gtype in ("LineString", "MultiLineString"):
        lines = geom.geoms if gtype == "MultiLineString" else [geom]
        pts = []
        for line in lines:
            pts.extend(_densify(list(line.coords), step_deg))
        return pts
    if gtype in ("Polygon", "MultiPolygon"):
        polys = geom.geoms if gtype == "MultiPolygon" else [geom]
        pts = []
        for poly in polys:
            pts.append(poly.representative_point().coords[0])
        return pts
    return []


def evaluate_flood_exposure(
    grid: DemGrid, assets: dict[str, list[dict]], flooded_mask
) -> dict:
    """Classify each asset as flooded/not flooded via the raster cell lookup."""
    step_deg = min(grid.res_lng, grid.res_lat) * 2
    results: dict[str, dict] = {}
    affected_ids: list[dict] = []

    for kind, features in assets.items():
        counts = {"flooded": 0, "total": 0}
        for feature in features:
            counts["total"] += 1
            points = _asset_points(feature.get("geometry"), step_deg)
            at_risk = any(
                flooded_mask[grid.cell(lng, lat)] for lng, lat in points
            )
            if at_risk:
                counts["flooded"] += 1
                affected_ids.append(
                    {
                        "kind": kind,
                        "name": feature.get("properties", {}).get("name"),
                        "id": feature.get("properties", {}).get("id"),
                    }
                )
        results[kind] = counts
    return {"assets": results, "affected": affected_ids}


def evaluate_quake_exposure(
    grid: DemGrid,
    assets: dict[str, list[dict]],
    epicenter_lng: float,
    epicenter_lat: float,
    magnitude: float,
    depth_km: float,
) -> dict:
    """Classify each asset into the highest intensity band at its location."""
    step_deg = min(grid.res_lng, grid.res_lat) * 2
    results: dict[str, dict] = {}
    exposed: list[dict] = []

    for kind, features in assets.items():
        counts: dict[str, int] = {"total": 0}
        for band in earthquake.BANDS:
            counts[band] = 0
        counts["none"] = 0
        for feature in features:
            counts["total"] += 1
            points = _asset_points(feature.get("geometry"), step_deg)
            worst: tuple[int, str | None] = (0, None)
            for lng, lat in points:
                band = None
                b, _ = quake_zones_at(lng, lat, grid, epicenter_lng, epicenter_lat, magnitude, depth_km)
                rank = earthquake.BANDS.index(b) + 1 if b else 0
                if rank > worst[0]:
                    worst = (rank, b)
            band = worst[1] or "none"
            counts[band] += 1
            if band in earthquake.BANDS:
                exposed.append(
                    {
                        "kind": kind,
                        "name": feature.get("properties", {}).get("name"),
                        "id": feature.get("properties", {}).get("id"),
                        "band": band,
                    }
                )
        results[kind] = counts
    return {"assets": results, "exposed": exposed}


def evaluate(grid: DemGrid, assets: dict[str, list[dict]], hazard: dict) -> dict:
    """Dispatch to the right exposure evaluator based on the hazard kind."""
    kind = hazard["kind"]
    if kind == "flood":
        return evaluate_flood_exposure(grid, assets, hazard["mask"])
    if kind == "earthquake":
        return evaluate_quake_exposure(
            grid,
            assets,
            hazard["epicenter_lng"],
            hazard["epicenter_lat"],
            hazard["magnitude"],
            hazard["depth_km"],
        )
    raise ValueError(f"unknown hazard kind: {kind}")