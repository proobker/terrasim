"""Asset exposure: intersecting infrastructure with simulated hazard layers.

Output is always framed as *estimated exposure* — "N facilities fall within
the estimated high-exposure zone" — never as deterministic damage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from shapely.geometry import shape

from app.engine import earthquake
from app.engine.earthquake import quake_zones_at
from app.engine.grid import DemGrid

_BAND_LABELS = {"high": "high", "medium_high": "medium_high", "medium": "medium", "low": "low"}


@dataclass(frozen=True)
class PointAssets:
    """Many assets held as arrays (a city's buildings, or its roads).

    Exposure classifies them in one numpy pass instead of one dict per asset
    — results match the per-feature path exactly, in the same order.

    By default each asset is one point. With ``starts`` (CSR offsets, length
    n_assets + 1, no empty segment) asset ``i`` owns the sample points
    ``starts[i]:starts[i+1]`` — a road densified along its length.
    """

    kind: str
    lng: np.ndarray
    lat: np.ndarray
    ids: np.ndarray  # int; negative means "positional": f"{kind}:{index}"
    name_table: np.ndarray
    name_idx: np.ndarray
    starts: np.ndarray | None = None

    def __len__(self) -> int:
        return int(self.ids.size)

    def per_asset(self, values: np.ndarray, ufunc: np.ufunc) -> np.ndarray:
        """Reduce per-point ``values`` to one value per asset with ``ufunc``."""
        if self.starts is None:
            return values
        return ufunc.reduceat(values, self.starts[:-1])

    def id_at(self, i: int) -> Any:
        fid = int(self.ids[i])
        return fid if fid >= 0 else f"{self.kind}:{i}"

    def name_at(self, i: int) -> str | None:
        return str(self.name_table[self.name_idx[i]]) or None


def _cells(grid: DemGrid, lng: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ``DemGrid.cell`` (same truncation + clamping)."""
    c = ((lng - grid.min_lng) / grid.res_lng).astype(np.int64)
    r = ((grid.max_lat - lat) / grid.res_lat).astype(np.int64)
    return np.clip(r, 0, grid.nrows - 1), np.clip(c, 0, grid.ncols - 1)


def _quake_band_index(
    grid: DemGrid, pa: PointAssets, epicenter_lng: float, epicenter_lat: float, magnitude: float, depth_km: float
) -> np.ndarray:
    """Index into ``earthquake.BANDS`` per asset; ``len(BANDS)`` means none.

    Vectorised ``quake_zones_at`` + ``band_for``.
    """
    r = np.sqrt(
        ((pa.lng - epicenter_lng) * grid.km_per_deg_lng(pa.lat)) ** 2
        + ((pa.lat - epicenter_lat) * 111.32) ** 2
    )
    index = earthquake.intensity_index(r, depth_km, magnitude)
    band = np.full(index.shape, len(earthquake.BANDS), dtype=np.int64)
    for i in reversed(range(len(earthquake.BANDS))):
        band[index >= earthquake.BAND_THRESHOLDS[i]] = i
    return band


def line_assets(kind: str, features: list[dict], step_deg: float) -> PointAssets:
    """Line features (roads) as a multi-point :class:`PointAssets`, sampled
    exactly like the per-feature path (``_asset_points``)."""
    lng: list[float] = []
    lat: list[float] = []
    starts = [0]
    ids: list[int] = []
    names: list[str] = []
    for feature in features:
        pts = _asset_points(feature, step_deg) if feature.get("geometry") else []
        if not pts:
            continue
        for x, y in pts:
            lng.append(x)
            lat.append(y)
        starts.append(len(lng))
        props = feature.get("properties") or {}
        fid = props.get("id")
        ids.append(fid if isinstance(fid, int) and fid >= 0 else -1)
        names.append(str(props.get("name") or ""))
    name_table, name_idx = np.unique(np.asarray(names, dtype=str), return_inverse=True)
    return PointAssets(
        kind,
        np.asarray(lng, dtype=np.float64),
        np.asarray(lat, dtype=np.float64),
        np.asarray(ids, dtype=np.int64),
        name_table,
        name_idx.astype(np.int32),
        np.asarray(starts, dtype=np.int64),
    )


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


def _asset_points(feature: dict, step_deg: float) -> list[tuple[float, float]]:
    geometry = feature.get("geometry")
    # Fast path: the PBF extractor pre-computes a bbox centroid, so exposure
    # on huge building sets never materialises a Shapely polygon per asset.
    # ``load_assets`` flattens the centroid into the asset dict; raw GeoJSON
    # features with a ``properties.centroid`` also work.
    props = feature.get("properties") or {}
    centroid = feature.get("centroid") or props.get("centroid")
    if geometry and geometry.get("type") == "Polygon" and isinstance(centroid, (list, tuple)) and len(centroid) == 2:
        return [tuple(centroid)]
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
    grid: DemGrid, assets: dict[str, list[dict] | PointAssets], flooded_mask
) -> dict:
    """Classify each asset as flooded/not flooded via the raster cell lookup."""
    step_deg = min(grid.res_lng, grid.res_lat) * 2
    results: dict[str, dict] = {}
    affected_ids: list[dict] = []

    for kind, features in assets.items():
        if isinstance(features, PointAssets):
            hit = features.per_asset(
                flooded_mask[_cells(grid, features.lng, features.lat)], np.logical_or
            )
            results[kind] = {"flooded": int(hit.sum()), "total": len(features)}
            affected_ids.extend(
                {"kind": kind, "name": features.name_at(i), "id": features.id_at(i)}
                for i in np.flatnonzero(hit).tolist()
            )
            continue
        counts = {"flooded": 0, "total": 0}
        for feature in features:
            counts["total"] += 1
            points = _asset_points(feature, step_deg)
            at_risk = any(
                flooded_mask[grid.cell(lng, lat)] for lng, lat in points
            )
            if at_risk:
                counts["flooded"] += 1
                props = feature.get("properties") or {}
                affected_ids.append(
                    {
                        "kind": kind,
                        "name": feature.get("name") or props.get("name"),
                        "id": feature.get("id") or props.get("id"),
                    }
                )
        results[kind] = counts
    return {"assets": results, "affected": affected_ids}


def evaluate_quake_exposure(
    grid: DemGrid,
    assets: dict[str, list[dict] | PointAssets],
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
        if isinstance(features, PointAssets):
            # A lower BANDS index is more severe: a road takes its worst point.
            band_i = features.per_asset(
                _quake_band_index(grid, features, epicenter_lng, epicenter_lat, magnitude, depth_km),
                np.minimum,
            )
            tally = np.bincount(band_i, minlength=len(earthquake.BANDS) + 1)
            counts["total"] = len(features)
            for i, band in enumerate(earthquake.BANDS):
                counts[band] = int(tally[i])
            counts["none"] = int(tally[-1])
            for i in np.flatnonzero(band_i < len(earthquake.BANDS)).tolist():
                band = earthquake.BANDS[band_i[i]]
                if kind == "buildings":
                    exposed.append({"id": features.id_at(i), "band": band})
                else:
                    exposed.append(
                        {"kind": kind, "name": features.name_at(i), "id": features.id_at(i), "band": band}
                    )
            results[kind] = counts
            continue
        for feature in features:
            counts["total"] += 1
            points = _asset_points(feature, step_deg)
            # Most severe band across the asset's points (BANDS is ordered
            # high -> low, so the smallest index wins).
            worst: int | None = None
            for lng, lat in points:
                b, _ = quake_zones_at(lng, lat, grid, epicenter_lng, epicenter_lat, magnitude, depth_km)
                if b is not None:
                    i = earthquake.BANDS.index(b)
                    worst = i if worst is None else min(worst, i)
            band = earthquake.BANDS[worst] if worst is not None else "none"
            counts[band] += 1
            if band in earthquake.BANDS:
                if kind == "buildings":
                    # Thousands of buildings carry bands; the frontend tints
                    # by id only, so keep the payload compact for them.
                    exposed.append({"id": feature["id"], "band": band})
                else:
                    props = feature.get("properties") or {}
                    exposed.append(
                        {
                            "kind": kind,
                            "name": feature.get("name") or props.get("name"),
                            "id": feature.get("id") or props.get("id"),
                            "band": band,
                        }
                    )
        results[kind] = counts
    return {"assets": results, "exposed": exposed}


def evaluate(grid: DemGrid, assets: dict[str, list[dict] | PointAssets], hazard: dict) -> dict:
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