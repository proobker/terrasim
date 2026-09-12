"""Loading of bundled, preprocessed demo datasets.

Each city lives in ``data/bundles/<city_id>/`` and contains:

- ``city.json``        display metadata (name, mode, center, bounds, zoom)
- ``dem.meta.json``    grid georeferencing
- ``dem.npz``          elevation raster (``elev``)
- ``buildings.geojson`` / ``roads.geojson`` / ``facilities.geojson``
"""

from __future__ import annotations

import json
from pathlib import Path

from app.engine.grid import DemGrid, load_dem

DATA_ROOT = Path(
    __import__("os").environ.get("TERRASIM_DATA", Path(__file__).resolve().parents[2] / "data" / "bundles")
)

LAYER_FILES = ("buildings.geojson", "roads.geojson", "facilities.geojson")


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


def load_layer(city_id: str, kind: str) -> dict:
    """Return a GeoJSON FeatureCollection for buildings/roads/facilities."""
    if kind not in ("buildings", "roads", "facilities"):
        raise ValueError(f"unknown layer kind: {kind}")
    with (_city_dir(city_id) / f"{kind}.geojson").open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_assets(city_id: str) -> dict[str, list[dict]]:
    """Load buildings/roads/facilities as a list of lightweight asset dicts.

    Each dict carries ``id``, ``name``, ``kind`` and ``type`` (the mapped
    OSM ''building'' / ''highway'' / amenity tag).
    """
    assets: dict[str, list[dict]] = {}
    for kind in ("buildings", "roads", "facilities"):
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