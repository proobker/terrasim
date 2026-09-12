"""Volume-conserving, transient, tributary-aware hypothetical flood model.

This is deliberately NOT a hydrodynamic model. It routes a hypothetical
flood *volume* through the terrain as a simplified flood wave, so the
results are directional (water travels downstream over simulated time),
volume-limited (a given rise carries a given amount of water, nothing
more), and specific to the chosen river and its tributaries.

What the model tracks:

- **Direction of flow**: every cell gets a D8 steepest-descent direction
  from the DEM. Water moves from cell to cell along the flow network and
  spreads laterally only through shared lower ground.
- **Volume conservation**: the flood starts as an injected hydrograph
  volume, and the routing step moves water between cells while preserving
  the total. A ``rise_m`` is converted into a conserved volume derived
  from the reach geometry (length x assumed inundation width), so longer
  rivers carry more water and floodplains only fill until the volume is
  spent.
- **Transient wave**: inflow is released over simulated time (a
  triangular hydrograph), peaking early and decaying; each cell floods
  when the wave front reaches it, so upstream floods first and the flood
  extends downstream over time. The reported extent is the *peak* state
  over the whole simulation.
- **Tributaries**: any other mapped waterline whose basin drains into the
  chosen river contributes its own volume, lagged by its distance to the
  junction — so tributary-fed floods arrive later and add water.

Limitations kept explicit: no rainfall-runoff, evaporation, infiltration,
channel cross-sections, hydraulic structures, erosion, or true velocity;
the routing is a simplified flux transfer capped for numerical stability.
Treat the output as a *terrain-based hypothetical flood extent*, never a
prediction. See plans.md §8.
"""

from __future__ import annotations

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons

# 8-connected neighbour offsets, index = D8 direction code (row-major order).
_NEIGH8 = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)

_EPS = 1e-6
_DEPTH_EPS = 1e-3  # a cell counts as flooded once it holds this much water (m)

# Model tuning (hypothetical, not calibrated):
_CHANNEL_WIDTH_CELLS = 2.0  # assumed inundation width (in cells) above a reach
_TRIBUTARY_FACTOR = 0.5     # tributary volume vs an equal-length main reach
_SLOPE_STEPS_PER_CELL = 3   # sim steps for the wave to advance one grid cell
_MIN_STEPS = 120
_MAX_STEPS = 700
_FLUX_FRACTION = 0.22       # max head-driven depth fraction moved per step


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


def _upstream_catchment(
    elev: np.ndarray, flow: np.ndarray, seeds: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return (network distance to seed, contributing-catchment mask).

    A cell belongs to the catchment when its D8 downstream path reaches a
    seed cell. ``dist`` is the number of flow steps each cell needs to
    reach the nearest seed — used to lag tributary inflows by their
    distance to the junction. One top-down pass is enough because D8
    strictly descends: every cell is processed after its downstream
    neighbour.
    """
    h, w = elev.shape
    dist = np.full((h, w), np.inf)
    dist[seeds] = 0.0
    order = np.argsort(elev.ravel())  # lowest first: downstream resolves before upstream
    for idx in order:
        r, c = divmod(int(idx), w)
        code = int(flow[r, c])
        if code < 0:
            continue
        dr, dc = _NEIGH8[code]
        nr, nc = r + dr, c + dc
        if dist[nr, nc] + 1.0 < dist[r, c]:
            dist[r, c] = dist[nr, nc] + 1.0
    return dist, np.isfinite(dist)


def _flow_accumulation(elev: np.ndarray, flow: np.ndarray) -> np.ndarray:
    """D8 flow accumulation: how many cells drain through each cell.

    Used to weight inflows toward headwater reaches, so a rise sends more
    water where the river's own basin is deep. One top-down pass suffices
    (D8 strictly descends).
    """
    h, w = elev.shape
    acc = np.ones(elev.shape, dtype=np.float64)
    order = np.argsort(elev.ravel())[::-1]
    for idx in order:
        r, c = divmod(int(idx), w)
        code = int(flow[r, c])
        if code < 0:
            continue
        dr, dc = _NEIGH8[code]
        nr, nc = r + dr, c + dc
        acc[nr, nc] += acc[r, c]
    return acc


def _channel_seeds(grid: DemGrid, coords: list[tuple[float, float]]) -> np.ndarray:
    """Rasterize a river polyline into a continuous 4-connected seed mask."""
    h, w = grid.elev.shape
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
                err += dc_abs
                c += sc
            if (r - r1) * sr > 0:
                r = r1
            if (c - c1) * sc > 0:
                c = c1
            if 0 <= r < h and 0 <= c < w:
                seed[r, c] = True
    return seed


def _all_water_seeds(
    grid: DemGrid, water_features: list[dict] | None
) -> np.ndarray | None:
    """Rasterize every waterway in a FeatureCollection into a union mask."""
    if not water_features:
        return None
    union = np.zeros(grid.elev.shape, dtype=bool)
    for feature in water_features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not geometry:
            continue
        coords = _line_coords(geometry)
        if coords:
            union |= _channel_seeds(grid, coords)
    return union


def _line_coords(geometry: dict) -> list[tuple[float, float]]:
    """Flatten LineString/MultiLineString/Polygon geometry into (lng, lat)."""
    coords = geometry.get("coordinates") or []
    gtype = geometry.get("type")
    if gtype == "LineString":
        return [(p[0], p[1]) for p in coords]
    if gtype == "MultiLineString":
        return [(p[0], p[1]) for part in coords for p in part]
    if gtype == "Polygon":
        return [(p[0], p[1]) for ring in coords for p in ring]
    return []


def _inflow_plan(
    grid: DemGrid,
    elev: np.ndarray,
    flow: np.ndarray,
    main_seeds: np.ndarray,
    all_water: np.ndarray | None,
    level_m: float,
    mode: str,
    use_catchment: bool = True,
) -> dict | None:
    """Translate a rise into a conserved per-cell inflow plan.

    Returns None (dry) when there is nowhere for the water to go. The plan
    carries, for every inflow cell, its total depth assignment ``d_cell``
    and the simulation step ``start`` at which its share begins to flow —
    river cells start immediately, tributaries lag by their distance to
    the river, and geo-referenced water bodies inject at once.
    """
    cell_area = grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0)
    h, w = elev.shape
    n_steps = _MIN_STEPS

    if mode == "absolute":
        d_cell = np.maximum(0.0, float(level_m) - elev).astype(np.float32)
        inflow_mask = d_cell > _DEPTH_EPS
        if not inflow_mask.any():
            return None
        starts = np.zeros((h, w), dtype=np.int64)
        window = min(40, n_steps // 3)
        source_volume = float((d_cell * cell_area).sum())
        tributaries = 0
        return {
            "inflow_mask": inflow_mask,
            "d_cell": d_cell,
            "starts": starts,
            "window": window,
            "n_steps": n_steps,
            "volume_m3": source_volume,
            "peak_step_m3": source_volume,
            "tributaries": tributaries,
        }

    if not use_catchment:
        inflow_mask = main_seeds.copy()
    else:
        dist, catchment = _upstream_catchment(elev, flow, main_seeds)
        inflow_mask = main_seeds.copy()
        if all_water is not None:
            inflow_mask |= catchment & all_water
    trib_mask = inflow_mask & ~main_seeds

    reach_cells = int(main_seeds.sum())
    if reach_cells == 0:
        return None
    n_steps = int(min(max(reach_cells * _SLOPE_STEPS_PER_CELL, _MIN_STEPS), _MAX_STEPS))
    window = max(5, n_steps // 3)

    n_main = int(main_seeds.sum())
    n_trib = int(trib_mask.sum())
    volume = float(level_m) * cell_area * _CHANNEL_WIDTH_CELLS * (n_main + n_trib * _TRIBUTARY_FACTOR)
    if volume <= 0.0:
        return None

    if use_catchment:
        acc = _flow_accumulation(elev, flow)
        weight = np.where(trib_mask, acc * _TRIBUTARY_FACTOR, acc)
    else:
        acc = np.ones(elev.shape, dtype=np.float64)
        weight = acc
    weight = np.where(inflow_mask, weight, 0.0)
    total_weight = float(weight.sum())
    if total_weight <= 0.0:
        return None
    share = weight / total_weight

    d_cell = (share * volume / cell_area).astype(np.float32)
    if use_catchment:
        lag = np.full((h, w), n_steps, dtype=np.int64)
        finite = np.isfinite(dist)
        if finite.any():
            lag[finite] = np.clip(
                (dist[finite] * _SLOPE_STEPS_PER_CELL).astype(np.int64), 0, n_steps - window
            )
        starts = lag.copy()
    else:
        starts = np.zeros((h, w), dtype=np.int64)
        starts[inflow_mask] = 0
        starts[~inflow_mask] = n_steps

    peak_step_rate = volume * (3.0 / window) * 0.5
    return {
        "inflow_mask": inflow_mask,
        "d_cell": d_cell,
        "starts": starts,
        "window": window,
        "n_steps": n_steps,
        "volume_m3": float(volume),
        "peak_step_m3": peak_step_rate,
        "tributaries": n_trib if all_water is not None else 0,
        "reach_cells": reach_cells,
    }


def _flux_ca_step(elev: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """Move one timestep of water volume between neighbouring cells.

    Head-driven flux (water goes to lower or flooded neighbours), clipped
    so a cell never exports more than it holds — the routing conserves
    volume. Cells on the DEM edge face an infinitely high wall (padded
    elevation ``+inf``) and therefore never leak off the grid.
    """
    h, w = elev.shape
    stage = elev + depth
    pad = np.full((h + 2, w + 2), np.inf, dtype=np.float32)
    pad[1:-1, 1:-1] = stage

    out = np.zeros((h, w), dtype=np.float32)
    heads = []
    for dr, dc in _NEIGH8:
        sn = pad[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
        heads.append(np.maximum(stage - sn, 0.0))

    available = depth / 8.0
    scale_denom = np.zeros((h, w), dtype=np.float32)
    for head in heads:
        scale_denom += np.minimum(_FLUX_FRACTION * head, available)
    scale = np.minimum(1.0, depth / np.maximum(scale_denom, _EPS))

    gain = np.zeros((h + 2, w + 2), dtype=np.float32)
    for code, (dr, dc) in enumerate(_NEIGH8):
        flux = np.minimum(_FLUX_FRACTION * heads[code], available) * scale
        out += flux
        gain[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w] += flux
    return depth - out + gain[1:-1, 1:-1]


def _dilate8(mask: np.ndarray) -> np.ndarray:
    """Dilate a boolean mask by one 8-connected cell."""
    h, w = mask.shape
    padded = np.pad(mask, 1, mode="constant")
    out = mask.copy()
    for dr, dc in _NEIGH8:
        out |= padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
    return out


def _flux_domain(
    elev: np.ndarray, flow: np.ndarray, inflow_mask: np.ndarray, margin: int = 6
) -> np.ndarray:
    """Cells the flood wave can reach.

    The union of the D8 upstream closure (tributary basin) and the
    downstream closure (every cell the wave itself can travel to along the
    flow network), dilated by ``margin`` cells so stage-driven spreading
    onto the floodplain is not cut off. The flux simulation runs only
    inside the box that bounds this domain, keeping the cost proportional
    to the valley rather than the whole DEM.
    """
    h, w = elev.shape
    domain = inflow_mask.copy()
    down = inflow_mask.copy()
    order_asc = np.argsort(elev.ravel())  # lowest first: propagate downstream
    for idx in order_asc:
        r, c = divmod(int(idx), w)
        code = int(flow[r, c])
        if code < 0 or not down[r, c]:
            continue
        dr, dc = _NEIGH8[code]
        down[r + dr, c + dc] = True
    order_desc = order_asc[::-1]  # highest first: propagate upstream
    for idx in order_desc:
        r, c = divmod(int(idx), w)
        code = int(flow[r, c])
        if code < 0:
            continue
        dr, dc = _NEIGH8[code]
        if not domain[r, c] and domain[r + dr, c + dc]:
            domain[r, c] = True
    domain |= down
    for _ in range(margin):
        domain = _dilate8(domain)
    return domain


def _flux_simulate(
    elev: np.ndarray,
    flow: np.ndarray,
    plan: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Run the hydrograph through the flux router; return (peak_mask, surface).

    ``surface`` is the peak water-surface raster (elevation + peak depth).
    The router operates on a sub-grid bounded by the reachable domain
    (D8 network plus a lateral margin), keeping the cost proportional to
    the valley rather than the whole DEM.
    """
    inflow = plan["inflow_mask"]
    d_cell = plan["d_cell"]
    starts = plan["starts"]
    window = plan["window"]
    n_steps = plan["n_steps"]
    factor = 3.0 / window

    domain = _flux_domain(elev, flow, inflow, margin=12)
    rows, cols = np.argwhere(domain).T
    if rows.size == 0:
        return np.zeros_like(elev, dtype=bool), elev.astype(np.float32)
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1

    elev_f = elev.astype(np.float32)
    elev_s = elev_f[r0:r1, c0:c1]
    d_cell = np.ascontiguousarray(d_cell[r0:r1, c0:c1])
    starts = np.ascontiguousarray(starts[r0:r1, c0:c1].astype(np.int64))

    depth = np.zeros(elev_s.shape, dtype=np.float32)
    peak = np.zeros(elev_s.shape, dtype=np.float32)
    for t in range(n_steps):
        active = (starts <= t) & (t < starts + window)
        if active.any():
            u = np.clip((t - starts) / window, 0.0, 1.0)
            shape = factor * (2.0 * u - 2.0 * u * u)
            depth += np.where(active, d_cell * shape, np.float32(0.0))
        depth = _flux_ca_step(elev_s, depth)
        peak = np.maximum(peak, depth)

    surface = elev_f.copy()
    surface[r0:r1, c0:c1] = elev_s + peak
    mask = np.zeros_like(elev, dtype=bool)
    mask[r0:r1, c0:c1] = peak > _DEPTH_EPS
    return mask, surface


def flood_mask(
    grid: DemGrid,
    source_lng: float,
    source_lat: float,
    level_m: float,
    mode: str = "rise",
    *,
    region: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Compute the flooded-cell mask from a point source.

    Returns (mask, peak water-surface raster or None when nothing floods).
    In ``rise`` mode the point source releases a conserved volume equal to
    the rise above the source cell's terrain at a one-cell inlet; in
    ``absolute`` mode the volume is the water below ``level_m`` above sea
    level. ``region`` optionally clips the reported mask to a geographic
    basin.
    """
    elev = grid.elev
    r0, c0 = grid.cell(source_lng, source_lat)
    seeds = np.zeros_like(elev, dtype=bool)
    seeds[r0, c0] = True
    flow = _d8_flow_dir(elev)
    plan = _inflow_plan(grid, elev, flow, seeds, None, level_m, mode, use_catchment=False)
    if plan is None:
        return np.zeros_like(elev, dtype=bool), None
    mask, surface = _flux_simulate(elev, flow, plan)
    if region is not None:
        mask = mask & region
    if not mask.any():
        return mask, None
    return mask, surface


def river_flood_mask(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
    water_features: list[dict] | None = None,
    *,
    region: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Compute the flooded mask seeded along a river channel.

    Every cell the river line crosses is an inflow cell. When
    ``water_features`` (a GeoJSON FeatureCollection) is supplied, its
    waterlines inside the river's contributing basin add volume as
    tributaries. Returns (mask, peak water-surface raster or None).
    """
    elev = grid.elev
    seeds = _channel_seeds(grid, coords)
    if not seeds.any():
        return seeds, None
    all_water = _all_water_seeds(grid, water_features)
    flow = _d8_flow_dir(elev)
    plan = _inflow_plan(grid, elev, flow, seeds, all_water, level_m, mode)
    if plan is None:
        return np.zeros_like(elev, dtype=bool), None
    mask, surface = _flux_simulate(elev, flow, plan)
    if region is not None:
        mask = mask & region
    if not mask.any():
        return mask, None
    return mask, surface


def flood_stats(
    grid: DemGrid,
    mask: np.ndarray,
    surface: float,
    surface_raster: np.ndarray | None = None,
    extra: dict | None = None,
) -> dict:
    """Aggregate flood extents and depths.

    ``surface`` is the peak modelled water surface (reported as the
    scenario's ``water_surface_m``). When ``surface_raster`` is supplied,
    per-cell depth is ``surface_raster - elevation`` so the graded, routed
    surface yields correct depth bands along the river.
    """
    cells = int(mask.sum())
    area_m2 = cells * grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0)
    if surface_raster is not None:
        depths = np.where(mask, surface_raster - grid.elev, 0.0)
    else:
        depths = np.where(mask, surface - grid.elev, 0.0)
    deep_mask = depths >= DEPTH_CORE_M
    stats = {
        "cells_flooded": cells,
        "cell_resolution_m": grid.res_lat * 111.32 * 1000,
        "water_surface_m": surface,
        "max_depth_m": round(float(depths.max()), 2) if cells else 0.0,
        "mean_depth_m": round(float(depths[mask].mean()), 2) if cells else 0.0,
        "deep_area_km2": round(float(deep_mask.sum()) * grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0) / 1e6, 3) if cells else 0.0,
        "area_km2": round(area_m2 / 1e6, 3),
        "percent_of_cells": round(100.0 * mask.mean(), 2),
    }
    if extra:
        stats.update(extra)
    return stats


DEPTH_CORE_M = 1.0


def flood_to_featurecollections(
    grid: DemGrid, mask: np.ndarray, surface: np.ndarray | float | None = None
) -> dict:
    """Return rendered flood overlay GeoJSON.

    ``surface`` enables the deeper ``flood-deep`` band (cells at least
    ``DEPTH_CORE_M`` below the peak water surface) so the modelled water
    reads as a pond with a darker core. Accepts a flat surface (float) or
    a per-cell peak surface raster (ndarray).
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


def _time_stats(grid: DemGrid, plan: dict) -> dict:
    """Hypothetical wave timings: steps, modelled hours, peak discharge."""
    cell_m = grid.res_lat * 111.32 * 1000
    dt_s = cell_m / (0.8 * _SLOPE_STEPS_PER_CELL)  # assume ~0.8 m/s flow
    return {
        "sim_steps": plan["n_steps"],
        "sim_hours": round(plan["n_steps"] * dt_s / 3600.0, 2),
        "peak_discharge_m3s": round(plan["peak_step_m3"] / dt_s, 1),
    }


def _result(
    grid: DemGrid,
    mask: np.ndarray,
    surface_raster: np.ndarray | None = None,
    plan: dict | None = None,
    *,
    region: np.ndarray | None = None,
) -> dict:
    """Assemble the flood result dict (also carries the raw mask for reuse)."""
    if region is not None:
        mask = mask & region
    if mask.any() and surface_raster is not None and plan is not None:
        surface = float(surface_raster[mask].max())
        layers = flood_to_featurecollections(grid, mask, surface_raster)
        extra = {
            "volume_m3": round(plan["volume_m3"], 1),
            "tributaries": int(plan.get("tributaries", 0)),
            "reach_cells": int(plan.get("reach_cells", 0)),
        }
        extra.update(_time_stats(grid, plan))
        stats = flood_stats(grid, mask, surface, surface_raster, extra)
        return {
            "dry": False,
            "flooded": layers,
            "stats": stats,
            "mask": mask,
        }
    return {
        "dry": True,
        "flooded": {"type": "FeatureCollection", "features": []},
        "stats": {
            "cells_flooded": 0,
            "area_km2": 0.0,
            "percent_of_cells": 0.0,
            "max_depth_m": 0.0,
            "volume_m3": 0.0,
            "tributaries": 0,
            "reach_cells": 0,
            "sim_steps": 0,
            "sim_hours": 0.0,
            "peak_discharge_m3s": 0.0,
        },
        "mask": np.zeros_like(grid.elev, dtype=bool),
    }


def run(
    grid: DemGrid,
    source_lng: float,
    source_lat: float,
    level_m: float,
    mode: str,
    *,
    region: np.ndarray | None = None,
) -> dict:
    elev = grid.elev
    r0, c0 = grid.cell(source_lng, source_lat)
    seeds = np.zeros_like(elev, dtype=bool)
    seeds[r0, c0] = True
    flow = _d8_flow_dir(elev)
    plan = _inflow_plan(grid, elev, flow, seeds, None, level_m, mode, use_catchment=False)
    if plan is None:
        return _result(grid, np.zeros_like(elev, dtype=bool), None, None, region=region)
    mask, surface = _flux_simulate(elev, flow, plan)
    return _result(grid, mask, surface, plan, region=region)


def run_river(
    grid: DemGrid,
    coords: list[tuple[float, float]],
    level_m: float,
    mode: str = "rise",
    water_features: list[dict] | None = None,
    *,
    region: np.ndarray | None = None,
) -> dict:
    elev = grid.elev
    seeds = _channel_seeds(grid, coords)
    if not seeds.any():
        return _result(grid, np.zeros_like(elev, dtype=bool), None, None, region=region)
    all_water = _all_water_seeds(grid, water_features)
    flow = _d8_flow_dir(elev)
    plan = _inflow_plan(grid, elev, flow, seeds, all_water, level_m, mode)
    if plan is None:
        return _result(grid, np.zeros_like(elev, dtype=bool), None, None, region=region)
    mask, surface = _flux_simulate(elev, flow, plan)
    return _result(grid, mask, surface, plan, region=region)