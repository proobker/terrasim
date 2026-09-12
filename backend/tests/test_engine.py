"""Tests for the simulation engine using a synthetic DEM city bundle."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
import pytest

import app.datasets as datasets
from app.engine import earthquake, exposure, flood, suitability


def make_city_bundle(tmp_path: Path, city_id: str = "testcity", n: int = 24) -> Path:
    """Write a small synthetic city bundle and return its directory.

    Terrain is a centred bowl: elevation 10 m at the middle, rising to
    50 m at the rim. Platform resolution ~0.05 deg (~5.5 km).
    """
    res = 0.05
    min_lng, min_lat = 85.0, 27.0
    rows = np.arange(n)
    cols = np.arange(n)
    lat = min_lat + (n - rows - 0.5) * res
    lng = min_lng + (cols + 0.5) * res
    lng_grid, lat_grid = np.meshgrid(lng, lat)
    c_lng, c_lat = min_lng + n / 2 * res, min_lat + n / 2 * res
    dist = np.sqrt((lng_grid - c_lng) ** 2 + (lat_grid - c_lat) ** 2)
    elev = 10.0 + 40.0 * (dist / (res * n / 2)) ** 2

    city = tmp_path / city_id
    city.mkdir(parents=True, exist_ok=True)
    city_meta = {
        "id": city_id,
        "name": "Test City",
        "mode": "existing",
        "center": [c_lng, c_lat],
        "bounds": [min_lng, min_lat, min_lng + n * res, min_lat + n * res],
        "zoom": 10,
    }
    dem_meta = {"min_lng": min_lng, "min_lat": min_lat, "res_lng": res, "res_lat": res}
    (city / "city.json").write_text(json.dumps(city_meta), encoding="utf-8")
    (city / "dem.meta.json").write_text(json.dumps(dem_meta), encoding="utf-8")
    np.savez(city / "dem.npz", elev=elev.astype(np.float32))

    buildings = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "House 1", "id": 1},
                "geometry": {"type": "Point", "coordinates": [c_lng - res, c_lat]},
            }
        ],
    }
    roads = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Main Rd", "id": 1},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[min_lng + res, c_lat], [min_lng + n * res, c_lat]],
                },
            }
        ],
    }
    facilities = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "General Hospital", "id": 1, "type": "hospital"},
                "geometry": {"type": "Point", "coordinates": [c_lng, c_lat]},
            }
        ],
    }
    for name, fc in (("buildings", buildings), ("roads", roads), ("facilities", facilities)):
        (city / f"{name}.geojson").write_text(json.dumps(fc), encoding="utf-8")
    return city


@pytest.fixture
def city(tmp_path):
    datasets.DATA_ROOT = tmp_path
    return make_city_bundle(tmp_path)


def test_flood_bowl_is_single_connected_component(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    mask, surface = flood.flood_mask(grid, *centre, level_m=15.0, mode="rise")
    assert surface is not None
    assert mask.sum() > 0

    rows, cols = np.argwhere(mask).T
    visited = np.zeros_like(mask)
    queue = deque([(int(rows[0]), int(cols[0]))])
    visited[rows[0], cols[0]] = True
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < mask.shape[0] and 0 <= nc < mask.shape[1] and mask[nr, nc] and not visited[nr, nc]:
                visited[nr, nc] = True
                queue.append((nr, nc))
    assert visited.sum() == mask.sum()


def test_flood_allows_absolute_surface_mode(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    mask, surface = flood.flood_mask(grid, *centre, level_m=20.0, mode="absolute")
    assert surface == 20.0
    assert mask.sum() > 0


def test_flood_dry_when_surface_below_source(city):
    grid = datasets.load_city_dem(city.name)
    lng = grid.min_lng + grid.res_lng
    lat = grid.max_lat - grid.res_lat  # north rim: highest elevation (~83 m)
    mask, surface = flood.flood_mask(grid, lng, lat, level_m=60.0, mode="absolute")
    assert surface is None
    assert mask.sum() == 0


def test_quake_intensity_decays_with_distance(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    near_idx = earthquake_index_at(city, *centre)
    far_lng = grid.min_lng + grid.res_lng * grid.ncols
    far_idx = earthquake_index_at(city, far_lng, centre[1])
    assert 0.0 < near_idx <= 1.0
    assert far_idx < near_idx


def earthquake_index_at(city, lng, lat, m=7.0, depth=10.0):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    _, idx = earthquake.quake_zones_at(lng, lat, grid, centre[0], centre[1], m, depth)
    return idx


def test_quake_zones_contain_high_band_near_epicentre(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    zones = earthquake.quake_zones(grid, centre[0], centre[1], 7.0, 10.0)
    assert len(zones["high"]["features"]) > 0
    assert "low" in zones


def test_flood_exposure_flags_hospital(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    assets = datasets.load_assets(city.name)
    mask, _ = flood.flood_mask(grid, *centre, level_m=25.0)
    result = exposure.evaluate_flood_exposure(grid, assets, mask)
    assert result["assets"]["facilities"]["flooded"] == 1
    assert any(a["kind"] == "facilities" for a in result["affected"])


def test_quake_exposure_ranks_by_band(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    assets = datasets.load_assets(city.name)
    result = exposure.evaluate_quake_exposure(grid, assets, centre[0], centre[1], 7.0, 10.0)
    counts = result["assets"]["facilities"]
    assert counts["total"] == 1
    assert sum(counts[b] for b in earthquake.BANDS) == 1


def test_suitability_returns_all_three_classes(city):
    grid = datasets.load_city_dem(city.name)
    result = suitability.run(grid)
    assert set(result["legend"]) == {"green", "yellow", "red"}
    assert any(result["layers"][k]["features"] for k in result["layers"])