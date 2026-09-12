"""Tests for the simulation engine using a synthetic DEM city bundle."""

from __future__ import annotations

import json
import struct
import zlib
from collections import deque
from pathlib import Path

import numpy as np
import pytest

import app.datasets as datasets
from app.engine import earthquake, exposure, flood, suitability, terrain_tiles


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
    water = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Test River", "id": "w-1", "type": "waterway", "waterway": "river"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [min_lng + res, min_lat + res],
                        [min_lng + 2 * res, min_lat + 2 * res],
                        [c_lng - res, c_lat - res],
                        [c_lng, c_lat],
                        [c_lng + res, c_lat + res],
                        [min_lng + (n - 1) * res, min_lat + (n - 1) * res],
                    ],
                },
            }
        ],
    }
    for name, fc in (
        ("buildings", buildings),
        ("roads", roads),
        ("facilities", facilities),
        ("water", water),
    ):
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


def test_river_flood_seeds_channel_and_rises(city):
    grid = datasets.load_city_dem(city.name)
    geometry = datasets.river_geometry_by_ref(city.name, "w-1")
    assert geometry is not None
    coords = datasets.line_vertices(geometry)
    centre_r, centre_c = grid.cell(*datasets.city_meta(city.name)["center"])

    mask, surface = flood.river_flood_mask(grid, coords, level_m=2.0, mode="rise")
    expected_surface = float(grid.elev[centre_r, centre_c]) + 2.0
    assert surface == expected_surface
    assert mask.sum() > 0
    assert mask[centre_r, centre_c]

    big_mask, _ = flood.river_flood_mask(grid, coords, level_m=50.0, mode="rise")
    assert big_mask.sum() > mask.sum()


def test_river_flood_dry_when_surface_below_channel(city):
    grid = datasets.load_city_dem(city.name)
    coords = datasets.line_vertices(datasets.river_geometry_by_ref(city.name, "w-1"))
    mask, surface = flood.river_flood_mask(grid, coords, level_m=5.0, mode="absolute")
    assert surface == 5.0
    assert mask.sum() == 0

    result = flood.run_river(grid, coords, level_m=5.0, mode="absolute")
    assert result["dry"] is True
    assert result["stats"]["cells_flooded"] == 0


def test_river_lookup_by_name_and_rivers_summary(city):
    assert datasets.river_geometry_by_ref(city.name, "TEST RIVER") is not None
    rows = datasets.rivers(city.name)
    assert rows[0]["id"] == "w-1"
    assert rows[0]["name"] == "Test River"
    assert rows[0]["type"] == "waterway"


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


def test_flood_overlay_includes_deep_core_band(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    result = flood.run(grid, *centre, level_m=15.0, mode="rise")
    assert not result["dry"]
    classes = {
        f["properties"]["class"] for f in result["flooded"]["features"]
    }
    assert "flood" in classes
    # the bowl keeps a deep (>1 m) core for an aggressive rise
    assert "flood-deep" in classes
    assert result["stats"]["max_depth_m"] > 1.0
    assert result["stats"]["mean_depth_m"] > 0.0


def test_quake_radii_monotonic_by_severity(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    result = earthquake.run(grid, centre[0], centre[1], 7.0, 10.0)
    radii = [result["radii_km"][b] for b in earthquake.BANDS]
    assert radii[0] < radii[-1]
    assert result["radii_km"]["high"] > 0.0


def decode_png_rgb(data: bytes) -> tuple[int, int, tuple[int, int, int]]:
    """Unpack the minimal PNG writer output: (w, h, mode)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = bytearray()
    w = h = mode = -1
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            w, h, _, mode, _, _, _ = struct.unpack(">IIBBBBB", chunk)
        elif tag == b"IDAT":
            idat.extend(chunk)
        pos += 12 + length
    rgb = np.frombuffer(zlib.decompress(bytes(idat)), dtype=np.uint8).reshape(
        h, 1 + w * 3
    )[:, 1:]
    return w, h, (mode, rgb)


def terrain_decode(elev_m: float) -> np.ndarray:
    v = max(0.0, min(65535.0, elev_m + 32768.0))
    r = int(v) >> 8 & 0xFF
    g = int(v) & 0xFF
    b = int((v - int(v)) * 256) & 0xFF
    return np.array([r, g, b], dtype=np.uint8)


def test_terrain_tile_roundtrips_terrarium(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    z = 9
    n = 2**z
    x = int((centre[0] + 180.0) / 360.0 * n)
    m = (1.0 - np.log(np.tan(np.deg2rad(centre[1])) + 1.0 / np.cos(np.deg2rad(centre[1]))) / np.pi) / 2.0
    y = int(m * n)
    data = terrain_tiles.tile(city.name, z, x, y)
    assert data is not None
    w, h, (mode, rgb) = decode_png_rgb(data)
    assert (mode, w, h) == (2, 256, 256)
    # decode the tile-centre pixel and compare with the DEM at that point
    cx = 360.0 * ((x + 0.5) / n) - 180.0
    cy = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 0.5) / n))))
    r, c = grid.cell(cx, cy)
    expected = float(grid.elev[r, c])
    pix = 128 * 3
    got = (
        float(rgb[128, pix]) * 256.0
        + float(rgb[128, pix + 1])
        + float(rgb[128, pix + 2]) / 256.0
        - 32768.0
    )
    assert abs(got - expected) < 60.0
    # a tile far outside the DEM extent must return None (no coverage)
    assert terrain_tiles.tile(city.name, z, 0, 0) is None
    assert terrain_tiles.tile(city.name, 4, 0, 0) is None  # below MIN_ZOOM