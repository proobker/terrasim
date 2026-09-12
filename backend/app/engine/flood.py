"""Flow-routed hypothetical flood extent.

This is deliberately NOT a hydrodynamic model. It computes the set of
raster cells that (a) are hydrologically connected to a user-supplied
source (a clicked cell or a whole river channel) and (b) lie below a
modelled water surface. See plans.md §8.

The water surface is flow-aware, not a single flat level:

- A D8 steepest-descent direction raster is derived from the DEM; water
  leaves the source along the downhill flow path and ponds where the
  terrain opens up below the carried water surface.
- For a river source, the modelled surface rises by ``level_m`` above the
  *local* channel bed (a smoothed grade line) rather than above the
  channel's lowest point, so water follows the run of the river and
  different rivers produce genuinely different extents.
- Spreading ponds use the highest incoming water surface (max-wins), so
  connected low ground fills to a common level while higher ground stays
  dry.

Limitations kept explicit: no rainfall, discharge, flow velocity, channel
hydraulics, drainage networks, infiltration or time-dependence. Treat the
output as a *terrain-based hypothetical flood extent*, never a prediction.
"""

from __future__ import annotations

import heapq

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons

# 8-connected neighbour offsets, index = D8 direction code (row-major order).
_NEIGH8 = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)

_EPS = 1e-6


def _d8_flow_dir(elev: np.ndarray) -> np.ndarray:
    """D8 steepest-descent direction for every raster cell.

    Returns an int8 raster whose value is an index into ``_NEIGH8`` pointing
    to the neighbour with the largest elevation drop. Cells with no strictly
    lower neighbour (pits, plateaus, DEM edges) are sinks and get ``-1`` —
    flood water that reaches a sink stays there and ponds.
    """
    h, w = elev.shape
    padded = np.pad(elev, 1, mode="edge")
    flow = np.full((h, w), -1, dtype=np.int8)
    best_drop = np.zeros((h, w))
    for code, (dr, dc) in enumerate(_NEIGH8):
        win = padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
        drop = elev - win
        take = drop > best_drop  # strict: first direction wins ties
        flow[take] = code
        best_drop = np.maximum(best_drop, drop)
    return flow


def _local_min_disk(elev: np.ndarray, radius: int = 2) -> np.ndarray:
    """Morphological minimum over a small disk (grade-following channel bed).

    A single spurious high vertex (bridge, sampling artifact) must not
    locally prop up the water surface and split a reach, so the channel
    "bed" used for the graded surface is the local minimum rather than the
    raw elevation. Radius 2 spans roughly one DEM cell-pair.
    """
    h, w = elev.shape
    padded = np.pad(elev, radius, mode="edge")
    out = np.full((h, w), np.inf)
    r2 = radius * radius
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr * dr + dc * dc > r2:
                continue
            win = padded[radius + dr : radius + dr + h, radius + dc : radius + dc + w]
            out = np.minimum(out, win)
    return out


def _channel_seeds(grid: DemGrid, coords: list[tuple[float, float]]) -> np.ndarray:
    """Rasterize a river polyline into a continuous 4-connected seed mask."""
    seed = np.zeros(grid.elev.shape, dtype=bool)
    cells = [grid.cell(lng, lat) for lng, lat in coords]
    if not cells:
        return seed
    for (r0, c0), (r1, c1) in zip(cells, cells[1:]):
        seed[r0, c0] = True
        seed[r1, c1] = True
        dr_abs, dc_abs = abs(r1 - r0), abs(c1 - c0)
        sr = 1 if r1 >= r0 else -1
        sc = 1 if c1 >= c0 else -1
        err = dr_abs - dc_abs
        r, c = r0, c0
        while (r, c) != (r1, c1):
            e2 = 2 * err
            if e2 > -dc_abs:
                err -= dc_abs
                r += sr
            if e2 < dr_abs:
                err += dr_abs
                c += sc
            seed[r, c] = True
    return seed


def _surface_seed(
    elev: np.ndarray,
    flow: np.ndarray,
    seeds: np.ndarray,
    seed_surface: np.ndarray,
) -> np.ndarray:
    """Carry the water surface downstream along the D8 flow path.

    Every seed cell's modelled surface is walked downstream through the
    flow-direction network; a downstream cell inherits the water surface of
    the cell that drains into it whenever the terrain there is below that
    surface. This is the "direction of flow" backbone of the model: water
    reaches the river's outlet corridor even where the ridgeline would be
    ambiguous.
    """
    surf = seed_surface.astype(float).copy()
    # A seed only holds water when its own terrain is at or below its surface
    # (e.g. an absolute level below a dry reach must not seed that reach).
    surf[elev > surf] = -np.inf
    stack = list(map(tuple, np.argwhere(seeds)))
    nrows, ncols = elev.shape
    while stack:
        r, c = stack.pop()
        code = int(flow[r, c])
        if code < 0:
            continue
        dr, dc = _NEIGH8[code]
        nr, nc = r + dr, c + dc
        if not (0 <= nr < nrows and 0 <= nc < ncols):
            continue
        s = surf[r, c]
        if elev[nr, nc] <= s + _EPS and s > surf[nr, nc] + _EPS:
            surf[nr, nc] = s
            stack.append((nr, nc))
    return surf


def _pond_fill(elev: np.ndarray, surf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Spread standing water across connected low ground below the surface.

    A priority fill ordered by the highest incoming water surface (max-wins):
    a cell floods when its terrain is at or below the peak surface reaching
    it, and where two ponds merge the higher surface governs. This is the
    ponding half of the model — overtopped banks backfill their floodplain
    at the local (graded) water level.
    """
    started = surf > -np.inf
    if not started.any():
        return started, surf
    pq = [(-surf[r, c], int(r), int(c)) for r, c in np.argwhere(started)]
    heapq.heapify(pq)
    nrows, ncols = elev.shape
    while pq:
        neg_s, r, c = heapq.heappop(pq)
        s = -neg_s
        if s < surf[r, c] - _EPS:
            continue
        r0, r1 = max(0, r - 1), min(nrows, r + 2)
        c0, c1 = max(0, c - 1), min(ncols, c + 2)
        for nr in range(r0, r1):
            for nc in range(c0, c1):
                if nr == r and nc == c:
                    continue
                if s > surf[nr, nc] + _EPS and elev[nr, nc] <= s + _EPS:
                    surf[nr, nc] = s
                    heapq.heappush(pq, (-s, nr, nc))
    return surf > -np.inf, surf


def _flow_route(
    grid: DemGrid, seeds: np.ndarray, seed_surface: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return (flooded mask, per-cell water-surface raster)."""
    elev = grid.elev
    flow = _d8_flow_dir(elev)
    surf = _surface_seed(elev, flow, seeds, seed_surface)
    return _pond_fill(elev, surf)


def flood_mask(
    grid: DemGrid,
    source_lng: float,
    source_lat: float,
    level_m: float,
    mode: str = "rise",
) -> tuple[np.ndarray, float | None]:
    """Compute the flow-routed flooded-cell mask from a clicked source cell.

    Args:
        grid: elevation raster + georeferencing.
        source_lng/source_lat: flood origin (usually a river/water body).
        level_m: either an absolute water-surface elevation (meters above
            sea level) when ``mode == "absolute"``, or a rise above the
            source cell's elevation when ``mode == "rise"``.
        mode: ``"rise"`` or ``"absolute"``.

    Returns:
        (flooded mask, peak modelled water surface in meters or None if dry).
    """
    elev = grid.elev
    r0, c0 = grid.cell(source_lng, source_lat)
    if mode == "absolute":
        s0 = float(level_m)
        if elev[r0, c0] > s0:
            return np.zeros_like(elev, dtype=bool), None
    else:
        s0 = float(elev[r0, c0]) + float(level_m)

    seeds = np.zeros_like(elev, dtype=bool)
    seeds[r0, c0] = True
    seed_surface = np.full(elev.shape, -np.inf)
    seed_surface[r0, c0] = s0
    mask, surf = _flow_route(grid, seeds, seed_surface)
    if not mask.any():
        return mask, None
    return mask, float(surf[mask].max())


def river_flood_mask(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
) -> tuple[np.ndarray, float | None]:
    """Compute the flow-routed flooded mask seeded along a river channel.

    Every cell the river line crosses becomes a flood seed, so the modelled
    water rises out of the whole channel. For ``mode == "rise"`` the water
    surface follows the river's own grade line: each reach is hypothesized
    to rise by ``level_m`` meters *above its local channel bed*, so upstream
    and downstream reaches flood independently instead of sharing one flat
    level. Water is then routed downstream along the D8 flow path and ponds
    in connected low ground. For ``"absolute"`` the surface is ``level_m``
    meters above sea level (flat), as before.

    Args:
        grid: elevation raster + georeferencing.
        coords: river line vertices as ``(lng, lat)`` pairs.
        level_m: absolute water-surface elevation (meters above sea level)
            when ``mode == "absolute"``, or the hypothesized rise in meters
            above each reach's local channel bed when ``mode == "rise"``.
        mode: ``"rise"`` or ``"absolute"``.

    Returns:
        (flooded mask, peak modelled water surface in meters or None when no
        river cell falls inside the DEM coverage / nothing floods).
    """
    elev = grid.elev
    seeds = _channel_seeds(grid, coords)
    if not seeds.any():
        return seeds, None

    seed_surface = np.full(elev.shape, -np.inf)
    if mode == "absolute":
        seed_surface[seeds] = float(level_m)
    else:
        bed = _local_min_disk(elev)
        seed_surface[seeds] = bed[seeds] + float(level_m)

    mask, surf = _flow_route(grid, seeds, seed_surface)
    if not mask.any():
        return mask, None
    return mask, float(surf[mask].max())


def flood_stats(
    grid: DemGrid,
    mask: np.ndarray,
    surface: float,
    surface_raster: np.ndarray | None = None,
) -> dict:
    """Aggregate flood extents and depths.

    ``surface`` is the peak modelled water surface (reported as the
    scenario's ``water_surface_m``). When ``surface_raster`` is supplied,
    per-cell depth is ``surface_raster - elevation`` so a graded surface
    yields correct depth bands along the river; otherwise depth falls back
    to a flat surface.
    """
    cells = int(mask.sum())
    area_m2 = cells * grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0)
    if surface_raster is not None:
        depths = np.where(mask, surface_raster - grid.elev, 0.0)
    else:
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
    grid: DemGrid, mask: np.ndarray, surface: np.ndarray | float | None = None
) -> dict:
    """Return rendered flood overlay GeoJSON.

    ``surface`` enables the deeper ``flood-deep`` band (cells at least
    ``DEPTH_CORE_M`` below the modelled water surface) so the modelled water
    reads as a pond with a darker core instead of a flat translucent sheet.
    Accepts either a flat surface (float) or a per-cell surface raster
    (ndarray) for graded depths.
    """
    features = [
        {"type": "Feature", "properties": {"class": "flood"}, "geometry": polygon}
        for polygon in mask_to_polygons(mask, grid)
    ]
    if surface is not None:
        if np.ndim(surface) == 0:
            depth = np.where(mask, float(surface) - grid.elev, 0.0)
        else:
            depth = np.where(mask, surface - grid.elev, 0.0)
        deep = depth >= DEPTH_CORE_M
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


def _result(grid: DemGrid, mask: np.ndarray, surface_raster: np.ndarray | None = None) -> dict:
    if surface_raster is None or not mask.any():
        return {
            "dry": True,
            "flooded": {"type": "FeatureCollection", "features": []},
            "stats": {"cells_flooded": 0, "area_km2": 0.0, "percent_of_cells": 0.0, "max_depth_m": 0.0},
        }
    surface = float(surface_raster[mask].max())
    layers = flood_to_featurecollections(grid, mask, surface_raster)
    stats = flood_stats(grid, mask, surface, surface_raster)
    return {
        "dry": False,
        "flooded": layers,
        "stats": stats,
    }


def run(grid: DemGrid, source_lng: float, source_lat: float, level_m: float, mode: str) -> dict:
    mask, _ = flood_mask(grid, source_lng, source_lat, level_m, mode)
    if not mask.any():
        return _result(grid, mask)
    elev = grid.elev
    r0, c0 = grid.cell(source_lng, source_lat)
    s0 = float(elev[r0, c0]) + float(level_m) if mode == "rise" else float(level_m)
    seeds = np.zeros_like(elev, dtype=bool)
    seeds[r0, c0] = True
    seed_surface = np.full(elev.shape, -np.inf)
    seed_surface[r0, c0] = s0
    _, surf = _flow_route(grid, seeds, seed_surface)
    return _result(grid, mask, surf)


def run_river(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
) -> dict:
    mask, _ = river_flood_mask(grid, coords, level_m, mode)
    if not mask.any():
        return _result(grid, mask)
    elev = grid.elev
    seeds = _channel_seeds(grid, coords)
    seed_surface = np.full(elev.shape, -np.inf)
    if mode == "absolute":
        seed_surface[seeds] = float(level_m)
    else:
        bed = _local_min_disk(elev)
        seed_surface[seeds] = bed[seeds] + float(level_m)
    _, surf = _flow_route(grid, seeds, seed_surface)
    return _result(grid, mask, surf)