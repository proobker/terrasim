"""Geospatial grid utilities shared by the simulation engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping
from shapely.ops import unary_union

# Earth metrics
KM_PER_DEG_LAT = 111.32
METERS_PER_KM = 1000.0


@dataclass(frozen=True)
class DemGrid:
    """A regular elevation raster aligned to geographic lat/lng.

    Row 0 is the southern edge (min_lat); column 0 is the western edge
    (min_lng). Cells index the *southwest corner* of their cell.
    """

    elev: np.ndarray
    min_lng: float
    min_lat: float
    res_lng: float
    res_lat: float

    @property
    def nrows(self) -> int:
        return self.elev.shape[0]

    @property
    def ncols(self) -> int:
        return self.elev.shape[1]

    @property
    def max_lng(self) -> float:
        return self.min_lng + self.ncols * self.res_lng

    @property
    def max_lat(self) -> float:
        return self.min_lat + self.nrows * self.res_lat

    def cell(self, lng: float, lat: float) -> tuple[int, int]:
        c = int((lng - self.min_lng) / self.res_lng)
        r = int((self.max_lat - lat) / self.res_lat)
        r = max(0, min(r, self.nrows - 1))
        c = max(0, min(c, self.ncols - 1))
        return r, c

    def cell_center(self, r: int, c: int) -> tuple[float, float]:
        lng = self.min_lng + (c + 0.5) * self.res_lng
        lat = self.max_lat - (r + 0.5) * self.res_lat
        return lng, lat

    def cell_bbox(self, r: int, c: int) -> tuple[float, float, float, float]:
        x0 = self.min_lng + c * self.res_lng
        x1 = x0 + self.res_lng
        y1 = self.max_lat - r * self.res_lat
        y0 = y1 - self.res_lat
        return x0, y0, x1, y1

    def km_per_deg_lng(self, lat: float | np.ndarray) -> np.ndarray | float:
        return KM_PER_DEG_LAT * np.maximum(np.cos(np.deg2rad(lat)), 0.1)

    def cell_area_m2(self, lat: float) -> float:
        w_m = self.res_lng * self.km_per_deg_lng(lat) * METERS_PER_KM
        h_m = self.res_lat * KM_PER_DEG_LAT * METERS_PER_KM
        return w_m * h_m


def load_dem(city_dir: Path) -> DemGrid:
    """Load the cached elevation raster + georeferencing for a city bundle."""
    with (city_dir / "dem.meta.json").open("r", encoding="utf-8") as fh:
        meta = json.load(fh)
    array = np.load(city_dir / "dem.npz")["elev"].astype(np.float32)
    return DemGrid(
        elev=array,
        min_lng=float(meta["min_lng"]),
        min_lat=float(meta["min_lat"]),
        res_lng=float(meta["res_lng"]),
        res_lat=float(meta["res_lat"]),
    )


def downsample_mask(mask: np.ndarray, max_cells: int = 96) -> tuple[np.ndarray, int]:
    """Return a downsampled boolean mask (and its factor) for display rendering.

    A cell in the coarse mask is True when any underlying cell is True.
    """
    h, w = mask.shape
    factor = max(1, -(-max(h, w) // max_cells))
    if factor == 1:
        return mask, 1
    hc = -(-h // factor)
    wc = -(-w // factor)
    padded = np.zeros((hc * factor, wc * factor), dtype=bool)
    padded[:h, :w] = mask
    coarse = padded.reshape(hc, factor, wc, factor).any(axis=(1, 3))
    return coarse, factor


def mask_to_polygons(
    mask: np.ndarray,
    grid: DemGrid,
    max_cells: int = 96,
    simplify: bool = True,
) -> list[dict]:
    """Convert a boolean raster mask into a list of GeoJSON polygons.

    The mask is downsampled for display, neighbouring cells are merged with
    a unary union, and small holes/slivers are removed via simplification.
    """
    coarse, factor = downsample_mask(mask, max_cells)
    cells = np.argwhere(coarse)
    polys = [
        box(*grid.cell_bbox(r * factor, c * factor))
        for r, c in cells
    ]
    merged = unary_union(polys)
    if merged.is_empty:
        return []
    if simplify:
        tol = max(grid.res_lng, grid.res_lat) * factor * 0.5
        merged = merged.simplify(tol, preserve_topology=True)
    shapes = merged.geoms if merged.geom_type in ("MultiPolygon", "GeometryCollection") else [merged]
    features = []
    for shape in shapes:
        if shape.is_empty:
            continue
        # skip below one coarse cell of area to avoid specks
        features.append(mapping(shape))
    return features