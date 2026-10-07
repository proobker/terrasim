"""Loading of bundled, preprocessed demo datasets.

Each city lives in ``data/bundles/<city_id>/`` and contains:

- ``city.json``        display metadata (name, mode, center, bounds, zoom)
- ``dem.meta.json``    grid georeferencing
- ``dem.npz``          elevation raster (``elev``)
- ``buildings.geojson`` / ``roads.geojson`` / ``facilities.geojson``
- ``water.geojson``        river/stream/canal centerlines (LineStrings)
"""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from app.engine import building_tiles
from app.engine.exposure import PointAssets
from app.engine.grid import DemGrid, load_dem

DATA_ROOT = Path(
    __import__("os").environ.get("TERRASIM_DATA", Path(__file__).resolve().parents[2] / "data" / "bundles")
)

LAYER_FILES = ("buildings.geojson", "roads.geojson", "facilities.geojson", "water.geojson")


def _city_dir(city_id: str) -> Path:
    d = DATA_ROOT / city_id
    if not (d / "city.json").exists():
        raise FileNotFoundError(f"unknown city bundle: {city_id}")
    return d


def list_cities() -> list[dict]:
    cities = []
    if not DATA_ROOT.exists():
        return cities
    for child in sorted(DATA_ROOT.iterdir()):
        meta_file = child / "city.json"
        if meta_file.is_file():
            with meta_file.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
            meta.setdefault("id", child.name)
            cities.append(meta)
    return cities


def city_meta(city_id: str) -> dict:
    with (_city_dir(city_id) / "city.json").open("r", encoding="utf-8") as fh:
        meta = json.load(fh)
    meta.setdefault("id", city_id)
    return meta


def load_city_dem(city_id: str) -> DemGrid:
    return load_dem(_city_dir(city_id))


LAYER_KINDS = ("buildings", "roads", "facilities", "water", "rim")


def _layer_path(city_id: str, kind: str) -> Path:
    if kind not in LAYER_KINDS:
        raise ValueError(f"unknown layer kind: {kind}")
    path = _city_dir(city_id) / f"{kind}.geojson"
    if not path.is_file():
        raise FileNotFoundError(f"{city_id} has no {kind} layer")
    return path


def load_layer(city_id: str, kind: str) -> dict:
    """Return a GeoJSON FeatureCollection for buildings/roads/facilities/water/rim."""
    with _layer_path(city_id, kind).open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=16)
def _gzipped(path: Path, mtime_ns: int) -> bytes:
    # mtime_ns is part of the cache key so a rebuilt bundle is re-read.
    return gzip.compress(path.read_bytes(), compresslevel=5)


def layer_gzip(city_id: str, kind: str) -> tuple[bytes, str]:
    """Gzipped GeoJSON bytes of a layer file plus a validator ETag.

    The bundle files are already GeoJSON, so the API ships them as-is: parsing
    the 100 MB Kathmandu buildings file and letting FastAPI re-encode it took
    ~25 s per request; compressed bytes held in memory go out in well under one.
    """
    path = _layer_path(city_id, kind)
    stat = path.stat()
    return _gzipped(path, stat.st_mtime_ns), f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def load_assets(city_id: str) -> dict[str, list[dict] | PointAssets]:
    """Load buildings/roads/facilities for exposure.

    Roads and facilities are lists of lightweight asset dicts carrying ``id``,
    ``name``, ``kind`` and ``type`` (the mapped OSM ''highway'' / amenity tag).
    Buildings are a :class:`PointAssets` read from ``buildings.blocks.npz``:
    parsing the 100 MB Kathmandu GeoJSON per run peaked at ~900 MB, more than
    the 512 MB host has.
    """
    _layer_path(city_id, "buildings")  # FileNotFoundError for an unknown city
    pts = building_tiles.points(city_id)
    assets: dict[str, list[dict] | PointAssets] = {
        "buildings": PointAssets("buildings", pts.lng, pts.lat, pts.ids, pts.name_table, pts.name_idx)
    }
    for kind in ("roads", "facilities"):
        fc = load_layer(city_id, kind)
        items = []
        for idx, feature in enumerate(fc.get("features", [])):
            props = feature.get("properties", {}) or {}
            items.append(
                {
                    "id": props.get("id") or props.get("osm_id") or f"{kind}:{idx}",
                    "name": props.get("name"),
                    "kind": kind,
                    "type": props.get("type"),
                    "centroid": props.get("centroid"),
                    "geometry": feature.get("geometry"),
                }
            )
        assets[kind] = items
    return assets


def road_points(city_id: str) -> list[list[tuple[float, float]]]:
    """Decimal-degree coordinate lists for all roads (for suitability)."""
    fc = load_layer(city_id, "roads")
    segments: list[list[tuple[float, float]]] = []
    for feature in fc.get("features", []):
        geom = feature.get("geometry")
        if not geom:
            continue
        coords = geom.get("coordinates")
        if geom["type"] == "LineString" and coords:
            segments.append(coords)
        elif geom["type"] == "MultiLineString":
            for part in coords:
                segments.append(part)
    return segments


def line_vertices(geometry: dict | None) -> list[tuple[float, float]]:
    """Flatten a LineString/MultiLineString/Polygon geometry into (lng, lat) pairs."""
    if not geometry:
        return []
    coords = geometry.get("coordinates") or []
    gtype = geometry.get("type")
    if gtype == "LineString":
        return [(p[0], p[1]) for p in coords]
    if gtype == "MultiLineString":
        return [(p[0], p[1]) for part in coords for p in part]
    if gtype == "Polygon":
        return [(p[0], p[1]) for ring in coords for p in ring]
    return []


def rivers(city_id: str) -> list[dict]:
    """Lightweight summaries of the city's rivers (for a selection picker)."""
    try:
        fc = load_layer(city_id, "water")
    except FileNotFoundError:
        return []  # bundle built without a water layer: nothing to pick
    rows = []
    for idx, feature in enumerate(fc.get("features", [])):
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry")
        if not geometry or geometry.get("type") not in ("LineString", "MultiLineString", "Polygon"):
            continue
        rows.append(
            {
                "id": str(props.get("id") or props.get("osm_id") or f"water:{idx}"),
                "name": props.get("name"),
                "type": props.get("type") or props.get("waterway") or props.get("natural"),
            }
        )
    return rows


def river_geometry_by_ref(city_id: str, ref: str) -> dict | None:
    """Find a river feature geometry by OSM id or (case-insensitive) name."""
    fc = load_layer(city_id, "water")
    wanted = ref.strip()
    for feature in fc.get("features", []):
        props = feature.get("properties", {}) or {}
        ids = {str(props.get("id")), str(props.get("osm_id"))}
        names = {props.get("name")} if props.get("name") else set()
        if wanted in ids or (names and wanted.lower() == str(names.pop()).lower()):
            return feature.get("geometry")
    return None