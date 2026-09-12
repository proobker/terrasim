"""Preprocess and cache demo city bundles for terrasim.

Downloads OpenStreetMap data (Overpass API) and an elevation raster
(Mapzen Terrarium tiles) for a set of curated cities, then writes compact
bundles under ``data/bundles/<city_id>/``:

- ``city.json``         display metadata + attribution
- ``dem.meta.json``     grid georeferencing
- ``dem.npz``           elevation raster
- ``buildings.geojson`` / ``roads.geojson`` / ``facilities.geojson``
- ``water.geojson``     river/stream/canal centerlines (for flood sources)
- ``rim.geojson``       valley-bowl outline (iso-line of the DEM at the city's
                        ``valley_cap_m``), used to clip hazard overlays to the
                        actual geographic basin instead of the grid rectangle

Usage (from the backend directory):

    uv run --group dev python ../scripts/fetch_data.py --all
    uv run --group dev python ../scripts/fetch_data.py --city kathmandu

Attribution:
- Map data © OpenStreetMap contributors (ODbL): https://www.openstreetmap.org/copyright
- Elevation: Mapzen terrain tiles (Terrarium), public-domain sourced.
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import math
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image
from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / "data" / "bundles"

USER_AGENT = "terrasim-hackathon/0.1 (terrasim-resilience@example.com)"
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
OVERPASS_TIMEOUT = 40
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"

# Amenity types grouped into small per-type queries so a single failed
# request can never stall the whole facilities bundle.
FACILITY_TYPES = {
    "hospital": "hospital",
    "clinic": "clinic",
    "school": "school",
    "higher_ed": "college|university",
    "fire_station": "fire_station",
    "police": "police",
    "shelter": "shelter|community_centre",
}

# name, mode, status, [w, s, e, n]
CITIES = {
    "kathmandu": {
        "name": "Kathmandu",
        "mode": "existing",
        "status": "urban core + surrounding valley hills",
        # Dense OSM feature fetch stays on the urban core box.
        "bounds": [85.24, 27.62, 85.44, 27.78],
        # The valley theatre: the geomorphologic bowl used for the DEM grid,
        # terrain tiles, hazard simulation and the default map view.
        "hazard_bounds": [85.15, 27.54, 85.47, 27.75],
        # Rim threshold (m asl): cells below this are "the valley". The bowl
        # floor sits around 1,300-1,360 m; the surrounding hills rise above
        # 1,500 m, so 1,450 m traces the rim cleanly.
        "valley_cap_m": 1450.0,
        "zoom": 13,
    },
    "pokhara": {
        "name": "Pokhara",
        "mode": "new",
        "status": "valley floor + lakeside, suitable for planning demos",
        "bounds": [83.90, 28.14, 84.08, 28.30],
        "zoom": 12,
    },
}

RES_DEG = 0.0003  # ~30-33 m cell at Nepal latitudes
BUILDING_MAX = 4500  # target total, accumulated across chunked fetches
ROAD_MAX = 4500
WATER_MAX = 300
FACILITY_MAX = 500


def chunk_bboxes(bounds: list[float], splits: int = 3) -> list[tuple[float, float, float, float]]:
    """Split a bounds box into a 3x3-ish grid of smaller bboxes.

    Overpass mirrors degrade `out geom` geometry on very large extracts;
    tiny chunks reliably return full coordinates.
    """
    w, s, e, n = bounds
    lat_edges = [s + (n - s) * i / splits for i in range(splits + 1)]
    lng_edges = [w + (e - w) * i / splits for i in range(splits + 1)]
    chunks = []
    for a in range(splits):
        for b in range(splits):
            s0, n0 = lat_edges[a], lat_edges[a + 1]
            w0, e0 = lng_edges[b], lng_edges[b + 1]
            chunks.append((w0, s0, e0, n0))
    return chunks

def _bbox_str(w: float, s: float, e: float, n: float) -> str:
    return f"({s:.4f},{w:.4f},{n:.4f},{e:.4f})"


def merge_elements(target: dict[int, dict], incoming: list[dict]) -> None:
    """Merge by id, preferring the version with richer geometry."""
    for el in incoming:
        existing = target.get(el["id"])
        if existing is None:
            target[el["id"]] = el
            continue
        if len(el.get("geometry", [])) > len(existing.get("geometry", [])):
            target[el["id"]] = el


def fetch_osm(bounds: list[float]) -> dict:
    buildings: dict[int, dict] = {}
    roads: dict[int, dict] = {}
    water: dict[int, dict] = {}
    for w0, s0, e0, n0 in chunk_bboxes(bounds, splits=2):
        bbox = _bbox_str(w0, s0, e0, n0)
        buildings_query = (
            "[out:json][timeout:120];"
            f"(way[\"building\"]{bbox};);"
            "out center 4000;"
        )
        roads_query = (
            "[out:json][timeout:120];"
            '(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]'
            f"{bbox};);"
            "out geom 3000;"
        )
        water_query = (
            "[out:json][timeout:120];"
            f'(way["waterway"~"^(river|stream|canal)$"]{bbox};);'
            "out geom 2000;"
        )
        try:
            merge_elements(buildings, post_overpass_any(buildings_query, min_elements=1).get("elements", []))
        except RuntimeError:
            print("  !! buildings chunk unavailable, skipped")
        time.sleep(1)
        try:
            merge_elements(roads, post_overpass_any(roads_query, min_elements=1).get("elements", []))
        except RuntimeError:
            print("  !! roads chunk unavailable, skipped")
        time.sleep(1)
        try:
            merge_elements(water, post_overpass_any(water_query, min_elements=1).get("elements", []))
        except RuntimeError:
            print("  !! water chunk unavailable, skipped")
        time.sleep(1)
        if len(buildings) >= BUILDING_MAX and len(roads) >= ROAD_MAX:
            break
    return {
        "buildings": {"elements": list(buildings.values())},
        "roads": {"elements": list(roads.values())},
        "water": {"elements": list(water.values())},
        "facilities_result": fetch_facilities(bounds),
    }


def post_overpass(query: str, endpoint_order: list[str] | None = None, min_elements: int = 0) -> dict:
    """POST a query to a healthy Overpass mirror.

    Mirrors reject bursts: try each mirror exactly once (in a shuffled
    order), keep the most complete response, and never retry the same
    mirror in a loop. A response parsing as JSON with >= ``min_elements``
    elements is returned immediately; otherwise the largest response wins
    and a hard failure raises.
    """
    endpoints = endpoint_order or OVERPASS_ENDPOINTS
    best: dict | None = None
    last_error: str | None = None
    for url in endpoints:
        body = urllib.parse.urlencode({"data": query}).encode()
        request = urllib.request.Request(
            url,
            data=body,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=OVERPASS_TIMEOUT) as resp:
                payload = json.loads(resp.read())
            count = len(payload.get("elements", []))
            if "elements" in payload and count >= min_elements:
                time.sleep(0.8)
                return payload
            if best is None or count > len(best.get("elements", [])):
                best = payload
            last_error = f"{url}: only {count} elements (wanted at least {min_elements})"
        except Exception as exc:  # transient mirror failure
            last_error = f"{url}: {exc!r}"
        time.sleep(1.5)
    if best is None:
        raise RuntimeError(f"all Overpass mirrors failed: {last_error}")
    if min_elements > 0 and not best.get("elements"):
        # Rather than fail the whole build, callers may treat this as a skip.
        raise RuntimeError(f"every mirror returned empty for a non-empty query ({last_error})")
    return best


def post_overpass_any(query: str, min_elements: int = 0) -> dict:
    from random import shuffle

    order = list(OVERPASS_ENDPOINTS)
    shuffle(order)
    return post_overpass(query, order, min_elements)


def fetch_facilities(bounds: list[float]) -> list[dict]:
    """Query facilities per amenity type so failures stay small."""
    w, s, e, n = bounds
    bbox = f"({s:.4f},{w:.4f},{n:.4f},{e:.4f})"
    elements: dict[int, dict] = {}
    for key, pattern in FACILITY_TYPES.items():
        query = (
            '[out:json][timeout:60];'
            f'(nwr["amenity"~"{pattern}"]{bbox};);'
            "out center 300;"
        )
        try:
            result = post_overpass_any(query)
        except RuntimeError:
            print(f"  !! facilities/{key}: mirrors unavailable, skipped")
            continue
        for el in result.get("elements", []):
            elements[el["id"]] = el
        print(f"  facilities/{key}: {len(result.get('elements', []))}")
    return list(elements.values())


def element_centroid(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return element["lon"], element["lat"]
    center = element.get("center")
    if center:
        return center["lon"], center["lat"]
    return None


def to_features(elements: list[dict], geom_attr: str | None, center_only: bool, keep_lines: bool = False, extra_tags: tuple[str, ...] = (), add_id: bool = False) -> list[dict]:
    features = []
    for el in elements:
        props: dict = {"name": el.get("tags", {}).get("name"),
                       "type": el.get("tags", {}).get("building") or el.get("tags", {}).get("amenity") or el.get("tags", {}).get("highway")}
        for tag in extra_tags:
            val = el.get("tags", {}).get(tag)
            if val:
                props[tag] = val
        if add_id:
            props["id"] = el["id"]
        if center_only:
            pt = element_centroid(el)
            if pt is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {k: v for k, v in props.items() if v},
                    "geometry": {"type": "Point", "coordinates": list(pt)},
                }
            )
        else:
            geom = el.get(geom_attr or "")
            coords = [[p["lon"], p["lat"]] for p in geom] if geom else None
            if not coords:
                continue
            if len(coords) == 2:
                gtype, gcoords = "LineString", coords
            elif len(coords) >= 4 and not keep_lines:
                # GeoJSON Polygon coordinates = [ring, ...]
                gtype, gcoords = "Polygon", [coords + [coords[0]]]
            elif len(coords) >= 4:
                gtype, gcoords = "LineString", coords
            else:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {k: v for k, v in props.items() if v},
                    "geometry": {"type": gtype, "coordinates": gcoords},
                }
            )
    return features


def filter_buildings(features: list[dict], max_area_m2: float = 40.0) -> list[dict]:
    """Keep the largest buildings; drop sliver footprints below an area."""
    def area(feature) -> float:
        coords = feature["geometry"]["coordinates"]
        if feature["geometry"]["type"] != "Polygon" or not coords:
            return 0.0
        ring = coords[0]
        n = len(ring)
        if n < 3:
            return 0.0
        s = 0.0
        for i in range(n - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            s += x1 * y2 - x2 * y1
        deg_area = abs(s) / 2.0
        return deg_area * (111320.0) ** 2  # rough degree area -> m^2

    sized = [(f, area(f)) for f in features if area(f) >= max_area_m2]
    sized.sort(key=lambda t: t[1], reverse=True)
    return [f for f, _ in sized]


# ---------------------------------------------------------------------------
# Water normalisation: merge river fragments, unify naming
# ---------------------------------------------------------------------------

_SNAP_DEG = 50.0 / 111320.0      # ~50 m in degrees
# Same-stem, same-name fragments are one physical river even where OSM has
# unmapped gaps (measured gaps: Seti up to 9 km). City bounds are only ~20 km
# wide, so 20 km means "any same-named fragments in this extract merge".
_SAME_STEM_MERGE_M = 20_000.0
_FUZZY_RATIO = 0.85                # min difflib.SequenceMatcher ratio for fuzzy stem match
# Folded forms included (khola->kola etc. after aspirate fold)
_HYDRONYMS = frozenset({
    "river", "khola", "kholso", "nadi", "nahar",
    "nala", "gandaki", "khahare", "kulo",
    "kola", "kolso", "kahare",
})
# Aspirate/double-consonant transliteration folds (applied sequentially)
_TRANS_FOLDS = [("chh", "ch"), ("tth", "t"), ("ph", "f"), ("kh", "k"), ("gh", "g")]


def _water_stem(name: str | None) -> tuple[str | None, str]:
    """Normalise a waterway name to a merge key (stem) and display form.

    Returns ``(None, "")`` for unnamed features.  Devanagari-only names use
    their full lowercase form (bracket markers like ``(क)`` preserved).  Latin
    names are transliteration-folded and stripped of generic hydronyms.
    """
    if not name or not name.strip():
        return None, ""
    raw = name.strip()

    # Devanagari-only: keep full name as stem (honest; distinct branches stay separate)
    has_ascii = any("a" <= c.lower() <= "z" for c in raw)
    if not has_ascii:
        return raw.lower(), raw

    # Latin path
    s = unicodedata.normalize("NFD", raw)
    s = "".join(c for c in s if ord(c) < 128).lower().strip()
    s = re.sub(r"\(.*?\)", " ", s).strip()
    for src, dst in _TRANS_FOLDS:
        s = s.replace(src, dst)
    tokens = s.split()
    if not tokens:
        return raw.lower(), raw
    filtered = [t for t in tokens if t not in _HYDRONYMS]
    stem = " ".join(filtered) if filtered else " ".join(tokens)
    return stem, raw


def _line_endpoints(geometry: dict) -> list[tuple[float, float]]:
    coords = geometry.get("coordinates", [])
    gtype = geometry.get("type")
    out: list[tuple[float, float]] = []
    if gtype == "LineString" and coords:
        out.append(tuple(coords[0][:2]))
        out.append(tuple(coords[-1][:2]))
    elif gtype == "MultiLineString":
        for part in coords:
            if part:
                out.append(tuple(part[0][:2]))
                out.append(tuple(part[-1][:2]))
    return out


def _count_segs(geometry: dict) -> int:
    coords = geometry.get("coordinates", [])
    gtype = geometry.get("type")
    if gtype == "LineString":
        return max(0, len(coords) - 1)
    if gtype == "MultiLineString":
        return sum(max(0, len(part) - 1) for part in coords)
    return 0


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) * 111320.0


def _has_deva(s: str) -> bool:
    return any(ord(c) > 127 for c in s)


def _stem_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    if not a or not b:
        return False
    # Devanagari stems match exactly only: "(क)" / "(ख)" branch markers are real
    # distinct watercourses, and transliteration variance does not apply.
    if _has_deva(a) or _has_deva(b):
        return False
    # prefix match (e.g. "seti" matches "seti gandaki")
    if a.startswith(b) or b.startswith(a):
        return True
    if len(a) >= 4 and len(b) >= 4:
        if difflib.SequenceMatcher(None, a, b).ratio() >= _FUZZY_RATIO:
            return True
    return False


def _emit_group(
    member_indices: list[int],
    feat_meta: list[dict],
    features: list[dict],
    out: list[dict],
) -> None:
    """Emit a single merged feature from a group of member indices."""
    all_parts: list[list] = []
    for i in member_indices:
        geom = features[i].get("geometry", {})
        coords = geom.get("coordinates", [])
        gtype = geom.get("type")
        if gtype == "LineString" and coords:
            all_parts.append(coords)
        elif gtype == "MultiLineString":
            all_parts.extend(coords)
    if not all_parts:
        return

    best_i = max(member_indices, key=lambda i: feat_meta[i]["segs"])
    canonical_name = feat_meta[best_i]["disp"] or feat_meta[best_i]["name_raw"]

    type_segs: dict[str, int] = defaultdict(int)
    for i in member_indices:
        t = feat_meta[i]["waterway"] or "river"
        type_segs[t] += feat_meta[i]["segs"]
    dominant_type = max(type_segs, key=type_segs.get)

    if len(all_parts) == 1:
        geometry = {"type": "LineString", "coordinates": all_parts[0]}
    else:
        geometry = {"type": "MultiLineString", "coordinates": all_parts}

    props: dict = {
        "name": canonical_name,
        "waterway": dominant_type,
        "id": features[best_i]["properties"].get("id"),
        "type": dominant_type,
    }
    out.append({"type": "Feature", "properties": props, "geometry": geometry})


def normalize_water(features: list[dict]) -> list[dict]:
    """Merge water features that are segments of the same physical river.

    Same-stem + same-family features within 1 km (or sharing a snap-point)
    become one MultiLineString.  Unnamed segments join a named group only
    when they share a snap-point (connect-only adoption).
    """
    if not features:
        return features

    meta: list[dict] = []
    for f in features:
        props = f.get("properties", {})
        name = props.get("name")
        waterway = props.get("waterway", "river")
        stem, disp = _water_stem(name)
        family = "canal" if waterway == "canal" else "water"
        meta.append({
            "stem": stem,
            "disp": disp,
            "family": family,
            "points": _line_endpoints(f.get("geometry", {})),
            "segs": _count_segs(f.get("geometry", {})),
            "name_raw": name,
            "waterway": waterway,
        })

    n = len(meta)

    # -- union-find -------------------------------------------------------
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # -- phase 1: snap connectivity (all features, 50 m) -----------------
    grid: dict[tuple[int, int], int] = {}
    for i, m in enumerate(meta):
        for pt in m["points"]:
            gx, gy = int(round(pt[0] / _SNAP_DEG)), int(round(pt[1] / _SNAP_DEG))
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    j = grid.get((gx + dx, gy + dy))
                    if j is not None and j != i:
                        union(i, j)
            grid[(gx, gy)] = i

    # -- phase 2: compat-stem 1 km gap (named features only) --------------
    stem_feats: dict[str | None, list[int]] = defaultdict(list)
    for i, m in enumerate(meta):
        if m["stem"] is not None:
            stem_feats[m["stem"]].append(i)

    # build compat sets among stems
    stem_keys = [k for k in stem_feats if k is not None]
    compat_map: dict[str, set[str]] = defaultdict(set)
    for a, b in combinations(stem_keys, 2):
        if _stem_compatible(a, b):
            compat_map[a].add(b)
            compat_map[b].add(a)

    visited: set[str] = set()
    for sk in stem_keys:
        if sk in visited:
            continue
        # BFS compat cluster
        cluster: set[str] = set()
        queue = [sk]
        while queue:
            s = queue.pop()
            if s in cluster:
                continue
            cluster.add(s)
            visited.add(s)
            for nb in compat_map.get(s, set()):
                if nb not in cluster:
                    queue.append(nb)

        cluster_idx = [i for s in cluster for i in stem_feats[s]]
        if len(cluster_idx) < 2:
            continue

        # bucket by UF component
        comp_buckets: dict[int, list[int]] = defaultdict(list)
        for i in cluster_idx:
            comp_buckets[find(i)].append(i)
        bucket_list = list(comp_buckets.values())
        if len(bucket_list) < 2:
            continue

        # min gap between each pair of buckets
        def _min_gap(a: list[int], b: list[int]) -> float:
            pts_a = [pt for i in a for pt in meta[i]["points"]]
            pts_b = [pt for i in b for pt in meta[i]["points"]]
            best = float("inf")
            for pa in pts_a:
                for pb in pts_b:
                    d = _dist_m(pa, pb)
                    if d < best:
                        best = d
                        if best <= _SAME_STEM_MERGE_M:
                            return best
            return best

        for i, j in combinations(range(len(bucket_list)), 2):
            if _min_gap(bucket_list[i], bucket_list[j]) <= _SAME_STEM_MERGE_M:
                union(bucket_list[i][0], bucket_list[j][0])

    # -- phase 3: emit ----------------------------------------------------
    uf_groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        uf_groups[find(i)].append(i)

    # pre-compute global canonical display per stem
    stem_best_disp: dict[str, str] = {}
    for stem, idxs in stem_feats.items():
        if not stem:
            continue
        best = max(idxs, key=lambda i: meta[i]["segs"])
        stem_best_disp[stem] = meta[best]["disp"] or meta[best]["name_raw"]

    out: list[dict] = []
    for members in uf_groups.values():
        stems_present = {meta[i]["stem"] for i in members}
        named_stems = [s for s in stems_present if s is not None]
        has_unnamed = None in stems_present

        if not named_stems:
            # fully unnamed component: keep each way as-is
            for i in members:
                out.append(features[i])
            continue

        # partition named stems into compatibility groups
        stem_parent = {s: s for s in named_stems}

        def sfind(s: str) -> str:
            while stem_parent[s] != s:
                stem_parent[s] = stem_parent[stem_parent[s]]
                s = stem_parent[s]
            return s

        def sunion(a: str, b: str) -> None:
            ra, rb = sfind(a), sfind(b)
            if ra != rb:
                stem_parent[rb] = ra

        for a, b in combinations(named_stems, 2):
            if _stem_compatible(a, b):
                sunion(a, b)

        compat_groups: dict[str, list[str]] = defaultdict(list)
        for s in named_stems:
            compat_groups[sfind(s)].append(s)

        # group members per compat group; unnamed go to the dominant group
        group_members: dict[str, list[int]] = defaultdict(list)
        group_segs: dict[str, int] = defaultdict(int)
        for root, stems in compat_groups.items():
            member_idxs = [i for i in members if meta[i]["stem"] in stems]
            group_members[root] = member_idxs
            group_segs[root] = sum(meta[i]["segs"] for i in member_idxs)
        dominant = max(group_segs, key=group_segs.get)

        # canonical display name per compat group (unify casing/spelling)
        canon: dict[str, str] = {}
        for root, stems in compat_groups.items():
            member_idxs = group_members[root]
            rep = max(
                stems,
                key=lambda s: sum(meta[i]["segs"] for i in member_idxs if meta[i]["stem"] == s),
            )
            canon[root] = stem_best_disp.get(rep) or stem_best_disp[stems[0]]

        for root, stems in compat_groups.items():
            # partition by family so canals never absorb {river,stream} ways
            fam: dict[str, list[int]] = defaultdict(list)
            fam_names: set[str] = set()
            for i in group_members[root]:
                fam[meta[i]["family"]].append(i)
                fam_names.add(meta[i]["family"])
            if root == dominant and has_unnamed:
                for i in members:
                    if meta[i]["stem"] is None and meta[i]["family"] in fam_names:
                        fam[meta[i]["family"]].append(i)
                has_unnamed = False
            for family, idxs in fam.items():
                named_idx = [i for i in idxs if meta[i]["stem"] is not None]
                if not named_idx:
                    # only unnamed ways in this family: keep them individual
                    out.extend(features[i] for i in idxs)
                    continue
                rep = max(named_idx, key=lambda i: meta[i]["segs"])
                rep_stem = meta[rep]["stem"]
                canon = stem_best_disp.get(rep_stem) or stem_best_disp[rep_stem]
                for i in idxs:
                    meta[i]["disp"] = canon
                _emit_group(idxs, meta, features, out)

    return out


# ---------------------------------------------------------------------------
# Terrarium elevation tiles
# ---------------------------------------------------------------------------

def slippy_tile(lng: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    xtile = int((lng + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def tile_extent(xt: int, yt: int, z: int) -> tuple[float, float, float, float]:
    n = 2**z
    w = xt / n * 360.0 - 180.0
    e = (xt + 1) / n * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * yt / n))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (yt + 1) / n))))
    return w, lat_bottom, e, lat_top


def decode_terrarium(path_bytes: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(path_bytes)).convert("RGB")
    arr = np.asarray(img, dtype=np.float64)
    elev = arr[:, :, 0] * 256.0 + arr[:, :, 1] + arr[:, :, 2] / 256.0 - 32768.0
    elev[np.abs(elev) > 12000] = np.nan  # missing data
    return elev


def fetch_tile(xt: int, yt: int, z: int) -> np.ndarray | None:
    url = f"{TERRARIUM}/{z}/{xt}/{yt}.png"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                return decode_terrarium(resp.read())
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2)


def world_pixels(lngs: np.ndarray, lats: np.ndarray, z: int) -> tuple[np.ndarray, np.ndarray]:
    n = 2**z * 256.0
    px = (lngs + 180.0) / 360.0 * n
    py = (1.0 - np.arcsinh(np.tan(np.radians(lats))) / math.pi) / 2.0 * n
    return px, py


def bilinear(a: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    h, w = a.shape
    orig_shape = px.shape
    px = px.ravel()
    py = py.ravel()
    x0 = np.floor(px).astype(int)
    y0 = np.floor(py).astype(int)
    x0 = np.clip(x0, 0, w - 2)
    y0 = np.clip(y0, 0, h - 2)
    x1, y1 = x0 + 1, y0 + 1
    wx = px - x0
    wy = py - y0
    v00 = a[y0, x0]
    v10 = a[y0, x1]
    v01 = a[y1, x0]
    v11 = a[y1, x1]
    out = (v00 * (1 - wx) + v10 * wx) * (1 - wy) + (v01 * (1 - wx) + v11 * wx) * wy
    return out.reshape(orig_shape)


def fetch_dem(bounds: list[float], z: int = 11) -> tuple[np.ndarray, dict]:
    """Return (elev grid, meta) resampled onto a lat/lng-aligned grid."""
    w, s, e, n = bounds

    # Covering tile range
    xt_min, yt_min = slippy_tile(w, n, z)
    xt_max, yt_max = slippy_tile(e, s, z)

    tiles = {}
    for xt in range(xt_min, xt_max + 1):
        for yt in range(yt_min, yt_max + 1):
            arr = fetch_tile(xt, yt, z)
            if arr is not None:
                tiles[(xt, yt)] = arr
    if not tiles:
        raise RuntimeError("no elevation tiles retrieved")

    # Build the assembled raster in pixel space (top row = north).
    x0_pix = xt_min * 256
    y0_pix = yt_min * 256
    width = (xt_max - xt_min + 1) * 256
    height = (yt_max - yt_min + 1) * 256
    assembled = np.full((height, width), np.nan)
    for (xt, yt), arr in tiles.items():
        assembled[(yt - yt_min) * 256 : (yt - yt_min + 1) * 256,
                  (xt - xt_min) * 256 : (xt - xt_min + 1) * 256] = arr

    # Target grid aligned to the bundle bounds.
    ncols = int(round((e - w) / RES_DEG)) + 1
    nrows = int(round((n - s) / RES_DEG)) + 1

    lats_c = s + (nrows - np.arange(nrows) - 0.5) * RES_DEG
    lngs_c = w + (np.arange(ncols) + 0.5) * RES_DEG
    lng_grid, lat_grid = np.meshgrid(lngs_c, lats_c)

    px, py = world_pixels(lng_grid, lat_grid, z)
    dem = bilinear(assembled, px - x0_pix, py - y0_pix)

    # Fill NaN seams (missing tiles / ocean) with the local median.
    valid = np.isfinite(dem)
    if not valid.all():
        median = np.nanmedian(dem[np.isfinite(dem)])
        dem[~valid] = median if np.isfinite(median) else 0.0

    meta = {"min_lng": w, "min_lat": s, "res_lng": RES_DEG, "res_lat": RES_DEG}
    return dem.astype(np.float32), meta


def rim_geojson(dem: np.ndarray, meta: dict, cap_m: float | None) -> dict | None:
    """Extract the valley-bowl outline from the DEM.

    The bowl is the 4-connected lowland region below ``cap_m``. Its exterior
    ring is the ``rim`` — the line where the valley floor meets the enclosing
    hills — written as a simplified LineString feature. Returns None when the
    region is empty or fills the whole grid (the rim would be the box itself,
    which buys nothing).
    """
    if cap_m is None:
        return None
    mask = dem < cap_m
    if not mask.any():
        return None
    h, w = mask.shape
    boxes = []
    for r in range(h):
        row = np.flatnonzero(mask[r])
        if row.size == 0:
            continue
        lat1 = meta["min_lat"] + (h - r) * meta["res_lat"]
        lat0 = lat1 - meta["res_lat"]
        start = int(row[0])
        prev = start

        def emit(a: int, b: int) -> None:
            boxes.append(
                box(
                    meta["min_lng"] + a * meta["res_lng"],
                    lat0,
                    meta["min_lng"] + (b + 1) * meta["res_lng"],
                    lat1,
                )
            )

        for c in row[1:].tolist():
            if c == prev + 1:
                prev = c
                continue
            emit(start, prev)
            start = prev = c
        emit(start, prev)
    if not boxes:
        return None

    merged = unary_union(boxes)
    # Donut holes and watershed-spill islands are possible; the rim we want is
    # the outline of the dominant lowland body (the valley floor itself).
    if merged.geom_type == "Polygon":
        body = merged
    elif merged.geom_type == "MultiPolygon":
        body = max(merged.geoms, key=lambda g: g.area)
    else:
        return None
    ext = body.exterior
    if ext is None or ext.length <= 0:
        return None
    ring = list(ext.coords)
    grid_corners = {
        (meta["min_lng"], meta["min_lat"]),
        (meta["min_lng"], meta["min_lat"] + h * meta["res_lat"]),
        (meta["min_lng"] + w * meta["res_lng"], meta["min_lat"]),
        (meta["min_lng"] + w * meta["res_lng"], meta["min_lat"] + h * meta["res_lat"]),
    }
    if any(tuple(map(lambda v: round(v, 6), p)) in grid_corners for p in ring):
        return None  # bowl fills the grid; a rectangle rim adds nothing

    # An open basin (valley opening to an adjacent plain) hugs the DEM border:
    # the ring is really the grid edge, not a valley outline. Reject it.
    eps = max(meta["res_lng"], meta["res_lat"]) / 2
    edge_points = sum(
        1
        for p in ring
        if (
            abs(p[0] - meta["min_lng"]) <= eps
            or abs(p[0] - (meta["min_lng"] + w * meta["res_lng"])) <= eps
            or abs(p[1] - meta["min_lat"]) <= eps
            or abs(p[1] - (meta["min_lat"] + h * meta["res_lat"])) <= eps
        )
    )
    if ring and edge_points / len(ring) > 0.35:
        return None

    tol = max(meta["res_lng"], meta["res_lat"]) * 4
    coords = [list(p) for p in ext.simplify(tol).coords]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"class": "valley-rim", "elev_m": cap_m},
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        ],
    }


def build_city(city_id: str, force: bool = False) -> None:
    cfg = CITIES[city_id]
    out = BUNDLES / city_id
    out.mkdir(parents=True, exist_ok=True)

    print(f"[{city_id}] fetching OSM (overpass, mirror rotation)...")
    osm = fetch_osm(cfg["bounds"])

    buildings = to_features(
        osm["buildings"].get("elements", []),
        None,
        True,
        extra_tags=("height", "building:levels"),
        add_id=True,
    )
    buildings = buildings[:BUILDING_MAX]
    roads = to_features(osm["roads"].get("elements", []), "geometry", False, keep_lines=True)
    water = to_features(
        osm["water"].get("elements", []),
        "geometry",
        False,
        keep_lines=True,
        extra_tags=("waterway",),
        add_id=True,
    )
    water = normalize_water(water)
    water = water[:WATER_MAX]
    facilities = to_features(osm["facilities_result"], None, True)
    facilities = facilities[:FACILITY_MAX]

    for name, fc in (
        ("buildings", buildings),
        ("roads", roads),
        ("water", water),
        ("facilities", facilities),
    ):
        (out / f"{name}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": fc}), encoding="utf-8"
        )
        print(f"  {name}: {len(fc)}")

    hazard_bounds = cfg.get("hazard_bounds", cfg["bounds"])
    print(f"[{city_id}] fetching DEM (terrarium z=11) over {hazard_bounds}...")
    dem, meta = fetch_dem(hazard_bounds)
    np.savez(out / "dem.npz", elev=dem)
    (out / "dem.meta.json").write_text(json.dumps(meta), encoding="utf-8")

    cap_m = cfg.get("valley_cap_m")
    rim = rim_geojson(dem, meta, cap_m)
    if rim:
        (out / "rim.geojson").write_text(json.dumps(rim), encoding="utf-8")
        print(f"  rim: {len(rim['features'])} feature(s) at {cap_m} m")
    else:
        (out / "rim.geojson").unlink(missing_ok=True)

    city = {
        "id": city_id,
        "name": cfg["name"],
        "mode": cfg["mode"],
        "status": cfg["status"],
        "center": [(cfg["bounds"][0] + cfg["bounds"][2]) / 2, (cfg["bounds"][1] + cfg["bounds"][3]) / 2],
        "bounds": cfg["bounds"],
        "hazard_bounds": hazard_bounds,
        "zoom": cfg["zoom"],
        "grid": {"ncols": dem.shape[1], "nrows": dem.shape[0], "res_deg": RES_DEG},
        "attribution": [
            "Map data © OpenStreetMap contributors (ODbL)",
            "Elevation: Mapzen terrain tiles (Terrarium)",
        ],
    }
    if cap_m is not None:
        city["valley_cap_m"] = cap_m
    (out / "city.json").write_text(json.dumps(city, indent=2), encoding="utf-8")
    print(f"[{city_id}] done -> {out}")


def normalize_existing(city_id: str) -> int:
    """Re-run water normalisation on a committed bundle without re-fetching."""
    path = BUNDLES / city_id / "water.geojson"
    fc = json.loads(path.read_text(encoding="utf-8"))
    before = len(fc["features"])
    fc["features"] = normalize_water(fc["features"])
    path.write_text(json.dumps(fc), encoding="utf-8")
    print(f"[{city_id}] water: {before} -> {len(fc['features'])} features")
    return len(fc["features"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build terrasim demo data bundles.")
    parser.add_argument("--all", action="store_true", help="build every configured city")
    parser.add_argument("--city", help="build a single city by id")
    parser.add_argument(
        "--normalize-water",
        action="store_true",
        help="re-run water normalization on existing bundles (no network)",
    )
    args = parser.parse_args()

    BUNDLES.mkdir(parents=True, exist_ok=True)
    targets = list(CITIES) if args.all else ([args.city] if args.city else [])
    if args.normalize_water:
        targets = (targets or list(CITIES))
        for city_id in targets:
            if city_id not in CITIES:
                parser.error(f"unknown city: {city_id}")
            normalize_existing(city_id)
        return
    if not targets:
        parser.error("pass --all, --city <id>, or --normalize-water")
    for city_id in targets:
        if city_id not in CITIES:
            parser.error(f"unknown city: {city_id}")
        build_city(city_id)


if __name__ == "__main__":
    main()