"""Pydantic models shared by the agents, the calendar and the UI."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

SkillLevel = Literal["beginner", "intermediate", "experienced"]
Goal = Literal[
    "salsa",
    "pesto_herbs",
    "salad",
    "pickling",
    "pollinator",
    "cut_flowers",
    "herbal_tea",
    "three_sisters",
    "kids",
]
StartMode = Literal["now", "month", "best_time", "next_season"]
SpaceType = Literal["containers", "raised_bed", "in_ground", "windowsill"]
Sun = Literal["full", "part", "shade", "unknown"]
Audience = Literal["me", "household", "school", "community"]
GradeBand = Literal["K-2", "3-5", "6-8", "9-12"]

GOAL_LABELS: dict[str, str] = {
    "salsa": "Salsa garden",
    "pesto_herbs": "Pesto & cooking herbs",
    "salad": "Salad greens",
    "pickling": "Pickling",
    "pollinator": "Pollinators & butterflies",
    "cut_flowers": "Cut flowers",
    "herbal_tea": "Herbal tea",
    "three_sisters": "Three Sisters (corn, beans, squash)",
    "kids": "Kids' garden",
}
SKILL_RANK = {"beginner": 1, "intermediate": 2, "experienced": 3}


class Constraints(BaseModel):
    """Everything the planner needs to know about the gardener. Built from the form,
    optionally refined by the Intake agent's reading of the chat."""

    location_id: str
    skill_level: SkillLevel
    goals: list[Goal] = Field(min_length=1, max_length=4)
    start_mode: StartMode = "now"
    start_date: date
    space_type: SpaceType
    width_ft: float = Field(default=4, ge=0, le=100)
    length_ft: float = Field(default=4, ge=0, le=100)
    num_containers: int = Field(default=4, ge=0, le=40)
    sun: Sun = "unknown"
    sun_basis: str = "not given"
    budget_min: int = Field(default=0, ge=0, le=10_000)
    budget_max: int | None = Field(default=None, ge=0, le=10_000)
    has_cats: bool = False
    has_dogs: bool = False
    want_plants: list[str] = Field(default_factory=list, max_length=6)
    avoid_plants: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=300)
    place: str = Field(default="", max_length=40)   # nickname like "Home" or "School", never an address
    # Who the garden is for
    audience: Audience = "me"
    adults: int = Field(default=1, ge=0, le=20)          # household mode
    kids: int = Field(default=0, ge=0, le=20)
    grade_band: GradeBand | None = None                  # school mode
    school_start: date | None = None                     # first day of the school year
    school_end: date | None = None                       # last day before summer break
    summer_care: bool = False                            # someone tends the garden over summer
    beds_ready: bool = False                             # beds/soil already exist (e.g. community plots)
    site_hazards: list[str] = Field(default_factory=list, max_length=6)  # confirmed from photos
    site_summary: str = Field(default="", max_length=250)               # Site Scout summary (confirmed)

    @property
    def people(self) -> float:
        """Eaters for sizing: kids count as half."""
        return max(1.0, self.adults + 0.5 * self.kids) if self.audience == "household" else 1.0

    @property
    def area_sqft(self) -> float:
        if self.space_type in ("containers", "windowsill"):
            return 0.0
        return round(self.width_ft * self.length_ft, 1)


class PlantPick(BaseModel):
    plant_id: str
    reason: str = Field(max_length=200)
    lesson: str = Field(default="", max_length=200)   # school mode: one classroom tie-in


class Selection(BaseModel):
    """Selector output. plant_id values are restricted to the candidate list at call time."""

    picks: list[PlantPick] = Field(min_length=1, max_length=6)   # LLM schema still asks for 3+
    alternates: list[PlantPick] = Field(default_factory=list, max_length=3)
    summary: str = Field(max_length=400)


class Task(BaseModel):
    when: date
    kind: Literal["prep", "start_indoors", "buy", "plant", "harvest", "build", "now", "care"]
    title: str
    detail: str = ""
    plant_id: str | None = None


class PlantSchedule(BaseModel):
    plant_id: str
    season_label: str
    method: Literal["start_indoors", "buy_transplants", "direct_sow", "indoor"]
    plant_out: date
    harvest_start: date
    harvest_end: date
    rolled_forward: bool = False
    tasks: list[Task]


class Allocation(BaseModel):
    plant_id: str
    count: int
    squares: int = 0       # 1-ft squares used (beds / in-ground)
    containers: int = 0    # pots used (containers / windowsill)


class MaterialLine(BaseModel):
    item: str
    qty: int
    unit_price: float
    subtotal: float
    store_links: dict[str, str]


class BuildPlan(BaseModel):
    build_id: str
    name: str
    why: str
    when: date | None = None
    materials: list[MaterialLine]
    total_usd: float
    notes: list[str] = Field(default_factory=list)
