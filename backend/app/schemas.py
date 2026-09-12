"""Request/response models for the terrasim API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GeoPoint(BaseModel):
    lng: float = Field(gt=-180, lt=180)
    lat: float = Field(gt=-90, lt=90)


class ScenarioAsset(BaseModel):
    kind: str
    id: str | None = None
    name: str | None = None
    lng: float
    lat: float


class FloodScenario(BaseModel):
    city_id: str
    source: GeoPoint | None = None
    river_id: str | None = None
    level_m: float = Field(default=2.0, gt=-20, lt=5000)
    mode: Literal["rise", "absolute"] = "rise"
    include_tributaries: bool = True
    assets: list[ScenarioAsset] | None = None

    @model_validator(mode="after")
    def exactly_one_origin(self) -> "FloodScenario":
        if (self.source is None) == (self.river_id is None):
            raise ValueError("provide exactly one of 'source' or 'river_id'")
        return self


class EarthquakeScenario(BaseModel):
    city_id: str
    epicenter: GeoPoint
    magnitude: float = Field(default=6.5, gt=0, lt=10)
    depth_km: float = Field(default=10.0, ge=0, lt=300)
    assets: list[ScenarioAsset] | None = None


class SuitabilityRequest(BaseModel):
    city_id: str