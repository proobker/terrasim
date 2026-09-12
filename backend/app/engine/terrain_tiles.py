"""Terrarium-encoded DEM raster tiles served from a city bundle.

The elevation raster in each bundle (``dem.npz`` + ``dem.meta.json``) is
re-shipped as 512x512 RGB PNG tiles for maplibre-gl ``raster-dem`` sources using
the Mapzen Terrarium encoding:

    elevation_m = (R * 256 + G + B / 256) - 32768

Rows are sampled on the tile's Mercator-exact latitude grid (not linear
latitude) so each elevation lands on the exact ground spot maplibre's terrain
mesh draws it at. Coverage is the DEM extent plus a ``PAD_FRAC`` margin: tiles
inside it are served edge-clamped, which keeps the terrain mesh from falling
back to maplibre's flat 0 m plane while the camera is over the valley.

The encoder is dependency-free (stdlib zlib/struct) so the runtime server does
not require Pillow.
"""

from __future__ import annotations

import math
import struct
import zlib
from functools import lru_cache

import numpy as np

from app.engine.grid import DemGrid

# DEM tiles are served at 512 px a side. maplibre v6 terrain composites each
# terrain tile to a 2x render-to-texture of the *declared* source tileSize, so a
# 512 px tile yields a 1024 px RTT and a 128x128 mesh over a *smaller* per-tile
# ground area — i.e. a denser mesh that hugs the valley walls instead of
# sketching huge stretched quads on steep slopes.
TILE = 512
MIN_ZOOM = 7
MAX_ZOOM = 15
# Coverage padding past the DEM extent, as a fraction of the DEM's own size.
# Any tile inside the padded box is served (edge-clamped once outside the DEM),
# so the terrain mesh never falls back to maplibre's flat 0 m fallback while the
# fitted/tilted camera is over the valley. Tiles far outside still 404 and keep
# the cache bounded.
PAD_FRAC = 0.5


def _grid(city_id: str) -> DemGrid:
    from app import datasets

    return datasets.load_city_dem(city_id)


def tile_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(lng_min, lat_min, lng_max, lat_max) for a slippy tile."""
    n = float(2**z)
    lng_min = x / n * 360.0 - 180.0
    lng_max = (x + 1) / n * 360.0 - 180.0
    lat_rad_max = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat_rad_min = math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n)))
    return lng_min, math.degrees(lat_rad_min), lng_max, math.degrees(lat_rad_max)


def _encode_terrarium(elev_m: np.ndarray) -> np.ndarray:
    """Convert an elevation array (m) into an HxWx3 RGB array (uint8)."""
    v = np.clip(elev_m + 32768.0, 0.0, 65535.0)
    vi = np.floor(v).astype(np.uint32)
    frac = np.floor((v - vi) * 256.0).astype(np.uint32)
    rgb = np.empty(elev_m.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = (vi >> 8) & 0xFF
    rgb[..., 1] = vi & 0xFF
    rgb[..., 2] = frac & 0xFF
    return rgb


def _png_rgb(rgb: np.ndarray) -> bytes:
    """Minimal 8-bit RGB PNG writer (zlib + CRC, no external deps)."""
    h, w = rgb.shape[:2]
    raw = bytearray()
    for i in range(h):
        raw.append(0)  # filter type: None
        raw.extend(rgb[i].tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def _padded_extent(grid: DemGrid) -> tuple[float, float, float, float]:
    """Coverage box: the DEM extent inflated by ``PAD_FRAC`` on each side.

    Tiles intersecting this box are always served (clamped to the DEM edge
    outside it), which keeps maplibre's terrain mesh from dropping to its flat
    0 m fallback while the fitted/tilted camera is anywhere near the DEM.
    """
    pad_lng = (grid.max_lng - grid.min_lng) * PAD_FRAC
    pad_lat = (grid.max_lat - grid.min_lat) * PAD_FRAC
    return (
        grid.min_lng - pad_lng,
        grid.min_lat - pad_lat,
        grid.max_lng + pad_lng,
        grid.max_lat + pad_lat,
    )


def _tile_lats(z: int, y: int) -> np.ndarray:
    """Mercator-exact latitude for every pixel row of tile (z, x, y).

    A slippy tile is uniform in Web Mercator *y*, not in geographic latitude.
    Sampling linearly in lat (as a naive re-sampler does) places each pixel's
    elevation at a slightly different ground spot than where maplibre's terrain
    mesh draws that pixel, skewing the surface against the draped base map. This
    computes the true row latitude so each elevation lands exactly on its mesh
    vertex.
    """
    n = float(2**z)
    f = (y + (np.arange(TILE, dtype=np.float64) + 0.5) / TILE) / n
    return np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * f))))


def _sample(grid: DemGrid, lngs: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Bilinearly sample the DEM at arbitrary lng/lat arrays (cell-centre)."""
    rows, cols = grid.elev.shape
    c = (lngs - grid.min_lng) / grid.res_lng - 0.5
    r = (grid.max_lat - lats) / grid.res_lat - 0.5
    r0 = np.floor(r).astype(np.int64)
    c0 = np.floor(c).astype(np.int64)
    fr = (r - r0).astype(np.float32)
    fc = (c - c0).astype(np.float32)
    r1, c1 = r0 + 1, c0 + 1

    def get(rr: np.ndarray, cc: np.ndarray) -> np.ndarray:
        return grid.elev[
            np.clip(rr, 0, rows - 1), np.clip(cc, 0, cols - 1)
        ]

    v00 = get(r0, c0)
    v10 = get(r1, c0)
    v01 = get(r0, c1)
    v11 = get(r1, c1)
    top = v00 * (1.0 - fc) + v01 * fc
    bot = v10 * (1.0 - fc) + v11 * fc
    return top * (1.0 - fr) + bot * fr


def tile(city_id: str, z: int, x: int, y: int) -> bytes | None:
    """Return Terrarium PNG bytes for a tile, or ``None`` outside coverage."""
    if not (MIN_ZOOM <= z <= MAX_ZOOM):
        return None
    grid = _grid(city_id)
    lng_min, lat_min, lng_max, lat_max = tile_bbox(z, x, y)
    pad_lng_min, pad_lat_min, pad_lng_max, pad_lat_max = _padded_extent(grid)
    if (
        lng_max <= pad_lng_min
        or lng_min >= pad_lng_max
        or lat_max <= pad_lat_min
        or lat_min >= pad_lat_max
    ):
        return None
    js = np.arange(TILE, dtype=np.float64) + 0.5
    lngs = lng_min + (lng_max - lng_min) * (js / TILE)
    lats = _tile_lats(z, y)
    lng_grid, lat_grid = np.meshgrid(lngs, lats)
    elev = _sample(grid, lng_grid, lat_grid)
    return _png_rgb(_encode_terrarium(elev))


@lru_cache(maxsize=2048)
def tile_bytes(city_id: str, z: int, x: int, y: int) -> bytes | None:
    """Cached ``tile()`` — keyed on tile coordinates, not raw bytes."""
    return tile(city_id, z, x, y)


def clear_cache() -> None:
    tile_bytes.cache_clear()