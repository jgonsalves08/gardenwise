"""Calendar agent (CODE, no LLM): sow / transplant / harvest dates from frost data.

For each plant we look for the first planting window on or after the gardener's
start date, trying this year's spring and fall windows, then next year's, and so on.
A warm-season crop is only valid if it can reach harvest before the first fall frost.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..data import Location, Plant, plants as plant_db
from ..schemas import PlantSchedule, SkillLevel, Task

PLANTING_SLACK_DAYS = 14   # how late you can still plant after the ideal date
FALL_SLACK_DAYS = 7
LATE_FALL_SLACK_DAYS = 21   # garlic / cover crops can go in until the ground freezes


def _season_name(d: date) -> str:
    if d.month in (3, 4, 5):
        return "Spring"
    if d.month in (6, 7, 8):
        return "Summer"
    if d.month in (9, 10, 11):
        return "Fall"
    return "Winter"


def _candidate_windows(plant: Plant, loc: Location, year: int) -> list[tuple[date, str]]:
    """Ideal outdoor planting dates for a given year: (date, 'spring'|'fall')."""
    out: list[tuple[date, str]] = []
    if plant.spring_plant_offset_days is not None:
        out.append((loc.last_frost_on(year) + timedelta(days=plant.spring_plant_offset_days), "spring"))
    if plant.fall_plant_days_before_first_frost is not None:
        out.append((loc.first_frost_on(year) - timedelta(days=plant.fall_plant_days_before_first_frost), "fall"))
    return sorted(out)


def _fits_before_frost(plant: Plant, loc: Location, plant_out: date) -> bool:
    if not plant.frost_tender:
        return True
    return plant_out + timedelta(days=plant.days_to_maturity) <= loc.first_frost_on(plant_out.year)


def schedule_plant(plant: Plant, loc: Location, start: date, skill: SkillLevel) -> PlantSchedule:
    tasks: list[Task] = []

    if plant.season == "indoor":
        plant_out = start
        harvest_start = plant_out + timedelta(days=plant.days_to_maturity)
        harvest_end = harvest_start + timedelta(days=plant.harvest_window_days)
        tasks = [
            Task(when=plant_out, kind="plant", title=f"Sow {plant.name} indoors", plant_id=plant.id,
                 detail="Sunny windowsill or under a shop light; can repeat every 2 weeks year-round."),
            Task(when=harvest_start, kind="harvest", title=f"Harvest {plant.name}", plant_id=plant.id),
        ]
        return PlantSchedule(plant_id=plant.id, season_label=f"{_season_name(start)} {start.year} (indoors)",
                             method="indoor", plant_out=plant_out, harvest_start=harvest_start,
                             harvest_end=harvest_end, tasks=tasks)

    chosen: tuple[date, str] | None = None
    for year in (start.year, start.year + 1, start.year + 2):
        for ideal, kind in _candidate_windows(plant, loc, year):
            if kind == "spring":
                slack = PLANTING_SLACK_DAYS
            elif plant.season == "fall_planted" or plant.category == "cover_crop":
                slack = LATE_FALL_SLACK_DAYS
            else:
                slack = FALL_SLACK_DAYS
            if ideal + timedelta(days=slack) < start:
                continue  # window already closed
            plant_out = max(ideal, start)
            if not _fits_before_frost(plant, loc, plant_out):
                continue
            chosen = (plant_out, kind)
            break
        if chosen:
            break
    if chosen is None:  # data problem; the verifier will flag this plant
        raise ValueError(f"No valid planting window for {plant.id} at {loc.id}")

    plant_out, kind = chosen
    rolled = plant_out.year > start.year or (plant_out - start).days > 120

    # How the plant gets started.
    indoor_weeks = plant.indoor_start_weeks_before_last_frost
    method = "direct_sow"
    if plant.planting_method == "transplant":
        indoor_date = plant_out - timedelta(weeks=indoor_weeks or 6)
        if skill != "beginner" and indoor_weeks and kind == "spring" and indoor_date >= start:
            method = "start_indoors"
            tasks.append(Task(when=indoor_date, kind="start_indoors", plant_id=plant.id,
                              title=f"Start {plant.name} seeds indoors",
                              detail=f"{indoor_weeks} weeks before transplanting; use a sunny window or grow light."))
        else:
            method = "buy_transplants"
            tasks.append(Task(when=max(start, plant_out - timedelta(days=7)), kind="buy", plant_id=plant.id,
                              title=f"Buy {plant.name} transplants",
                              detail="Pick stocky, dark-green plants without flowers or yellow leaves."))

    verb = {"direct_sow": "Sow", "start_indoors": "Transplant", "buy_transplants": "Transplant"}[method]
    if plant.season == "fall_planted":
        verb = "Plant"
    tasks.append(Task(when=plant_out, kind="plant", plant_id=plant.id,
                      title=f"{verb} {plant.name} outdoors", detail=plant.tip))

    harvest_start = plant_out + timedelta(days=plant.days_to_maturity)
    harvest_end = harvest_start + timedelta(days=plant.harvest_window_days)
    if plant.frost_tender:
        harvest_end = min(harvest_end, loc.first_frost_on(harvest_start.year))
    harvest_end = max(harvest_end, harvest_start)
    tasks.append(Task(when=harvest_start, kind="harvest", plant_id=plant.id,
                      title=f"Start harvesting {plant.name}",
                      detail=f"Harvest through about {harvest_end:%b %d}."))

    label = f"{_season_name(plant_out)} {plant_out.year}"
    return PlantSchedule(plant_id=plant.id, season_label=label, method=method, plant_out=plant_out,
                         harvest_start=harvest_start, harvest_end=harvest_end,
                         rolled_forward=rolled, tasks=tasks)


def plantable_within(plant: Plant, loc: Location, start: date, weeks: int) -> bool:
    """True if this plant's next outdoor (or indoor) planting falls within `weeks` of start."""
    try:
        s = schedule_plant(plant, loc, start, "experienced")
    except ValueError:
        return False
    return (s.plant_out - start).days <= weeks * 7


def prep_tasks(schedules: list[PlantSchedule], start: date, has_edibles: bool,
               builds: list[tuple[str, int]]) -> list[Task]:
    """Prep work scheduled backwards from planting dates (never before the start date).

    Plants that go in soon (within 6 weeks of start) and plants that wait for a later
    window (e.g. next spring) get separate "order seeds" reminders, so a fall start
    doesn't tell you to buy tomato transplants in October.
    builds: (name, weeks before first planting to build it).
    """
    tasks: list[Task] = []
    if not schedules:
        return tasks
    first_out = min(s.plant_out for s in schedules)
    if has_edibles:
        tasks.append(Task(when=max(start, first_out - timedelta(weeks=6)), kind="prep",
                          title="Test soil for lead (and pH)",
                          detail="Send a sample to your state's extension soil lab (about $15–$30). "
                                 "Older homes, city lots and busy roadsides often have lead in the soil; "
                                 "use raised beds or containers with bagged soil if the level is elevated."))
    for name, weeks in builds:
        tasks.append(Task(when=max(start, first_out - timedelta(weeks=weeks or 0)),
                          kind="build", title=f"Build: {name}",
                          detail="See the shopping list for materials and costs."))

    soon = [s for s in schedules if (s.plant_out - start).days <= 42]
    later = [s for s in schedules if (s.plant_out - start).days > 42]
    if soon:
        tasks.append(Task(when=max(start, min(s.plant_out for s in soon) - timedelta(weeks=2)),
                          kind="buy", title="Get seeds and plants for what goes in now",
                          detail=", ".join(plant_db()[s.plant_id].name for s in soon)))
    if later:
        when = max(start, min(s.plant_out for s in later) - timedelta(weeks=6))
        tasks.append(Task(when=when, kind="buy", title="Order seeds for the next planting season",
                          detail="Popular varieties sell out by early spring: "
                                 + ", ".join(plant_db()[s.plant_id].name for s in later)))
    return tasks
