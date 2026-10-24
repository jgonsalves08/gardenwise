"""Loads and validates the static data in data/*.json. No live APIs."""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from . import config


class Location(BaseModel):
    id: str
    name: str
    state: str
    zone: str
    zone_num: int
    last_frost: str   # MM-DD
    first_frost: str  # MM-DD
    annual_rain_in: int
    soil_note: str
    zip_prefixes: list[str]
    source: str

    @property
    def label(self) -> str:
        return f"{self.name}, {self.state} (zone {self.zone})"

    def last_frost_on(self, year: int) -> date:
        m, d = map(int, self.last_frost.split("-"))
        return date(year, m, d)

    def first_frost_on(self, year: int) -> date:
        m, d = map(int, self.first_frost.split("-"))
        return date(year, m, d)


class PetToxic(BaseModel):
    cats: bool
    dogs: bool


class Plant(BaseModel):
    id: str
    name: str
    category: Literal["vegetable", "herb", "flower", "fruit", "cover_crop"]
    edible: bool
    season: Literal["warm", "cool", "fall_planted", "perennial", "indoor"]
    zone_min: int
    zone_max: int
    sun: list[Literal["full", "part", "shade"]]
    difficulty: Literal["beginner", "intermediate", "experienced"]
    planting_method: Literal["transplant", "direct_sow"]
    indoor_start_weeks_before_last_frost: int | None
    spring_plant_offset_days: int | None
    fall_plant_days_before_first_frost: int | None
    frost_tender: bool
    days_to_maturity: int
    harvest_window_days: int
    spacing_in: float
    per_sqft: float
    container_ok: bool
    min_container_gal: int | None
    indoor_ok: bool
    sprawling: bool
    tall: bool
    needs_trellis: bool
    goals: list[str]
    companions: list[str]
    pet_toxic: PetToxic
    pet_note: str
    tip: str
    sources: list[str]
    plants_per_person: float | None = None     # fresh eating, one adult, one season
    yield_lb_per_plant: float | None = None
    retail_price_per_lb: float | None = None
    yield_source: str = ""


@lru_cache(maxsize=1)
def locations() -> dict[str, Location]:
    raw = json.loads((config.DATA_DIR / "locations.json").read_text(encoding="utf-8"))
    return {loc["id"]: Location(**loc) for loc in raw}


@lru_cache(maxsize=1)
def plants() -> dict[str, Plant]:
    raw = json.loads((config.DATA_DIR / "plants.json").read_text(encoding="utf-8"))
    return {p["id"]: Plant(**p) for p in raw}


@lru_cache(maxsize=1)
def builds() -> dict:
    return json.loads((config.DATA_DIR / "builds.json").read_text(encoding="utf-8"))


def location_for_zip(zip_code: str) -> Location | None:
    """Map a 5-digit ZIP to the nearest listed location by 3-digit prefix.
    The ZIP itself is never stored or logged."""
    z = (zip_code or "").strip()
    if len(z) != 5 or not z.isdigit():
        return None
    prefix = z[:3]
    for loc in locations().values():
        if prefix in loc.zip_prefixes:
            return loc
    return None
