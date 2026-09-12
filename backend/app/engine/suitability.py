"""New-City suitability/risk layer (GREEN / YELLOW / RED planning indicators).

This is a relative planning aid built from elevation, slope and road access
— it is NOT a safety guarantee. See plans.md §4.
"""

from __future__ import annotations

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons

GREEN = 0
YELLOW = 1
RED = 2

BAND_NAMES = ["green", "yellow", "red"]


def _cells_near_segments(grid: DemGrid, segments: list[tuple[float, float]]) -> np.ndarray:
    """Boolean raster: True within ~2 cells of any supplied coordinate."""
    if not segments:
        return np.zeros((grid.nrows, grid.ncols), dtype=bool)
    near = np.zeros((grid.nrows, grid.ncols), dtype=bool)
    for lng, lat in segments:
        r, c = grid.cell(lng, lat)
        r0, r1 = max(0, r - 2), min(grid.nrows - 1, r + 2)
        c0, c1 = max(0, c - 2), min(grid.ncols - 1, c + 2)
        near[r0 : r1 + 1, c0 : c1 + 1] = True
    for _ in range(2):
        near = near | np.roll(near, 1, axis=0) | np.roll(near, -1, axis=0) | np.roll(near, 1, axis=1) | np.roll(near, -1, axis=1)
    return near


def suitability_score(grid: DemGrid, road_points: list[tuple[float, float]] | None = None) -> np.ndarray:
    """Return a suitability score grid in [0, 1] (higher = more suitable)."""
    elev = grid.elev.astype(np.float32)

    # Elevation factor: low-lying valley floors score worst on flood risk,
    # surrounding higher terrain scores better.
    p5, p95 = np.percentile(elev, [5, 95])
    e_norm = np.clip((elev - p5) / max(p95 - p5, 1.0), 0.0, 1.0)

    # Slope factor: convert degree-scale gradients to metres for the two axes.
    m_per_cell_x = grid.res_lng * grid.km_per_deg_lng((grid.min_lat + grid.max_lat) / 2.0) * 1000.0
    m_per_cell_y = grid.res_lat * 111.32 * 1000.0
    gy, gx = np.gradient(elev, m_per_cell_y, m_per_cell_x)
    grad = np.sqrt(gx**2 + gy**2)
    # Steepness normalised by the 90th percentile of the local gradient.
    p90_grade = np.percentile(np.clip(grad, 0, 60), 90)
    slope_norm = np.clip(grad / max(p90_grade, 1.0), 0.0, 1.0)

    road_regions = None
    if road_points:
        road_regions = _cells_near_segments(grid, road_points)
    road_bonus = np.where(road_regions, 0.10, 0.0) if road_points else np.zeros_like(elev)

    score = 0.52 * e_norm + 0.38 * (1.0 - slope_norm) + road_bonus
    return np.clip(score, 0.0, 1.0)


def classify_grid(score: np.ndarray) -> np.ndarray:
    """Map a score grid to GREEN/YELLOW/RED labels."""
    labels = np.full(score.shape, YELLOW, dtype=np.int8)
    labels[score >= 0.60] = GREEN
    labels[score <= 0.42] = RED
    return labels


def run(grid: DemGrid, road_points: list[tuple[float, float]] | None = None) -> dict:
    score = suitability_score(grid, road_points)
    labels = classify_grid(score)
    layers: dict[str, dict] = {}
    for band_idx, band_name in enumerate(BAND_NAMES):
        mask = labels == band_idx
        polygons = mask_to_polygons(mask, grid)
        layers[band_name] = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"class": band_name}, "geometry": polygon}
                for polygon in polygons
            ],
        }

    area_m2 = grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0)
    return {
        "layers": layers,
        "legend": {
            "green": "relatively suitable",
            "yellow": "conditional / investigate",
            "red": "relatively higher risk",
        },
        "area_km2": {
            band: round(int((labels == idx).sum()) * area_m2 / 1e6, 2)
            for idx, band in enumerate(BAND_NAMES)
        },
    }