"""Verifier (CODE, no LLM): checks the Selector's picks before the user sees them.

Every pick must exist in the plant database, fit the zone / sun / skill / space, get a valid
schedule from the frost data (dates in order, after the start date, tender crops harvested
before the first frost), and the set must cover the goals and fit in the space.
Pet toxicity and lead-in-soil are not failures: they become visible warnings.

The pipeline gives the Selector ONE retry with this report as feedback, then repairs
(drops failing picks) instead of looping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .agents.calendar import schedule_plant
from .data import Location, Plant, plants
from .schemas import GOAL_LABELS, SKILL_RANK, Constraints, PlantPick
from .school import harvest_in_school
from .space import capacity, min_footprint, suits_space


@dataclass
class Check:
    name: str
    status: Literal["pass", "fail", "warn"]
    detail: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    bad_ids: set[str] = field(default_factory=set)
    attempts: int = 1
    repaired: bool = False

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def feedback(self) -> str:
        return "\n".join(f"- {c.name}: {c.detail}" for c in self.checks if c.status == "fail")

    def add(self, name: str, ok: bool, detail_fail: str, detail_pass: str = "",
            bad: str | None = None, warn: bool = False) -> None:
        if ok:
            self.checks.append(Check(name, "pass", detail_pass))
        else:
            self.checks.append(Check(name, "warn" if warn else "fail", detail_fail))
            if bad and not warn:
                self.bad_ids.add(bad)


def verify(picks: list[PlantPick], c: Constraints, loc: Location,
           candidate_ids: set[str]) -> Report:
    db = plants()
    r = Report()
    ids = [p.plant_id for p in picks]

    r.add("No duplicate plants", len(ids) == len(set(ids)), "The same plant was picked twice.",
          f"{len(ids)} distinct plants")

    valid: list[Plant] = []
    for pid in ids:
        if pid not in db:
            r.add(f"{pid}: in database", False, f"'{pid}' is not in plants.json.", bad=pid)
            continue
        p = db[pid]
        n = p.name
        r.add(f"{n}: allowed candidate", pid in candidate_ids,
              f"{n} was not in the candidate list for this gardener.", "in candidate list", bad=pid)
        r.add(f"{n}: zone", p.zone_min <= loc.zone_num <= p.zone_max,
              f"{n} grows in zones {p.zone_min}–{p.zone_max}, not {loc.zone}.",
              f"zones {p.zone_min}–{p.zone_max} include {loc.zone}", bad=pid)
        r.add(f"{n}: sun", c.sun == "unknown" or c.sun in p.sun,
              f"{n} needs {'/'.join(p.sun)} sun; the spot is {c.sun}.",
              f"tolerates {'/'.join(p.sun)}", bad=pid)
        r.add(f"{n}: skill level", SKILL_RANK[p.difficulty] <= SKILL_RANK[c.skill_level],
              f"{n} is {p.difficulty}; the gardener is {c.skill_level}.", p.difficulty, bad=pid)
        r.add(f"{n}: suits the space", suits_space(p, c),
              f"{n} doesn't suit a {c.space_type.replace('_', ' ')} garden.", "fits space type", bad=pid)
        r.add(f"{n}: not on avoid list", pid not in c.avoid_plants,
              f"The gardener asked to avoid {n}.", bad=pid)
        try:
            s = schedule_plant(p, loc, c.start_date, c.skill_level)
            dates_ok = (s.plant_out >= c.start_date and s.harvest_start > s.plant_out
                        and s.harvest_end >= s.harvest_start
                        and all(t.when >= c.start_date for t in s.tasks))
            frost_ok = (not p.frost_tender
                        or s.harvest_start <= loc.first_frost_on(s.harvest_start.year))
            r.add(f"{n}: dates valid", dates_ok and frost_ok,
                  f"{n} has an invalid schedule (dates out of order or harvest after frost).",
                  f"plant {s.plant_out:%b %d %Y} → harvest {s.harvest_start:%b %d}", bad=pid)
            if c.audience == "school" and c.school_start and not c.summer_care:
                r.add(f"{n}: harvest during school year", harvest_in_school(s, c),
                      f"{n} is harvested {s.harvest_start:%b %d}–{s.harvest_end:%b %d}, during summer "
                      "break, and nobody is there over the summer. Pick a crop harvested while school is in session.",
                      "students will be there to pick it", bad=pid)
        except ValueError:
            r.add(f"{n}: dates valid", False, f"No valid planting window for {n} here.", bad=pid)
        if pid not in r.bad_ids:
            valid.append(p)

    # Goal coverage: only demand a goal if some candidate can serve it.
    cand_goals = {g for cid in candidate_ids if cid in db for g in db[cid].goals}
    for g in c.goals:
        if g not in cand_goals:
            r.add(f"Goal: {GOAL_LABELS[g]}", False,
                  "No plant fits this goal under these conditions.", warn=True)
            continue
        served = [p.name for p in valid if g in p.goals]
        r.add(f"Goal: {GOAL_LABELS[g]}", bool(served),
              f"No pick serves the goal '{g}'. Add a candidate tagged {g}.",
              ", ".join(served))

    for want in c.want_plants:
        if want in candidate_ids:
            r.add(f"Requested: {db[want].name}", want in ids,
                  f"The gardener asked for {db[want].name} (a valid candidate) but it was not picked.")

    need, cap = min_footprint(valid, c), capacity(c)
    unit = "pots" if c.space_type in ("containers", "windowsill") else "sq ft"
    r.add("Fits the space", need <= cap,
          f"The picks need at least {need} {unit} but only {cap} {unit} are available. Pick fewer or smaller plants.",
          f"needs {need} of {cap} {unit}")

    if c.plot_history:
        from .rotation import FAMILY_LABEL, conflicts
        rot = conflicts([p.id for p in valid], c.plot_history, c.start_date.year)
        r.add("Crop rotation", not rot,
              "Repeats a family grown here recently: "
              + "; ".join(f"{db[pid].name} ({FAMILY_LABEL[f]}, {y})" for pid, f, y in rot)
              + ". Fine in fresh soil or containers; otherwise consider a different spot.",
              "no plant family repeated too soon", warn=True)
    pets = [k for k, has in (("cats", c.has_cats), ("dogs", c.has_dogs)) if has]
    toxic = [p.name for p in valid if any(getattr(p.pet_toxic, k) for k in pets)]
    r.add("Pet safety", not toxic, f"Toxic to your pets: {', '.join(toxic)} — warning shown.",
          "no pet-toxic picks" if pets else "no pets", warn=True)
    edible_ground = any(p.edible for p in valid) and c.space_type in ("in_ground", "raised_bed")
    r.add("Lead-in-soil warning", not edible_ground,
          "Edibles in ground soil — lead-test warning shown.", "not needed", warn=True)
    return r


def repair(picks: list[PlantPick], report: Report) -> list[PlantPick]:
    """After the single retry: drop failing picks rather than calling the model again."""
    return [p for p in picks if p.plant_id not in report.bad_ids]
