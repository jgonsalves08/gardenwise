"""Why a plant (or a whole goal) can't be in a plan, in plain words.

The Selector's candidate filter uses why_not(), so the explanation shown to the gardener always
matches the rule that actually removed the plant.
"""

from __future__ import annotations

from .agents.calendar import schedule_plant
from .data import Location, Plant, plants
from .schemas import GOAL_LABELS, SKILL_RANK, Constraints
from .space import suits_space

SUN_WORDS = {"full": "full sun", "part": "some sun, some shade", "shade": "mostly shade"}
SPACE_WORDS = {"windowsill": "a windowsill", "containers": "containers", "raised_bed": "a raised bed",
               "in_ground": "an in-ground bed"}


def why_not(p: Plant, c: Constraints, loc: Location) -> list[str]:
    """Every reason this plant can't be planned here: zone, skill, sun, space, avoid, timing."""
    out = []
    if not (p.zone_min <= loc.zone_num <= p.zone_max):
        out.append("zone")
    if SKILL_RANK[p.difficulty] > SKILL_RANK[c.skill_level]:
        out.append("skill")
    if c.sun != "unknown" and c.sun not in p.sun:
        out.append("sun")
    if not suits_space(p, c):
        out.append("space")
    if p.id in c.avoid_plants:
        out.append("avoid")
    if p.category == "cover_crop" and c.space_type not in ("in_ground", "raised_bed"):
        out.append("space")
    if not out:
        try:   # short mountain seasons: crops that can't ripen before frost at all
            schedule_plant(p, loc, c.start_date, c.skill_level)
        except ValueError:
            out.append("timing")
    return out


def _lower(name: str) -> str:
    return name if name.split()[0] in ("Swiss",) else name[0].lower() + name[1:]


def _names(ps: list[Plant], start: bool = True) -> str:
    """'Butternut squash, pumpkin and sweet corn' (capitalized only at the start of a sentence)."""
    n = [_lower(p.name) for p in ps]
    out = n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]
    return out[0].upper() + out[1:] if start else out


def _are(ps: list[Plant]) -> str:
    return "is" if len(ps) == 1 else "are"


def unmet_goal_reason(goal: str, c: Constraints, loc: Location) -> str:
    """Plain-English reason no plant can serve this goal here, plus what the gardener could change."""
    serving = [p for p in plants().values() if goal in p.goals]
    reasons = {p.id: why_not(p, c, loc) for p in serving}
    by = lambda r: [p for p in serving if r in reasons[p.id]]   # noqa: E731
    parts, fixes = [], []
    if sun := by("sun"):
        need = "full sun (6 or more hours of direct sun a day)" if all(p.sun == ["full"] for p in sun) \
            else "more sun (at least 3–6 hours of direct sun a day)"
        parts.append(f"{_names(sun)} need{'s' if len(sun) == 1 else ''} {need}, and you said your spot gets "
                     f"{SUN_WORDS.get(c.sun, c.sun)}.")
        fixes.append("if another part of your yard gets more sun, plan that spot as its own garden")
    if skill := by("skill"):
        level = "experienced" if {p.difficulty for p in skill} == {"experienced"} else "more experienced"
        them = "it" if len(skill) == 1 else "them"
        if sun and {p.id for p in skill} == {p.id for p in sun}:
            who = "It's also" if len(skill) == 1 else "They're also"
        else:
            who = f"{_names(skill)} {_are(skill)}" + (" also" if parts else "")
        parts.append(f"{who} tricky for a {c.skill_level} gardener (we rate {them} for {level} gardeners).")
        fixes.append("try them once you have a season behind you, or change your experience level "
                     "if you've grown them before")
    if space := by("space"):
        parts.append(f"{_names(space)} {_are(space)} too big to grow in {SPACE_WORDS[c.space_type]}.")
        fixes.append("plan a raised or in-ground bed for them")
    if zone := by("zone"):
        parts.append(f"{_names(zone)} {_are(zone)} not a good fit for {loc.name}'s winters and summers.")
    if timing := by("timing"):
        parts.append(f"Starting in {c.start_date:%B}, there isn't enough warm weather left for {_names(timing, start=False)} "
                     f"to ripen before the first frost (around {loc.first_frost_on(c.start_date.year):%b %d}).")
        fixes.append("choose “best time to plant” in the form")
    if avoid := by("avoid"):
        parts.append(f"You asked to leave out {_names(avoid, start=False)}.")
    if not parts:
        return "None of the plants for this goal fit this spot."
    msg = " ".join(parts)
    if fixes:
        msg += " To grow them: " + "; or ".join(fixes) + ". Then change the form and get a new plan."
    return msg


def unmet_goal_warnings(c: Constraints, loc: Location) -> list[str]:
    """One alert per goal that no plant can serve under these conditions."""
    db = plants()
    out = []
    for g in c.goals:
        if any(g in p.goals and not why_not(p, c, loc) for p in db.values()):
            continue
        out.append(f"🎯 **{GOAL_LABELS[g]} isn't in this plan.** {unmet_goal_reason(g, c, loc)}")
    return out
