"""Tests for the simulation engine using a synthetic DEM city bundle."""

from __future__ import annotations

import json
import math
import struct
import zlib
from collections import deque
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import shape

import app.datasets as datasets
from app.engine import earthquake, exposure, flood, suitability, terrain_tiles
from app.engine.grid import DemGrid


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
    assert surface is not None
    assert mask.sum() > 0
    assert float(surface[mask].max()) > 18.0  # pooled surface ~ the absolute level


def test_flood_dry_when_surface_below_source(city):
    grid = datasets.load_city_dem(city.name)
    lng, lat = datasets.city_meta(city.name)["center"]
    mask, surface = flood.flood_mask(grid, lng, lat, level_m=5.0, mode="absolute")
    assert surface is None
    assert mask.sum() == 0


def test_river_flood_seeds_channel_and_rises(city):
    grid = datasets.load_city_dem(city.name)
    geometry = datasets.river_geometry_by_ref(city.name, "w-1")
    assert geometry is not None
    coords = datasets.line_vertices(geometry)
    centre_r, centre_c = grid.cell(*datasets.city_meta(city.name)["center"])

    mask, surface = flood.river_flood_mask(grid, coords, level_m=2.0, mode="rise")
    assert surface is not None
    assert mask.sum() > 0
    assert mask[centre_r, centre_c]  # the valley floor at the low point collects water

    big_mask, _ = flood.river_flood_mask(grid, coords, level_m=50.0, mode="rise")
    assert big_mask.sum() > mask.sum()

    result = flood.run_river(grid, coords, level_m=2.0, mode="rise")
    assert not result["dry"]
    assert result["stats"]["volume_m3"] > 0.0


def test_river_flood_dry_when_surface_below_channel(city):
    grid = datasets.load_city_dem(city.name)
    coords = datasets.line_vertices(datasets.river_geometry_by_ref(city.name, "w-1"))
    mask, surface = flood.river_flood_mask(grid, coords, level_m=5.0, mode="absolute")
    assert surface is None
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


def test_flood_schema_accepts_each_single_origin(city):
    from app.schemas import FloodScenario

    base = {"city_id": city.name, "level_m": 2.0}
    FloodScenario(**base, source={"lng": 85.2, "lat": 27.2})
    FloodScenario(**base, river_id="w-1")
    FloodScenario(**base, river_path=[{"lng": 85.1, "lat": 27.1}, {"lng": 85.3, "lat": 27.3}])
    FloodScenario(**base, river_path=[])


def test_flood_schema_rejects_zero_or_two_origins(city):
    from pydantic import ValidationError

    from app.schemas import FloodScenario

    base = {"city_id": city.name, "level_m": 2.0}
    with pytest.raises(ValidationError):
        FloodScenario(**base)  # none of source / river_id / river_path
    with pytest.raises(ValidationError):
        FloodScenario(**base, source={"lng": 85.2, "lat": 27.2}, river_id="w-1")
    with pytest.raises(ValidationError):
        FloodScenario(**base, river_id="w-1", river_path=[{"lng": 85.1, "lat": 27.1}])


def test_run_river_accepts_drawn_path(city):
    """A planner-drawn channel floods like an OSM river, purely from its path."""
    grid = datasets.load_city_dem(city.name)
    c_lng, c_lat = datasets.city_meta(city.name)["center"]
    path = [
        (c_lng - 0.4, c_lat - 0.4),
        (c_lng, c_lat),
        (c_lng + 0.4, c_lat + 0.4),
    ]
    result = flood.run_river(grid, path, level_m=6.0, mode="rise")
    assert not result["dry"]
    assert result["stats"]["cells_flooded"] > 0
    centre_r, centre_c = grid.cell(c_lng, c_lat)
    assert result["mask"][centre_r, centre_c]  # low point collects the rise


def test_d8_flow_direction_points_downhill():
    # Plane rising toward the east: each non-edge cell points to a strictly
    # lower (westward) neighbour and never uphill.
    elev = np.tile(np.arange(8, dtype=float), (6, 1))
    flow = flood._d8_flow_dir(elev)
    assert (flow[:, 0] == -1).all()  # no strictly lower neighbour on the edge
    for r in range(1, 5):  # interior rows keep D8 destinations in-bounds
        for c in range(1, 8):
            code = int(flow[r, c])
            assert code >= 0
            dr, dc = flood._NEIGH8[code]
            nr, nc = r + dr, c + dc
            assert 0 <= nr < 6 and 0 <= nc < 8
            assert elev[nr, nc] == elev[r, c] - 1  # the steepest drop
            assert dc == -1  # never chooses an uphill column


def test_d8_flow_converges_into_pit():
    rs, cs = np.indices((9, 9))
    elev = np.sqrt(((rs - 4) ** 2 + (cs - 4) ** 2).astype(float))
    flow = flood._d8_flow_dir(elev)
    assert flow[4, 4] == -1  # the pit is a sink
    assert int(flow[3, 4]) in (5, 6, 7)  # south rim routes toward the pit
    assert int(flow[4, 3]) in (3, 4, 7)  # east rim routes toward the pit


def test_upstream_catchment_distances_grow_upstream():
    # Radial terrain toward a central pit: every cell drains into the pit,
    # and the network distance grows the farther a cell sits upstream.
    rs, cs = np.indices((9, 9))
    elev = np.sqrt(((rs - 4) ** 2 + (cs - 4) ** 2).astype(float))
    flow = flood._d8_flow_dir(elev)
    seeds = np.zeros_like(elev, dtype=bool)
    seeds[4, 4] = True
    dist, catchment = flood._upstream_catchment(elev, flow, seeds)
    assert catchment.all()
    assert dist[4, 4] == 0.0
    assert dist[0, 4] == 4.0
    assert dist[0, 4] > dist[1, 4] > 0.0


def test_flow_accumulation_weighted_upstream():
    rs, cs = np.indices((9, 9))
    elev = np.sqrt(((rs - 4) ** 2 + (cs - 4) ** 2).astype(float))
    flow = flood._d8_flow_dir(elev)
    acc = flood._flow_accumulation(elev, flow)
    assert acc[4, 4] == 81.0   # every cell drains through the pit
    assert acc[0, 0] == 1.0    # rim corners are bare headwaters
    assert acc.max() == 81.0
    assert acc[3, 4] > acc[0, 4]  # deeper gaps accrue more upstream weight


def test_point_source_floods_downhill_not_uphill():
    # Terrain falls from north (row 0, high) to south (row n-1, low).
    n = 20
    res = 0.05
    elev = ((n - np.indices((n, n))[0]).astype(float) * 0.5).astype(np.float32)
    grid = DemGrid(elev, 85.0, 27.0, res, res)
    mask, _ = flood.flood_mask(grid, *grid.cell_center(6, 10), level_m=0.5, mode="rise")
    assert mask[6, 10]
    assert mask.sum() > 0
    assert mask[15, 10]
    assert mask[:5, :].sum() == 0  # uphill of the source stays dry


def test_tributary_adds_volume_when_draining_into_main(city):
    grid = datasets.load_city_dem(city.name)
    coords = datasets.line_vertices(datasets.river_geometry_by_ref(city.name, "w-1"))
    base = flood.run_river(grid, coords, level_m=3.0, mode="rise")
    assert base["stats"]["tributaries"] == 0

    res = grid.res_lng
    c_lng, c_lat = datasets.city_meta(city.name)["center"]
    trib = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [c_lng - 3 * res, c_lat + 6 * res],
                [c_lng - 2 * res, c_lat + 5 * res],
            ],
        },
    }
    richer = flood.run_river(grid, coords, level_m=3.0, mode="rise", water_features=[trib])
    assert richer["stats"]["tributaries"] > 0
    assert richer["stats"]["volume_m3"] > base["stats"]["volume_m3"]
    # tributaries add both water and simulated time
    assert richer["stats"]["sim_steps"] >= base["stats"]["sim_steps"]


def test_erosion_flux_step_conserves_volume():
    rng = np.random.default_rng(3)
    elev = rng.integers(0, 100, (12, 12)).astype(np.float32)
    depth = rng.random((12, 12)).astype(np.float32) * 2.0
    out = flood._flux_ca_step(elev, depth)
    assert np.all(out > -1e-5)  # never exports more than a cell holds
    assert np.isclose(out.sum(), depth.sum(), rtol=1e-4)  # nothing disappears


def test_inflow_plan_matches_declared_volume(city):
    grid = datasets.load_city_dem(city.name)
    coords = datasets.line_vertices(datasets.river_geometry_by_ref(city.name, "w-1"))
    seeds = flood._channel_seeds(grid, coords)
    flow = flood._d8_flow_dir(grid.elev)
    plan = flood._inflow_plan(grid, grid.elev, flow, seeds, None, 3.0, "rise")
    cell_area = grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0)
    assigned = float((plan["d_cell"].astype(np.float64) * cell_area).sum())
    assert np.isclose(assigned, plan["volume_m3"], rtol=0.02)  # per-cell shares sum to the volume
    assert plan["n_steps"] >= flood._MIN_STEPS


def test_rivers_in_separate_valleys_stay_disjoint_until_overtopped():
    # Flat DEM with a high N-S ridge splitting it into two valleys.
    n = 20
    res = 0.05
    elev = np.full((n, n), 10.0, dtype=np.float32)
    elev[:, 10:12] = 80.0  # the ridge
    grid = DemGrid(elev, 85.0, 27.0, res, res)

    coords_a = [(85.0 + 3 * res, 27.0 + 5 * res), (85.0 + 5 * res, 27.0 + 5 * res)]
    coords_b = [(85.0 + 15 * res, 27.0 + 5 * res), (85.0 + 17 * res, 27.0 + 5 * res)]

    mask_a, _ = flood.river_flood_mask(grid, coords_a, level_m=1.0, mode="rise")
    mask_b, _ = flood.river_flood_mask(grid, coords_b, level_m=1.0, mode="rise")
    assert mask_a.sum() > 0 and mask_b.sum() > 0
    assert not (mask_a & mask_b).any()          # ridge keeps them separate
    assert mask_a[:, 10:].sum() == 0            # A confined to its valley
    assert mask_b[:, :12].sum() == 0            # B confined to its valley

    big_a, _ = flood.river_flood_mask(grid, coords_a, level_m=5000.0, mode="rise")
    assert big_a[:, 10:12].sum() > 0            # overtopped ridge floods both sides
    assert big_a.sum() > mask_a.sum()


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


def test_quake_region_clip_limits_zones_to_basin(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    region = grid.region_mask(20.0)  # inner half of the bowl only
    full = earthquake.quake_zones(grid, centre[0], centre[1], 7.0, 10.0)
    clipped = earthquake.quake_zones(grid, centre[0], centre[1], 7.0, 10.0, region=region)
    full_area = sum(
        shape(f["geometry"]).area for band in full.values() for f in band["features"]
    )
    clipped_area = sum(
        shape(f["geometry"]).area for band in clipped.values() for f in band["features"]
    )
    assert full_area > 0.0
    assert 0.0 < clipped_area < full_area


def test_flood_region_clip_trims_outer_extent(city):
    grid = datasets.load_city_dem(city.name)
    centre = tuple(datasets.city_meta(city.name)["center"])
    region = grid.region_mask(11.0)  # small pool around the bowl floor
    full = flood.run(grid, *centre, level_m=25.0, mode="rise")
    clipped = flood.run(grid, *centre, level_m=25.0, mode="rise", region=region)
    assert not clipped["dry"]
    n_clip = clipped["stats"]["cells_flooded"]
    assert 0 < n_clip < full["stats"]["cells_flooded"]


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


def _tile_pixel_lng(lng_min: float, lng_max: float, j: int) -> float:
    return lng_min + (lng_max - lng_min) * (j + 0.5) / terrain_tiles.TILE


def _tile_pixel_lat(z: int, y: int, j: int) -> float:
    n = float(2**z)
    f = (y + (j + 0.5) / terrain_tiles.TILE) / n
    return np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * f))))


def _decode_elev(rgb: np.ndarray, row: int, col: int) -> float:
    pix = col * 3
    return (
        float(rgb[row, pix]) * 256.0
        + float(rgb[row, pix + 1])
        + float(rgb[row, pix + 2]) / 256.0
        - 32768.0
    )


def _centre_tile(grid: DemGrid, z: int) -> tuple[int, int]:
    lng = (grid.min_lng + grid.max_lng) / 2.0
    lat = (grid.min_lat + grid.max_lat) / 2.0
    n = 2**z
    x = int((lng + 180.0) / 360.0 * n)
    py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, int(py) if not math.isnan(py) else 0


def test_terrain_tile_roundtrips_terrarium(city):
    """End-to-end: the tile's centre pixel equals a direct DEM sample at the
    exact Mercator-exact position of that pixel (CRS + mercator row + encoder
    all agree to sub-metre precision, not the old ±60 m tolerance)."""
    grid = datasets.load_city_dem(city.name)
    z = 10
    x, y = _centre_tile(grid, z)
    data = terrain_tiles.tile(city.name, z, x, y)
    assert data is not None
    w, h, (mode, rgb) = decode_png_rgb(data)
    assert (mode, w, h) == (2, terrain_tiles.TILE, terrain_tiles.TILE)
    c = terrain_tiles.TILE // 2
    cx = _tile_pixel_lng(*terrain_tiles.tile_bbox(z, x, y)[::2], c)
    cy = _tile_pixel_lat(z, y, c)
    expected = float(
        terrain_tiles._sample(grid, np.array([cx]), np.array([cy]))[0]
    )
    got = _decode_elev(rgb, c, c)
    assert abs(got - expected) < 1.0
    # a tile far outside the DEM (and its padding) must return None, as must a
    # tile below the source minimum zoom.
    assert terrain_tiles.tile(city.name, z, 0, 0) is None
    assert terrain_tiles.tile(city.name, 4, 0, 0) is None


def test_terrain_sample_hits_cell_centres(city):
    """The DEM-cell-centre convention: sampling exactly a grid centre returns
    that cell's elevation (no half-cell offset drift)."""
    grid = datasets.load_city_dem(city.name)
    nrows, ncols = grid.elev.shape
    r, c = nrows // 2, ncols // 2
    lng, lat = grid.cell_center(r, c)
    got = float(terrain_tiles._sample(grid, np.array([lng]), np.array([lat]))[0])
    assert abs(got - float(grid.elev[r, c])) < 0.01


def test_terrain_tile_padded_coverage(city):
    """Tiles inside the padded coverage box but outside the DEM extent are
    served as edge-clamped continuation (never a flat-0 void), while tiles
    beyond the padding 404."""
    grid = datasets.load_city_dem(city.name)
    z = 10
    n = float(2**z)
    width = 360.0 / n
    # The tile immediately west of the DEM: entirely outside the DEM, but its
    # east edge still sits inside the padded box, so it must be served.
    x = int((grid.min_lng + 180.0) / 360.0 * n) - 1
    pad_lng_min = grid.min_lng - (grid.max_lng - grid.min_lng) * terrain_tiles.PAD_FRAC
    assert (x + 1) * width - 180.0 <= grid.min_lng  # fully outside the DEM
    assert (x + 1) * width - 180.0 > pad_lng_min  # but inside the padding
    lat = (grid.min_lat + grid.max_lat) / 2.0
    py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    y = int(py)
    data = terrain_tiles.tile(city.name, z, x, y)
    assert data is not None
    w, h, (_, rgb) = decode_png_rgb(data)
    assert (w, h) == (terrain_tiles.TILE, terrain_tiles.TILE)
    # centre pixel matches the (edge-clamped) direct sample exactly
    c = terrain_tiles.TILE // 2
    cx = _tile_pixel_lng(*terrain_tiles.tile_bbox(z, x, y)[::2], c)
    cy = _tile_pixel_lat(z, y, c)
    expected = float(
        terrain_tiles._sample(grid, np.array([cx]), np.array([cy]))[0]
    )
    got = _decode_elev(rgb, c, c)
    assert abs(got - expected) < 1.0
    # fully outside the padded box: no coverage
    assert terrain_tiles.tile(city.name, z, 0, 0) is None