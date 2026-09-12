"""Preprocess and cache demo city bundles for terrasim.

Downloads OpenStreetMap data (Overpass API) and an elevation raster
(Mapzen Terrarium tiles) for a set of curated cities, then writes compact
bundles under ``data/bundles/<city_id>/``:

- ``city.json``         display metadata + attribution
- ``dem.meta.json``     grid georeferencing
- ``dem.npz``           elevation raster
- ``buildings.geojson`` / ``roads.geojson`` / ``facilities.geojson``

Usage (from the backend directory):

    uv run --group dev python ../scripts/fetch_data.py --all
    uv run --group dev python ../scripts/fetch_data.py --city kathmandu

Attribution:
- Map data © OpenStreetMap contributors (ODbL): https://www.openstreetmap.org/copyright
- Elevation: Mapzen terrain tiles (Terrarium), public-domain sourced.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / "data" / "bundles"

USER_AGENT = "terrasim-hackathon/0.1 (terrasim-resilience@example.com)"
OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
OVERPASS_TIMEOUT = 90
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
        "bounds": [85.24, 27.62, 85.44, 27.78],
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
BUILDING_MAX = 2500
ROAD_MAX = 2500
FACILITY_MAX = 500


def post_overpass(query: str, endpoint_order: list[str] | None = None, min_elements: int = 0) -> dict:
    """POST a query to the healthiest Overpass mirror, with retries.

    Endpoints are notoriously flaky; we rotate mirrors and back off
    between attempts. A result is returned as soon as it parses as JSON
    and carries at least ``min_elements`` elements — a low bar that still
    rejects the "healthy but empty" failure mode of some mirrors. When no
    mirror clears the bar, the largest response is returned.
    """
    endpoints = endpoint_order or OVERPASS_ENDPOINTS
    last_error: str | None = None
    best: dict | None = None
    for attempt in range(2 * len(endpoints)):
        url = endpoints[attempt % len(endpoints)]
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
            if "elements" in payload and (count >= min_elements or (not payload["elements"] and min_elements == 0)):
                time.sleep(0.8)  # be polite to the mirror
                return payload
            if best is None or count > len(best.get("elements", [])):
                best = payload
            last_error = f"{url}: only {count} elements (wanted {'any' if min_elements == 0 else min_elements})"
        except Exception as exc:  # transient mirror failure
            last_error = f"{url}: {exc!r}"
        time.sleep(5 + 10 * attempt)
    if best is not None:
        return best
    raise RuntimeError(f"all Overpass mirrors failed: {last_error}")


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


def fetch_osm(bounds: list[float]) -> dict:
    w, s, e, n = bounds
    bbox = f"({s:.4f},{w:.4f},{n:.4f},{e:.4f})"
    roads_query = (
        "[out:json][timeout:120];"
        '(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]'
        f"{bbox};);"
        f"out geom {ROAD_MAX};"
    )
    buildings_query = (
        "[out:json][timeout:120];"
        f"(way[\"building\"]{bbox};);"
        f"out geom {BUILDING_MAX};"
    )
    return {
        "buildings": post_overpass_any(buildings_query, min_elements=1),
        "roads": post_overpass_any(roads_query, min_elements=1),
        "facilities_result": fetch_facilities(bounds),
    }


def element_centroid(element: dict) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return element["lon"], element["lat"]
    center = element.get("center")
    if center:
        return center["lon"], center["lat"]
    return None


def to_features(elements: list[dict], geom_attr: str | None, center_only: bool) -> list[dict]:
    features = []
    for el in elements:
        props: dict = {"name": el.get("tags", {}).get("name"),
                       "type": el.get("tags", {}).get("building") or el.get("tags", {}).get("amenity") or el.get("tags", {}).get("highway")}
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
            elif len(coords) >= 4:
                gtype, gcoords = "Polygon", coords + [coords[0]]
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
        if not coords:
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


def build_city(city_id: str, force: bool = False) -> None:
    cfg = CITIES[city_id]
    out = BUNDLES / city_id
    out.mkdir(parents=True, exist_ok=True)

    print(f"[{city_id}] fetching OSM (overpass, mirror rotation)...")
    osm = fetch_osm(cfg["bounds"])

    buildings = to_features(osm["buildings"].get("elements", []), "geometry", False)
    buildings = filter_buildings(buildings)
    roads = to_features(osm["roads"].get("elements", []), "geometry", False)
    facilities = to_features(osm["facilities_result"], None, True)
    facilities = facilities[:FACILITY_MAX]

    for name, fc in (
        ("buildings", buildings),
        ("roads", roads),
        ("facilities", facilities),
    ):
        (out / f"{name}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": fc}), encoding="utf-8"
        )
        print(f"  {name}: {len(fc)}")

    print(f"[{city_id}] fetching DEM (terrarium z=11) and resampling...")
    dem, meta = fetch_dem(cfg["bounds"])
    np.savez(out / "dem.npz", elev=dem)
    (out / "dem.meta.json").write_text(json.dumps(meta), encoding="utf-8")

    city = {
        "id": city_id,
        "name": cfg["name"],
        "mode": cfg["mode"],
        "status": cfg["status"],
        "center": [(cfg["bounds"][0] + cfg["bounds"][2]) / 2, (cfg["bounds"][1] + cfg["bounds"][3]) / 2],
        "bounds": cfg["bounds"],
        "zoom": cfg["zoom"],
        "grid": {"ncols": dem.shape[1], "nrows": dem.shape[0], "res_deg": RES_DEG},
        "attribution": [
            "Map data © OpenStreetMap contributors (ODbL)",
            "Elevation: Mapzen terrain tiles (Terrarium)",
        ],
    }
    (out / "city.json").write_text(json.dumps(city, indent=2), encoding="utf-8")
    print(f"[{city_id}] done -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build terrasim demo data bundles.")
    parser.add_argument("--all", action="store_true", help="build every configured city")
    parser.add_argument("--city", help="build a single city by id")
    args = parser.parse_args()

    BUNDLES.mkdir(parents=True, exist_ok=True)
    targets = list(CITIES) if args.all else ([args.city] if args.city else [])
    if not targets:
        parser.error("pass --all or --city <id>")
    for city_id in targets:
        if city_id not in CITIES:
            parser.error(f"unknown city: {city_id}")
        build_city(city_id)


if __name__ == "__main__":
    main()