"""Mapbox Vector Tiles of a city's buildings, for the 3D block layer.

Kathmandu's bundle holds ~362k OSM footprints (100 MB of GeoJSON). Shipping
that to the browser meant maplibre had to structured-clone and re-tile the
whole city on every load (~15-20 s before a block appeared). Served as vector
tiles, the browser only fetches the handful of tiles in view, already cut.

Each building is assigned to exactly one tile, by its centroid, at every zoom
— footprints are tens of metres, so nothing needs clipping and no block is
drawn twice across a tile seam. Block styling (estimated height + silhouette
tint) is computed here — moved from the frontend's old buildings3d.ts
unchanged, so the look is identical; heights stay *estimated / illustrative*.

Parsing the GeoJSON costs ~40 s and ~900 MB peak, so it happens once: the
footprints are packed into ``buildings.blocks.npz`` next to the bundle (int32
coordinates at 1e-7 deg, precomputed height + tint) and the server only ever
loads that (<1 s, ~40 MB). Commit the npz with the bundle so a deploy never
rebuilds it.

The MVT encoder is dependency-free (protobuf written by hand, vectorised with
numpy), mirroring ``terrain_tiles``.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

EXTENT = 4096
LAYER = "buildings"
# Below z13 a block is a 1-2 px speck under the haze, and a z12 tile would be
# ~1.7 MB gzipped; past z15 maplibre overscales (1 unit ~ 0.2 m).
MIN_ZOOM = 13
MAX_ZOOM = 15
# Bump when the packing or styling rules change so stale caches rebuild.
CACHE_VERSION = 2
CACHE_NAME = "buildings.blocks.npz"
COORD_SCALE = 1e7  # int32 coordinates at 1e-7 deg (~1 cm)

# --- styling (the block look; formerly buildings3d.ts) ------------------------

RANDOM_TINTS = ("#60A5FA", "#A78BFA", "#FBBF24", "#FB923C", "#94A3B8")

_TYPE_TABLE = (
    (re.compile(r"(hospital|clinic|medical)"), 5),
    (re.compile(r"(school|university|college|kinderga)"), 3),
    (re.compile(r"(government|public|library|museum|office)"), 6),
    (re.compile(r"(supermarket|shop|retail|market|food|cafe|restaurant|mall)"), 2),
    (re.compile(r"(industrial|warehouse|garage|factory|storage)"), 6),
    (re.compile(r"(apartment|flats|commercial|bank|hotel)"), 8),
    (re.compile(r"(church|temple|mosque|place_of_worship)"), 6),
)


def fnv1a(s: str) -> int:
    """FNV-1a over UTF-16 code units (same as ``hash()`` in buildings3d.ts)."""
    h = 0x811C9DC5
    data = s.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _num(v: object) -> float | None:
    """JS ``num()``: the first [\\d.]+ run, read like parseFloat."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str):
        m = re.search(r"[\d.]+", v)
        lead = re.match(r"\d+\.?\d*|\.\d+", m.group()) if m else None
        return float(lead.group()) if lead else None
    return None


def _round_half(x: float) -> float:
    # Math.round(x * 2) / 2 — half-up, unlike Python's banker's round().
    return math.floor(x * 2 + 0.5) / 2


def estimate_height(props: dict) -> float:
    """Estimated block height in metres: OSM height, else levels, else type."""
    h = _num(props.get("height"))
    if h is not None and 2 <= h <= 200:
        return _round_half(min(60.0, max(3.0, h)))
    lv = _num(props.get("building:levels"))
    if lv is not None and lv >= 1:
        return _round_half(min(60.0, max(3.0, lv * 3.2)))
    t = str(props.get("type") or "").lower()
    levels = next((n for rx, n in _TYPE_TABLE if rx.search(t)), 2)
    return _round_half(min(60.0, max(3.0, levels * 3.2)))


def tint(seed: str) -> str:
    """Stable silhouette colour for a block (``RANDOM_TINTS[fnv1a(seed) % 5]``)."""
    return RANDOM_TINTS[fnv1a(seed) % len(RANDOM_TINTS)]


# --- packed city ---------------------------------------------------------------


def _rings(geometry: dict | None) -> list | None:
    if not geometry:
        return None
    if geometry.get("type") == "Polygon":
        return geometry.get("coordinates") or None
    if geometry.get("type") == "MultiPolygon":
        parts = geometry.get("coordinates") or []
        return parts[0] if parts else None
    return None


def _square(lng: float, lat: float, size_m: float, rot_deg: float) -> list:
    # Centroid-only bundles get a stylised square (10-22 m, 0/45 deg twist).
    radius = size_m / 2 * math.sqrt(2)
    base = math.radians(rot_deg) + math.pi / 4
    m_lng = 111320 * math.cos(math.radians(lat))
    pts = [
        [
            lng + math.cos(base + k * math.pi / 2) * radius / m_lng,
            lat + math.sin(base + k * math.pi / 2) * radius / 111320,
        ]
        for k in range(4)
    ]
    return [pts + [pts[0]]]


def _exposure_point(geometry: dict | None, props: dict, cx: float, cy: float) -> tuple[float, float]:
    """The one point hazard exposure samples for a building.

    Same rule exposure applied to the raw GeoJSON: a polygon's precomputed
    ``centroid`` property, a point's own coordinate, otherwise a point
    guaranteed inside the footprint (first part of a multipolygon).
    """
    gtype = (geometry or {}).get("type")
    centroid = props.get("centroid")
    if gtype == "Polygon" and isinstance(centroid, (list, tuple)) and len(centroid) == 2:
        return float(centroid[0]), float(centroid[1])
    if gtype in ("Polygon", "MultiPolygon"):
        from shapely.geometry import shape

        geom = shape(geometry)
        part = geom.geoms[0] if gtype == "MultiPolygon" else geom
        x, y = part.representative_point().coords[0]
        return float(x), float(y)
    return cx, cy


def pack(features: list[dict]) -> dict[str, np.ndarray]:
    """Pack GeoJSON building features into flat arrays (the npz payload)."""
    ids, names, heights, colors, clng, clat, alng, alat = [], [], [], [], [], [], [], []
    coords: list[list[float]] = []
    ring_len: list[int] = []
    bld_rings: list[int] = []
    for f in features:
        props = f.get("properties") or {}
        rings = _rings(f.get("geometry"))
        if rings:
            outer = rings[0]
            cx = sum(p[0] for p in outer) / len(outer)
            cy = sum(p[1] for p in outer) / len(outer)
        else:
            pt = (f.get("geometry") or {}).get("coordinates") or [0, 0]
            cx, cy = float(pt[0]), float(pt[1])
        alng_i, alat_i = _exposure_point(f.get("geometry"), props, cx, cy)
        fid = props.get("id")
        seed = str(fid) if fid is not None else f"{cx:.6f},{cy:.6f}"
        h = fnv1a(seed)
        if not rings:
            rings = _square(cx, cy, 10 + (h % 13), (h % 2) * 45)
        for ring in rings:
            coords.extend(ring)
            ring_len.append(len(ring))
        bld_rings.append(len(rings))
        ids.append(fid if isinstance(fid, int) and fid >= 0 else -1)
        names.append(str(props.get("name") or ""))
        heights.append(estimate_height(props))
        colors.append(h % len(RANDOM_TINTS))
        clng.append(cx)
        clat.append(cy)
        alng.append(alng_i)
        alat.append(alat_i)
    xy = np.rint(np.asarray(coords, dtype=np.float64) * COORD_SCALE).astype(np.int32)
    name_table, name_idx = np.unique(np.asarray(names), return_inverse=True)
    return {
        "version": np.asarray(CACHE_VERSION),
        "ids": np.asarray(ids, dtype=np.int64),
        "name_table": name_table,
        "name_idx": name_idx.astype(np.int32),
        "height": np.asarray(heights, dtype=np.float32),
        "color": np.asarray(colors, dtype=np.uint8),
        "clng": np.asarray(clng, dtype=np.float64),
        "clat": np.asarray(clat, dtype=np.float64),
        "alng": np.asarray(alng, dtype=np.float64),
        "alat": np.asarray(alat, dtype=np.float64),
        "xy": xy.reshape(-1, 2),
        "ring_len": np.asarray(ring_len, dtype=np.int32),
        "bld_rings": np.asarray(bld_rings, dtype=np.int32),
    }


def _merc(lng: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat = np.clip(lat, -85.05112878, 85.05112878)
    r = np.radians(lat)
    return (lng + 180.0) / 360.0, (1.0 - np.log(np.tan(r) + 1.0 / np.cos(r)) / math.pi) / 2.0


@dataclass
class City:
    ids: np.ndarray
    name_table: np.ndarray
    name_idx: np.ndarray
    height: np.ndarray
    color: np.ndarray
    cx: np.ndarray  # centroids, Web Mercator unit square
    cy: np.ndarray
    px: np.ndarray  # ring points, Web Mercator unit square
    py: np.ndarray
    ring_start: np.ndarray  # ring r = points ring_start[r]:ring_start[r+1]
    bld_ring: np.ndarray  # building b = rings bld_ring[b]:bld_ring[b+1]


def _from_packed(p) -> City:
    xy = p["xy"].astype(np.float64) / COORD_SCALE
    px, py = _merc(xy[:, 0], xy[:, 1])
    cx, cy = _merc(p["clng"], p["clat"])
    return City(
        ids=p["ids"],
        name_table=p["name_table"],
        name_idx=p["name_idx"],
        height=p["height"],
        color=p["color"],
        cx=cx,
        cy=cy,
        px=px,
        py=py,
        ring_start=np.concatenate(([0], np.cumsum(p["ring_len"], dtype=np.int64))),
        bld_ring=np.concatenate(([0], np.cumsum(p["bld_rings"], dtype=np.int64))),
    )


def ensure_cache(city_id: str) -> Path:
    """Path to an up-to-date ``buildings.blocks.npz``, building it if needed.

    Freshness is the source GeoJSON's byte size recorded in the npz, not
    mtimes: a git checkout stamps files in arbitrary order, so on a fresh
    deploy the committed npz often looks "older" than its GeoJSON — and the
    rebuild (~900 MB peak) gets the 512 MB host OOM-killed before it serves.
    """
    from app import datasets

    src = datasets._layer_path(city_id, "buildings")
    cache = src.with_name(CACHE_NAME)
    src_size = src.stat().st_size
    if cache.is_file():
        with np.load(cache) as p:
            if (
                int(p["version"]) == CACHE_VERSION
                and "src_size" in p.files
                and int(p["src_size"]) == src_size
            ):
                return cache
    with src.open("r", encoding="utf-8") as fh:
        packed = pack(json.load(fh).get("features") or [])
    packed["src_size"] = np.asarray(src_size, dtype=np.int64)
    tmp = cache.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, **packed)
    tmp.replace(cache)
    return cache


@lru_cache(maxsize=4)
def _city(path: Path, mtime_ns: int) -> City:
    with np.load(path) as p:
        return _from_packed(p)


def city(city_id: str) -> City:
    path = ensure_cache(city_id)
    return _city(path, path.stat().st_mtime_ns)


@dataclass(frozen=True)
class Points:
    """Per-building exposure point, id and name (rows match ``pack`` order)."""

    lng: np.ndarray
    lat: np.ndarray
    ids: np.ndarray  # OSM id, or -1 when the bundle has none
    name_table: np.ndarray
    name_idx: np.ndarray


@lru_cache(maxsize=4)
def _points(path: Path, mtime_ns: int) -> Points:
    with np.load(path) as p:
        return Points(p["alng"], p["alat"], p["ids"], p["name_table"], p["name_idx"])


def points(city_id: str) -> Points:
    """Buildings as exposure points, read from the npz (~10 MB) so a scenario
    run never parses the 100 MB GeoJSON (~900 MB peak)."""
    path = ensure_cache(city_id)
    return _points(path, path.stat().st_mtime_ns)


# --- MVT encoding -------------------------------------------------------------


def _varints(values: np.ndarray) -> tuple[bytes, np.ndarray]:
    """Protobuf base-128 varints, vectorised. Returns bytes + per-value length."""
    v = np.asarray(values, dtype=np.uint64)
    nbytes = np.ones(v.shape, dtype=np.int64)
    for k in range(1, 10):
        nbytes += v >= np.uint64(1 << (7 * k))
    owner = np.repeat(np.arange(v.size), nbytes)
    starts = np.cumsum(nbytes) - nbytes
    pos = (np.arange(owner.size) - starts[owner]).astype(np.uint64)
    out = (v[owner] >> (np.uint64(7) * pos)) & np.uint64(0x7F)
    out |= np.where(pos < (nbytes[owner] - 1).astype(np.uint64), np.uint64(0x80), np.uint64(0))
    return out.astype(np.uint8).tobytes(), nbytes


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _field(num: int, payload: bytes) -> bytes:
    """Length-delimited protobuf field (wire type 2)."""
    return _varint((num << 3) | 2) + _varint(len(payload)) + payload


def _zigzag(a: np.ndarray) -> np.ndarray:
    a = a.astype(np.int64)
    return ((a << 1) ^ (a >> 63)).astype(np.uint64)


def _seg_ranges(starts: np.ndarray, lengths: np.ndarray) -> np.ndarray:
    """Concatenated aranges [s, s+len) for each (start, length)."""
    total = int(lengths.sum())
    if total == 0:
        return np.zeros(0, dtype=np.int64)
    offs = np.cumsum(lengths) - lengths
    return np.repeat(starts - offs, lengths) + np.arange(total)


def encode_tile(c: City, z: int, x: int, y: int) -> bytes:
    """Raw (uncompressed) MVT bytes; b"" when the tile holds no building."""
    n = float(2**z)
    blds = np.nonzero((np.floor(c.cx * n) == x) & (np.floor(c.cy * n) == y))[0]
    if blds.size == 0:
        return b""

    # Rings of the selected buildings, and each ring's owner / exterior flag.
    rings_per = c.bld_ring[blds + 1] - c.bld_ring[blds]
    rings = _seg_ranges(c.bld_ring[blds], rings_per)
    ring_owner = np.repeat(np.arange(blds.size), rings_per)
    exterior = np.ones(rings.size, dtype=bool)
    exterior[1:] = ring_owner[1:] != ring_owner[:-1]

    # Quantised points, ring by ring.
    rlen = c.ring_start[rings + 1] - c.ring_start[rings]
    pts = _seg_ranges(c.ring_start[rings], rlen)
    pr = np.repeat(np.arange(rings.size), rlen)  # point -> ring
    qx = np.rint((c.px[pts] * n - x) * EXTENT).astype(np.int64)
    qy = np.rint((c.py[pts] * n - y) * EXTENT).astype(np.int64)

    # Drop consecutive duplicates (quantisation collapses tiny edges) and the
    # GeoJSON closing point — MVT closes rings with ClosePath.
    first = np.ones(pts.size, dtype=bool)
    first[1:] = pr[1:] != pr[:-1]
    keep = first.copy()
    keep[1:] |= (qx[1:] != qx[:-1]) | (qy[1:] != qy[:-1])
    qx, qy, pr = qx[keep], qy[keep], pr[keep]
    first = first[keep]
    ring_first = np.nonzero(first)[0]
    last = np.r_[ring_first[1:] - 1, qx.size - 1]
    closing = (qx[last] == qx[ring_first]) & (qy[last] == qy[ring_first]) & (last > ring_first)
    drop = np.zeros(qx.size, dtype=bool)
    drop[last[closing]] = True
    qx, qy, pr = qx[~drop], qy[~drop], pr[~drop]

    # Signed area per ring (shoelace, y down); <3 points or zero area = collapsed.
    cnt = np.bincount(pr, minlength=rings.size)
    rstart = np.cumsum(cnt) - cnt
    nxt = np.arange(qx.size) + 1
    ring_end = rstart + cnt
    nxt[nxt == ring_end[pr]] = rstart[pr][nxt == ring_end[pr]]
    area = np.bincount(pr, weights=(qx * qy[nxt] - qx[nxt] * qy).astype(np.float64), minlength=rings.size)
    ok_ring = (cnt >= 3) & (area != 0)
    # A building whose footprint collapsed is skipped; a collapsed hole just drops.
    ok_bld = np.zeros(blds.size, dtype=bool)
    ok_bld[ring_owner[exterior & ok_ring]] = True
    ok_ring &= ok_bld[ring_owner]
    sel = ok_ring[pr]
    qx, qy, pr = qx[sel], qy[sel], pr[sel]
    if qx.size == 0:
        return b""

    # MVT winding: exterior area > 0, holes < 0 — reverse rings that disagree.
    cnt = np.bincount(pr, minlength=rings.size)
    rstart = np.cumsum(cnt) - cnt
    flip = ok_ring & ((area > 0) != exterior)
    pos = np.arange(qx.size) - rstart[pr]
    src = np.where(flip[pr], rstart[pr] + cnt[pr] - 1 - pos, np.arange(qx.size))
    qx, qy = qx[src], qy[src]

    # Deltas: the cursor runs on across a building's rings and resets per feature.
    owner = ring_owner[pr]
    dx = np.diff(qx, prepend=0)
    dy = np.diff(qy, prepend=0)
    feat_first = np.ones(qx.size, dtype=bool)
    feat_first[1:] = owner[1:] != owner[:-1]
    dx[feat_first] = qx[feat_first]
    dy[feat_first] = qy[feat_first]

    # Command stream per ring: MoveTo(1) x y, LineTo(k-1) ..., ClosePath.
    good = np.nonzero(cnt > 0)[0]
    k = cnt[good]
    ring_ints = 2 * k + 3
    geom = np.empty(int(ring_ints.sum()), dtype=np.uint64)
    gstart = np.cumsum(ring_ints) - ring_ints
    geom[gstart] = (1 << 3) | 1
    geom[gstart + 3] = ((k - 1).astype(np.uint64) << np.uint64(3)) | np.uint64(2)
    geom[gstart + ring_ints - 1] = (1 << 3) | 7
    p0 = rstart[good]
    zx, zy = _zigzag(dx), _zigzag(dy)
    geom[gstart + 1] = zx[p0]
    geom[gstart + 2] = zy[p0]
    rest = _seg_ranges(p0 + 1, k - 1)  # points after MoveTo
    rest_ring = np.repeat(np.arange(good.size), k - 1)
    slot = gstart[rest_ring] + 4 + 2 * (rest - p0[rest_ring] - 1)
    geom[slot] = zx[rest]
    geom[slot + 1] = zy[rest]

    geom_bytes, geom_len = _varints(geom)
    ring_bytes = np.add.reduceat(geom_len, gstart) if gstart.size else np.zeros(0, np.int64)
    ring_boff = np.cumsum(ring_bytes) - ring_bytes
    feat_of_ring = ring_owner[good]

    # Property tables: height (double), color (string), name (string).
    heights, h_ix = np.unique(c.height[blds], return_inverse=True)
    values = [_varint((3 << 3) | 1) + struct.pack("<d", float(h)) for h in heights]
    color_base = len(values)
    values += [_field(1, t.encode()) for t in RANDOM_TINTS]
    name_ix = c.name_idx[blds]
    named = np.unique(name_ix[c.name_table[name_ix] != ""])
    name_base = len(values)
    name_val = {int(i): name_base + j for j, i in enumerate(named)}
    values += [_field(1, str(c.name_table[i]).encode("utf-8")) for i in named]

    features = []
    fr = np.searchsorted(feat_of_ring, np.arange(blds.size), side="left")
    fr_end = np.searchsorted(feat_of_ring, np.arange(blds.size), side="right")
    for b in np.nonzero(fr_end > fr)[0].tolist():
        g0 = int(ring_boff[fr[b]])
        g1 = int(ring_boff[fr_end[b] - 1] + ring_bytes[fr_end[b] - 1])
        tags = [0, int(h_ix[b]), 1, color_base + int(c.color[blds[b]])]
        nv = name_val.get(int(name_ix[b]))
        if nv is not None:
            tags += [2, nv]
        body = b""
        fid = int(c.ids[blds[b]])
        if fid >= 0:
            body += b"\x08" + _varint(fid)
        body += _field(2, b"".join(_varint(t) for t in tags))
        body += b"\x18\x03"  # type = POLYGON
        body += _field(4, geom_bytes[g0:g1])
        features.append(_field(2, body))

    layer = b"\x78\x02" + _field(1, LAYER.encode())  # version 2, name
    layer += b"".join(features)
    layer += b"".join(_field(3, k.encode()) for k in ("height", "color", "name"))
    layer += b"".join(_field(4, v) for v in values)
    layer += b"\x28" + _varint(EXTENT)
    return _field(3, layer)


@lru_cache(maxsize=4096)
def _tile_gz(path: Path, mtime_ns: int, z: int, x: int, y: int) -> bytes:
    raw = encode_tile(_city(path, mtime_ns), z, x, y)
    return gzip.compress(raw, compresslevel=6) if raw else b""


def tile_gzip(city_id: str, z: int, x: int, y: int) -> bytes:
    """Gzipped MVT bytes for a tile (b"" = empty tile). Cached per bundle."""
    if not (MIN_ZOOM <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z):
        return b""
    path = ensure_cache(city_id)
    return _tile_gz(path, path.stat().st_mtime_ns, z, x, y)


def tiles_over(bounds: tuple[float, float, float, float], z: int) -> list[tuple[int, int, int]]:
    """Slippy tile coords covering a lng/lat bounds at zoom z (for warm-up)."""
    mx, my = _merc(np.array([bounds[0], bounds[2]]), np.array([bounds[3], bounds[1]]))
    (x0, x1), (y0, y1) = (mx * 2**z).astype(int), (my * 2**z).astype(int)
    return [(z, xx, yy) for xx in range(x0, x1 + 1) for yy in range(y0, y1 + 1)]
