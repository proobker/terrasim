"""Terrain-based hypothetical flood extent.

This is deliberately NOT a hydrodynamic model. It computes the set of
raster cells that are (a) connected to a user-supplied source (a clicked
cell or a whole river channel) and (b) below a modelled water surface
elevation. See plans.md §8.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons


def _flood_fill(elev: np.ndarray, seed: np.ndarray, surface: float) -> np.ndarray:
    """4-connected fill of cells at or below ``surface`` starting from seeds."""
    fill = np.zeros_like(elev, dtype=bool)
    queue: deque[tuple[int, int]] = deque()
    for r, c in np.argwhere(seed):
        if elev[r, c] <= surface:
            fill[r, c] = True
            queue.append((int(r), int(c)))
    nrows, ncols = fill.shape
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < nrows and 0 <= nc < ncols and not fill[nr, nc]:
                if elev[nr, nc] <= surface:
                    fill[nr, nc] = True
                    queue.append((nr, nc))
    return fill


def flood_mask(
    grid: DemGrid,
    source_lng: float,
    source_lat: float,
    level_m: float,
    mode: str = "rise",
) -> tuple[np.ndarray, float | None]:
    """Compute the connected flooded-cell mask from a clicked source cell.

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
    if elev[r0, c0] > surface:
        return np.zeros_like(elev, dtype=bool), None

    seed = np.zeros_like(elev, dtype=bool)
    seed[r0, c0] = True
    return _flood_fill(elev, seed, surface), surface


def river_flood_mask(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
) -> tuple[np.ndarray, float | None]:
    """Compute the connected flooded-cell mask seeded along a river channel.

    Every vertex of the river line becomes a flood seed, so the modelled
    water rises out of the whole channel rather than a single clicked cell.
    For ``mode == "rise"`` the water surface is the river's lowest channel
    cell plus ``level_m`` (i.e. the river is hypothesized to rise by that
    many meters); for ``"absolute"`` it is ``level_m`` meters above sea
    level. As with the point flood, the surface is flat (not a sloped
    river profile) — a deliberate simplification, see plans.md §8.

    Args:
        grid: elevation raster + georeferencing.
        coords: river line vertices as ``(lng, lat)`` pairs.
        level_m: absolute water-surface elevation (meters above sea level)
            when ``mode == "absolute"``, or the hypothesized rise in meters
            above the river's lowest channel cell when ``mode == "rise"``.
        mode: ``"rise"`` or ``"absolute"``.

    Returns:
        (flooded mask, water surface elevation used or None if no river
        cell falls inside the DEM coverage).
    """
    elev = grid.elev
    seed = np.zeros_like(elev, dtype=bool)
    for lng, lat in coords:
        r, c = grid.cell(lng, lat)
        seed[r, c] = True
    if not seed.any():
        return seed, None

    if mode == "absolute":
        surface = float(level_m)
    else:
        # The river's own water level is its lowest channel cell; a requested
        # river height of X meters raises that level by exactly X.
        surface = float(elev[seed].min()) + float(level_m)

    return _flood_fill(elev, seed, surface), surface


def flood_stats(grid: DemGrid, mask: np.ndarray, surface: float) -> dict:
    cells = int(mask.sum())
    area_m2 = cells * grid.cell_area_m2(
        (grid.min_lat + grid.max_lat) / 2.0
    )
    depths = np.where(mask, surface - grid.elev, 0.0)
    deep_mask = depths >= DEPTH_CORE_M
    return {
        "cells_flooded": cells,
        "cell_resolution_m": grid.res_lat * 111.32 * 1000,
        "water_surface_m": surface,
        "max_depth_m": round(float(depths.max()), 2) if cells else 0.0,
        "mean_depth_m": round(float(depths[mask].mean()), 2) if cells else 0.0,
        "deep_area_km2": round(float(deep_mask.sum()) * grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0) / 1e6, 3) if cells else 0.0,
        "area_km2": round(area_m2 / 1e6, 3),
        "percent_of_cells": round(100.0 * mask.mean(), 2),
    }


DEPTH_CORE_M = 1.0


def flood_to_featurecollections(
    grid: DemGrid, mask: np.ndarray, surface: float | None = None
) -> dict:
    """Return rendered flood overlay GeoJSON.

    ``surface`` enables the deeper ``flood-deep`` band (cells at least
    ``DEPTH_CORE_M`` below the water surface) so the modelled water reads as
    a pond with a darker core instead of a flat translucent sheet.
    """
    features = [
        {"type": "Feature", "properties": {"class": "flood"}, "geometry": polygon}
        for polygon in mask_to_polygons(mask, grid)
    ]
    if surface is not None:
        deep = np.logical_and(mask, (surface - grid.elev) >= DEPTH_CORE_M)
        if deep.any():
            for polygon in mask_to_polygons(deep, grid):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"class": "flood-deep"},
                        "geometry": polygon,
                    }
                )
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def _result(mask: np.ndarray, surface: float | None, grid: DemGrid) -> dict:
    if surface is None or not mask.any():
        return {
            "dry": True,
            "flooded": {"type": "FeatureCollection", "features": []},
            "stats": {"cells_flooded": 0, "area_km2": 0.0, "percent_of_cells": 0.0, "max_depth_m": 0.0},
        }
    layers = flood_to_featurecollections(grid, mask, surface)
    stats = flood_stats(grid, mask, surface)
    return {
        "dry": False,
        "flooded": layers,
        "stats": stats,
    }


def run(grid: DemGrid, source_lng: float, source_lat: float, level_m: float, mode: str) -> dict:
    mask, surface = flood_mask(grid, source_lng, source_lat, level_m, mode)
    return _result(mask, surface, grid)


def run_river(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
) -> dict:
    mask, surface = river_flood_mask(grid, coords, level_m, mode)
    return _result(mask, surface, grid)