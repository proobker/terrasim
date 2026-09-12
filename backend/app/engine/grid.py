"""Geospatial grid utilities shared by the simulation engine."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping
from shapely.ops import unary_union

_NEIGH4 = ((-1, 0), (1, 0), (0, -1), (0, 1))

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


def _label_components(fill: np.ndarray) -> tuple[np.ndarray, int]:
    """Label 4-connected components of a boolean mask (row-major BFS)."""
    h, w = fill.shape
    labels = np.zeros((h, w), dtype=np.int32)
    seen = np.zeros((h, w), dtype=bool)
    label = 0
    queue: deque[tuple[int, int]] = deque()
    for r0 in range(h):
        for c0 in range(w):
            if not fill[r0, c0] or seen[r0, c0]:
                continue
            label += 1
            seen[r0, c0] = True
            labels[r0, c0] = label
            queue.append((r0, c0))
            while queue:
                r, c = queue.popleft()
                for dr, dc in _NEIGH4:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < h and 0 <= nc < w and fill[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        labels[nr, nc] = label
                        queue.append((nr, nc))
    return labels, label


def clean_mask(mask: np.ndarray, min_keep: int = 4, fill_hole: int = 8) -> np.ndarray:
    """Drop specks smaller than ``min_keep`` cells and fill small enclosed
    holes smaller than ``fill_hole`` cells. Operates on the display mask, so
    the remaining features are continuous rather than stippled with noise."""
    m = np.asarray(mask, dtype=bool).copy()
    labels, count = _label_components(m)
    if count:
        sizes = np.bincount(labels.ravel())
        for lab in np.flatnonzero(sizes < min_keep):
            m[labels == lab] = False
    bg = ~m
    blabels, bcount = _label_components(bg)
    if bcount:
        bsizes = np.bincount(blabels.ravel())
        edge = np.concatenate(
            (blabels[0, :], blabels[-1, :], blabels[:, 0], blabels[:, -1])
        )
        boundary = set(np.unique(edge).tolist())
        for lab in np.flatnonzero(bsizes < fill_hole):
            if int(lab) and int(lab) not in boundary:
                m[blabels == lab] = True
    return m


def _strip_boxes(coarse: np.ndarray, factor: int, grid: DemGrid) -> list:
    """Build one bounding box per contiguous horizontal run of cells.

    This keeps the polygon count proportional to the number of *runs*
    (dozens, not per-cell tens-of-thousands), so unary_union stays cheap
    even at high display resolution.
    """
    boxes = []
    for r in range(coarse.shape[0]):
        row = np.flatnonzero(coarse[r])
        if row.size == 0:
            continue
        lat1 = grid.max_lat - r * factor * grid.res_lat
        lat0 = lat1 - factor * grid.res_lat
        start = int(row[0])
        prev = start
        for c in row[1:].tolist():
            if c == prev + 1:
                prev = c
                continue
            boxes.append(
                box(
                    grid.min_lng + start * factor * grid.res_lng,
                    lat0,
                    grid.min_lng + (prev + 1) * factor * grid.res_lng,
                    lat1,
                )
            )
            start = prev = c
        boxes.append(
            box(
                grid.min_lng + start * factor * grid.res_lng,
                lat0,
                grid.min_lng + (prev + 1) * factor * grid.res_lng,
                lat1,
            )
        )
    return boxes


def mask_to_polygons(
    mask: np.ndarray,
    grid: DemGrid,
    max_cells: int = 512,
    clean: bool = True,
    min_keep: int = 4,
    fill_hole: int = 8,
    simplify_tol: float | None = None,
) -> list[dict]:
    """Convert a boolean raster mask into a list of GeoJSON polygons.

    The mask is downsampled for display, cleaned of specks/holes, merged into
    polygons (one box per contiguous cell run before the union), then gently
    simplified so water/intensity zones read as continuous areas rather than
    stitched rectangles or slivers.
    """
    coarse, factor = downsample_mask(mask, max_cells)
    if clean:
        coarse = clean_mask(coarse, min_keep=min_keep, fill_hole=fill_hole)
    if not coarse.any():
        return []
    boxes = _strip_boxes(coarse, factor, grid)
    merged = unary_union(boxes)
    if merged.is_empty:
        return []
    if simplify_tol is None:
        simplify_tol = max(grid.res_lng, grid.res_lat) * factor * 0.5
    merged = merged.simplify(simplify_tol, preserve_topology=True)
    shapes = (
        merged.geoms
        if merged.geom_type in ("MultiPolygon", "GeometryCollection")
        else [merged]
    )
    features = []
    for shape in shapes:
        if shape.is_empty:
            continue
        features.append(mapping(shape))
    return features