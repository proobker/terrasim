"""Building vector tiles: block styling pinned to the look the frontend used to
compute (buildings3d.ts), a valid MVT encoding (decoded back with a tiny
reader), and the tile endpoint."""

import gzip

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.engine import building_tiles as bt
from app.main import app

client = TestClient(app)


# Expected values produced by the frontend's former estimateHeight and
# RANDOM_TINTS pick (buildings3d.ts, before blocks moved to vector tiles); all
# 362,022 Kathmandu blocks matched it exactly when the port landed.
@pytest.mark.parametrize(
    ("props", "height"),
    [
        ({"height": "4"}, 4.0),
        ({"building:levels": "3"}, 9.5),
        ({"type": "hospital"}, 16.0),
        ({"type": "yes"}, 6.5),
        ({"height": "250"}, 6.5),
        ({"height": "12.5 m"}, 12.5),
        ({"height": "."}, 6.5),
    ],
)
def test_estimate_height_matches_frontend(props, height):
    assert bt.estimate_height(props) == height


@pytest.mark.parametrize(
    ("seed", "color"),
    [("30962401", "#94A3B8"), ("56688295", "#FBBF24"), ("1", "#94A3B8")],
)
def test_tint_matches_frontend(seed, color):
    assert bt.tint(seed) == color


# --- minimal MVT reader ---------------------------------------------------------


def _varint(buf, i):
    out = shift = 0
    while True:
        b = buf[i]
        i += 1
        out |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return out, i


def _fields(buf):
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        num, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v, i = buf[i : i + 8], i + 8
        elif wt == 2:
            n, i = _varint(buf, i)
            v, i = buf[i : i + n], i + n
        else:
            raise AssertionError(f"unexpected wire type {wt}")
        yield num, v


def _packed(buf):
    i, out = 0, []
    while i < len(buf):
        v, i = _varint(buf, i)
        out.append(v)
    return out


def _rings(cmds):
    """Decode MVT polygon commands into absolute rings."""
    x = y = i = 0
    rings, ring = [], []
    while i < len(cmds):
        cid, count = cmds[i] & 7, cmds[i] >> 3
        i += 1
        if cid == 7:
            rings.append(ring)
            ring = []
            continue
        for _ in range(count):
            dx, dy = cmds[i], cmds[i + 1]
            i += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            ring.append((x, y))
    return rings


def _area(ring):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))


def _busiest_z15_tile(city):
    n = 2**15
    tx = np.floor(city.cx * n).astype(np.int64)
    ty = np.floor(city.cy * n).astype(np.int64)
    keys, counts = np.unique(tx * n + ty, return_counts=True)
    k = int(keys[np.argmax(counts)])
    return 15, k // n, k % n


def test_tile_decodes_to_source_footprints():
    city = bt.city("kathmandu")
    z, x, y = _busiest_z15_tile(city)
    raw = bt.encode_tile(city, z, x, y)
    (num, layer), = list(_fields(raw))
    assert num == 3
    layer_fields = list(_fields(layer))
    assert dict((n, v) for n, v in layer_fields if n in (1, 5, 15)) == {1: b"buildings", 5: 4096, 15: 2}
    keys = [v.decode() for n, v in layer_fields if n == 3]
    assert keys == ["height", "color", "name"]
    features = [v for n, v in layer_fields if n == 2]
    assert len(features) > 1000

    ids = {int(i): b for b, i in enumerate(city.ids) if i >= 0}
    n = 2**z
    for feat in features[:200]:
        f = dict((num, v) for num, v in _fields(feat))
        assert f[3] == 3  # POLYGON
        rings = _rings(_packed(f[4]))
        assert _area(rings[0]) > 0  # MVT exterior winding
        b = ids[f[1]]
        # Decoded exterior ~ the source ring quantised to the tile grid.
        s, e = city.ring_start[city.bld_ring[b]], city.ring_start[city.bld_ring[b] + 1]
        src = np.stack(((city.px[s:e] * n - x) * 4096, (city.py[s:e] * n - y) * 4096), axis=1)
        for px, py in rings[0]:
            assert np.min(np.hypot(src[:, 0] - px, src[:, 1] - py)) <= 0.75


def test_each_building_lands_in_exactly_one_tile():
    city = bt.city("pokhara")
    z = 14
    total = 0
    for _, x, y in bt.tiles_over((83.85, 28.10, 84.15, 28.35), z):
        raw = bt.encode_tile(city, z, x, y)
        if raw:
            (_, layer), = list(_fields(raw))
            total += sum(1 for n, _ in _fields(layer) if n == 2)
    assert 0 < total <= len(city.ids)
    assert total >= 0.95 * len(city.ids)  # only footprints collapsed at z14 drop


def test_building_tile_endpoint():
    city = bt.city("kathmandu")
    z, x, y = _busiest_z15_tile(city)
    r = client.get(f"/api/cities/kathmandu/tiles/buildings/{z}/{x}/{y}.pbf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-protobuf"
    assert r.content == bt.encode_tile(city, z, x, y)  # TestClient un-gzips
    assert client.get("/api/cities/kathmandu/tiles/buildings/15/0/0.pbf").status_code == 204
    assert client.get(f"/api/cities/kathmandu/tiles/buildings/9/{x >> 6}/{y >> 6}.pbf").status_code == 204
    assert client.get("/api/cities/nowhere/tiles/buildings/15/0/0.pbf").status_code == 204


def test_gzip_tile_is_cached():
    city = bt.city("kathmandu")
    z, x, y = _busiest_z15_tile(city)
    a = bt.tile_gzip("kathmandu", z, x, y)
    assert a is bt.tile_gzip("kathmandu", z, x, y)
    assert gzip.decompress(a) == bt.encode_tile(city, z, x, y)


@pytest.mark.parametrize("city_id", ["kathmandu", "pokhara"])
def test_committed_cache_is_fresh_regardless_of_mtime(city_id, monkeypatch):
    """A fresh git checkout can stamp the npz older than its GeoJSON; the server
    must still trust the committed cache instead of rebuilding (~900 MB peak,
    which OOM-kills a 512 MB host)."""
    import os

    from app import datasets

    src = datasets._layer_path(city_id, "buildings")
    cache = src.with_name(bt.CACHE_NAME)
    st = cache.stat()
    os.utime(cache, ns=(st.st_atime_ns, src.stat().st_mtime_ns - 10**9))

    def no_rebuild(_features):
        raise AssertionError("rebuilt the committed cache")

    monkeypatch.setattr(bt, "pack", no_rebuild)
    try:
        assert bt.ensure_cache(city_id) == cache
    finally:
        os.utime(cache, ns=(st.st_atime_ns, st.st_mtime_ns))
