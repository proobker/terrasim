"""Request/response models for the terrasim API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    lng: float = Field(gt=-180, lt=180)
    lat: float = Field(gt=-90, lt=90)


class FloodScenario(BaseModel):
    city_id: str
    source: GeoPoint
    level_m: float = Field(default=2.0, gt=-20, lt=5000)
    mode: Literal["rise", "absolute"] = "rise"


class EarthquakeScenario(BaseModel):
    city_id: str
    epicenter: GeoPoint
    magnitude: float = Field(default=6.5, gt=0, lt=10)
    depth_km: float = Field(default=10.0, ge=0, lt=300)


class SuitabilityRequest(BaseModel):
    city_id: str