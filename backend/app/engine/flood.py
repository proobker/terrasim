"""Terrain-based hypothetical flood extent.

This is deliberately NOT a hydrodynamic model. It computes the set of
raster cells that are (a) connected to a user-supplied source cell and
(b) below a modelled water surface elevation. See plans.md §8.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons


def flood_mask(
    grid: DemGrid,
    source_lng: float,
    source_lat: float,
    level_m: float,
    mode: str = "rise",
) -> tuple[np.ndarray, float | None]:
    """Compute the connected flooded-cell mask.

    Args:
        grid: elevation raster + georeferencing.
        source_lng/source_lat: flood origin (usually a river/water body).
        level_m: either an absolute water-surface elevation (meters above
            sea level) when ``mode == "absolute"``, or a rise above the
            source cell's elevation when ``mode == "rise"``.
        mode: ``"rise"`` or ``"absolute"``.

    Returns:
        (flooded mask, water surface elevation used or None if dry).
    """
    elev = grid.elev
    r0, c0 = grid.cell(source_lng, source_lat)
    if mode == "absolute":
        surface = float(level_m)
    else:
        surface = float(elev[r0, c0]) + float(level_m)

    # A flood origins only where the source cell is below the surface.
    filled = np.zeros_like(elev, dtype=bool)
    if elev[r0, c0] > surface:
        return filled, None

    queue: deque[tuple[int, int]] = deque([(r0, c0)])
    filled[r0, c0] = True
    nrows, ncols = filled.shape
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < nrows and 0 <= nc < ncols and not filled[nr, nc]:
                if elev[nr, nc] <= surface:
                    filled[nr, nc] = True
                    queue.append((nr, nc))
    return filled, surface


def flood_stats(grid: DemGrid, mask: np.ndarray, surface: float) -> dict:
    cells = int(mask.sum())
    area_m2 = cells * grid.cell_area_m2(
        (grid.min_lat + grid.max_lat) / 2.0
    )
    return {
        "cells_flooded": cells,
        "cell_resolution_m": grid.res_lat * 111.32 * 1000,
        "water_surface_m": surface,
        "area_km2": round(area_m2 / 1e6, 3),
        "percent_of_cells": round(100.0 * mask.mean(), 2),
    }


def flood_to_featurecollections(grid: DemGrid, mask: np.ndarray) -> dict:
    """Return rendered flood overlay GeoJSON (downsampled + merged)."""
    polygons = mask_to_polygons(mask, grid)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class": "flood"},
                "geometry": polygon,
            }
            for polygon in polygons
        ],
    }


def run(grid: DemGrid, source_lng: float, source_lat: float, level_m: float, mode: str) -> dict:
    mask, surface = flood_mask(grid, source_lng, source_lat, level_m, mode)
    if surface is None:
        return {
            "dry": True,
            "flooded": {"type": "FeatureCollection", "features": []},
            "stats": {"cells_flooded": 0, "area_km2": 0.0, "percent_of_cells": 0.0},
        }
    layers = flood_to_featurecollections(grid, mask)
    stats = flood_stats(grid, mask, surface)
    return {
        "dry": False,
        "flooded": layers,
        "stats": stats,
    }