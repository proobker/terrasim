"""Simplified scenario-based earthquake exposure model.

Implements a documented, deliberately simple attenuation proxy. Ground
motion proxies decay with 3D distance from the epicentre and grow with
magnitude. Output bands are *estimated relative intensity zones*, not
predictions of damage. See plans.md §9 for the scientific honesty framing.
"""

from __future__ import annotations

import numpy as np

from app.engine.grid import DemGrid, mask_to_polygons

# Band labels, ordered from most to least intense.
BANDS: list[str] = ["high", "medium_high", "medium", "low"]
# Thresholds on the intensity index (0..1) for each band.
BAND_THRESHOLDS: list[float] = [0.32, 0.20, 0.10, 0.04]

# Model constants (documented simplifications).
REFERENCE_MAGNITUDE = 6.0
REFERENCE_DISTANCE_KM = 8.0
DECAY_POWER = 1.5
MAGNITUDE_POWER = 2.0


def intensity_index(horizontal_km: np.ndarray, depth_km: float, magnitude: float) -> np.ndarray:
    """Return an intensity index in (0, 1] for the given distances.

    I = (M / M_ref)^2 * (R0 / (R0 + D))^1.5  where D = sqrt(R^2 + depth^2).
    """
    depth_km = max(depth_km, 0.0)
    d = np.sqrt(np.asarray(horizontal_km, dtype=np.float64) ** 2 + depth_km**2)
    mag_factor = (max(magnitude, 0.0) / REFERENCE_MAGNITUDE) ** MAGNITUDE_POWER
    dist_factor = (REFERENCE_DISTANCE_KM / (REFERENCE_DISTANCE_KM + d)) ** DECAY_POWER
    return np.minimum(1.0, mag_factor * dist_factor)


def band_for(index: float) -> str | None:
    for band, threshold in zip(BANDS, BAND_THRESHOLDS):
        if index >= threshold:
            return band
    return None


def intensity_band_thresholds() -> dict:
    return {band: threshold for band, threshold in zip(BANDS, BAND_THRESHOLDS)}


def horizontal_km(grid: DemGrid, lng: float, lat: float) -> np.ndarray:
    """Distance in km from a point to every raster cell centre."""
    rows = np.arange(grid.nrows)
    cols = np.arange(grid.ncols)
    lats = grid.max_lat - (rows + 0.5) * grid.res_lat
    lngs = grid.min_lng + (cols + 0.5) * grid.res_lng

    lat_grid, lng_grid = np.meshgrid(lats, lngs, indexing="ij")
    d_lng = (lng_grid - lng) * grid.km_per_deg_lng((lat_grid + lat) / 2.0)
    d_lat = (lat_grid - lat) * 111.32
    return np.sqrt(d_lng**2 + d_lat**2)


def quake_labels(grid: DemGrid, epicenter_lng: float, epicenter_lat: float, magnitude: float, depth_km: float) -> np.ndarray:
    """Return a per-cell integer band label (0=none .. 4=high)."""
    r_km = horizontal_km(grid, epicenter_lng, epicenter_lat)
    index_flat = intensity_index(r_km, depth_km, magnitude).ravel()
    labels = np.zeros(index_flat.size, dtype=np.int8)
    for band_idx, threshold in enumerate(BAND_THRESHOLDS):
        labels = np.where(
            np.logical_and(index_flat >= threshold, labels == 0),
            band_idx + 1,
            labels,
        )
    return labels.reshape(grid.nrows, grid.ncols)


def quake_zones(grid: DemGrid, epicenter_lng: float, epicenter_lat: float, magnitude: float, depth_km: float) -> dict:
    """Return zone overlay layers (one FeatureCollection per band + metadata)."""
    labels = quake_labels(grid, epicenter_lng, epicenter_lat, magnitude, depth_km)
    layers: dict[str, dict] = {}
    for band_idx, band_name in enumerate(BANDS, start=1):
        mask = labels == band_idx
        polygons = mask_to_polygons(mask, grid)
        layers[band_name] = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"class": band_name}, "geometry": polygon}
                for polygon in polygons
            ],
        }
    return layers


def quake_zones_at(lng: float, lat: float, grid: DemGrid, epicenter_lng: float, epicenter_lat: float, magnitude: float, depth_km: float) -> tuple[str | None, float]:
    """Band + index for a single coordinate (used for asset exposure)."""
    r = np.sqrt(
        ((lng - epicenter_lng) * grid.km_per_deg_lng(lat)) ** 2
        + ((lat - epicenter_lat) * 111.32) ** 2
    )
    index = float(intensity_index(r, depth_km, magnitude))
    return band_for(index), index


def run(grid: DemGrid, epicenter_lng: float, epicenter_lat: float, magnitude: float, depth_km: float) -> dict:
    zones = quake_zones(grid, epicenter_lng, epicenter_lat, magnitude, depth_km)
    labels = quake_labels(grid, epicenter_lng, epicenter_lat, magnitude, depth_km)
    area_by_band = {}
    for band_idx, band_name in enumerate(BANDS, start=1):
        cells = int((labels == band_idx).sum())
        area_by_band[band_name] = round(
            cells * grid.cell_area_m2((grid.min_lat + grid.max_lat) / 2.0) / 1e6, 2
        )
    return {
        "zones": zones,
        "bands": intensity_band_thresholds(),
        "area_km2": area_by_band,
    }