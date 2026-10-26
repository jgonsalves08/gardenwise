"""Wires the agents together.

Two stages so the user can change their mind for free:
  1. recommend()  — the LLM step(s): picks plants for this gardener.       (costs tokens)
  2. assemble()   — pure code: calendar, layout, builds, costs, warnings.  (free, instant)
The UI calls recommend() once, then re-runs assemble() whenever the user ticks or
unticks a recommended plant or an add-on build.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import config, llm
from .safety import clean_model_text
from .agents.build import advise_builds, compute_build, default_builds, eligible_builds, get_build
from .agents.calendar import prep_tasks, schedule_plant
from .agents.selector import select_plants
from .costs import plant_cost_lines
from .data import Location, Plant, locations, plants
from .schemas import (Allocation, BuildPlan, Constraints, MaterialLine, PlantPick,
                      PlantSchedule, Task)
from .school import harvest_in_school, summer_care_tasks
from .space import allocate, capacity, coverage, layout_grid
from .verifier import Report, repair, verify


@dataclass
class Recommendation:
    run_id: str
    constraints: Constraints
    picks: list[PlantPick]
    alternates: list[PlantPick]
    summary: str
    report: Report | None = None
    build_recs: list[tuple[str, str]] = field(default_factory=list)   # (build_id, reason)


@dataclass
class Plan:
    rec: Recommendation
    location: Location
    chosen_ids: list[str]
    plants: list[Plant]
    allocations: list[Allocation]
    schedules: list[PlantSchedule]
    builds: list[BuildPlan]           # included in the shopping list
    addons: list[BuildPlan]           # optional builds the user can tick to include
    plant_costs: list[MaterialLine]
    tasks: list[Task]
    grid: list[list[str | None]]
    free_space: int
    warnings: list[str] = field(default_factory=list)
    budget_notes: list[str] = field(default_factory=list)
    coverage: list[tuple[str, int, int]] = field(default_factory=list)   # (plant, planned, needed)

    def expected_harvest(self) -> tuple[float, float]:
        """(pounds, grocery value in $) from typical yields — rough, for motivation and impact."""
        lb = val = 0.0
        for a in self.allocations:
            p = next(x for x in self.plants if x.id == a.plant_id)
            if p.yield_lb_per_plant and a.count:
                lb += a.count * p.yield_lb_per_plant
                val += a.count * p.yield_lb_per_plant * (p.retail_price_per_lb or 0)
        return round(lb, 1), round(val, 2)

    @property
    def constraints(self) -> Constraints:
        return self.rec.constraints

    @property
    def build_total(self) -> float:
        return round(sum(b.total_usd for b in self.builds), 2)

    @property
    def plant_total(self) -> float:
        return round(sum(m.subtotal for m in self.plant_costs), 2)

    def shopping_lines(self) -> list[tuple[str, MaterialLine]]:
        return ([("plants", m) for m in self.plant_costs]
                + [(b.build_id, m) for b in self.builds for m in b.materials])

    @property
    def total(self) -> float:
        return round(self.build_total + self.plant_total, 2)


def safety_warnings(c: Constraints, chosen: list[Plant]) -> list[str]:
    warnings = []
    if any(p.edible for p in chosen) and c.space_type in ("in_ground", "raised_bed"):
        warnings.append(
            "🧪 **Test your soil for lead before growing food.** Many US yards (older painted "
            "houses, city lots, roadsides) have elevated lead. Your state extension lab tests soil for "
            "about $15–$30. Raised beds filled with bagged soil, over cardboard, are the safest option."
        )
    from .agents.site_scout import HAZARD_TEXT
    warnings += [HAZARD_TEXT[h] for h in c.site_hazards if h in HAZARD_TEXT]
    pets = [name for name, has in (("cats", c.has_cats), ("dogs", c.has_dogs)) if has]
    for p in chosen:
        hits = [pet for pet in pets if getattr(p.pet_toxic, pet)]
        if hits:
            warnings.append(f"🐾 **{p.name} is toxic to {' and '.join(hits)}.** {p.pet_note} "
                            "Fence it off or grow it out of reach.")
    return warnings


def recommend(c: Constraints, budget: llm.Budget) -> Recommendation:
    """Selector → Verifier (one retry with feedback, then repair) → Build advisor."""
    run_id = uuid.uuid4().hex[:8]
    loc = locations()[c.location_id]
    if not loc.supported:   # enforced here too, not just by the disabled button
        raise ValueError(f"Planning isn't available yet for {loc.name}, {loc.state}: {loc.support_reason}")
    db = plants()

    selection, cands = select_plants(c, loc, budget, run_id=run_id)
    cand_ids = {p.id for p in cands}
    report = verify(selection.picks, c, loc, cand_ids)
    if not report.ok and config.MAX_VERIFIER_RETRIES > 0:
        selection, _ = select_plants(c, loc, budget, run_id=run_id, feedback=report.feedback())
        report = verify(selection.picks, c, loc, cand_ids)
        report.attempts = 2
    picks = selection.picks
    if not report.ok:
        kept = repair(picks, report)
        if kept:
            report.repaired = True
            picks = kept

    picks = [pk.model_copy(update={"reason": clean_model_text(pk.reason, 200),
                                   "lesson": clean_model_text(pk.lesson, 200) if c.audience == "school" else ""})
             for pk in picks]
    seen = {pk.plant_id for pk in picks}
    alternates = []
    for pk in selection.alternates:
        if pk.plant_id in seen or pk.plant_id not in cand_ids:
            continue  # alternates must also be valid candidates; no retry needed
        seen.add(pk.plant_id)
        alternates.append(pk.model_copy(update={
            "reason": clean_model_text(pk.reason, 200),
            "lesson": clean_model_text(pk.lesson, 200) if c.audience == "school" else ""}))

    rec = Recommendation(run_id=run_id, constraints=c, picks=picks, alternates=alternates,
                         summary=clean_model_text(selection.summary, 400), report=report)

    # Build advisor sees code-computed prices for the optional builds.
    base = assemble(rec, [pk.plant_id for pk in picks], [])
    remaining = None if c.budget_max is None else c.budget_max - base.total
    try:
        rec.build_recs = advise_builds(c, base.plants, base.addons, remaining, budget, run_id=run_id)
    except llm.LLMError:
        rec.build_recs = []  # add-ons are optional; the plan still works without advice
    return rec


SHAREABLE_BUILDS = {"compost_bin", "rain_barrel"}   # one per place is enough


def assemble(rec: Recommendation, chosen_ids: list[str], addon_ids: list[str] | None = None,
             owned: set[str] | None = None) -> Plan:
    """Everything after plant selection. Pure code, so it's free to re-run on every click."""
    c = rec.constraints
    loc = locations()[c.location_id]
    db = plants()
    chosen = [db[i] for i in chosen_ids if i in db]

    allocs = allocate(chosen, c)
    schedules = [schedule_plant(p, loc, c.start_date, c.skill_level) for p in chosen]
    plant_costs = plant_cost_lines(chosen, allocs, schedules)

    # Builds: the base build for the space is required; a trellis is recommended if a
    # chosen plant climbs; other eligible builds are optional add-ons.
    base_ids = default_builds(c, chosen)
    required = [b for b in base_ids if b != "trellis"]
    optional_rec = [b for b in base_ids if b == "trellis"]
    built = [compute_build(b, c, allocs, db) for b in required]
    budget_notes: list[str] = []

    plant_total = sum(m.subtotal for m in plant_costs)
    spent = sum(b.total_usd for b in built) + plant_total
    for bid in optional_rec:
        bp = compute_build(bid, c, allocs, db)
        if c.budget_max is not None and spent + bp.total_usd > c.budget_max:
            budget_notes.append(f"Skipped the {bp.name.lower()} (${bp.total_usd:,.0f}) to stay in budget. "
                                "Bamboo stakes and twine (about $10) work for a first season.")
        else:
            built.append(bp)
            spent += bp.total_usd

    addon_ids = addon_ids or []
    owned = (owned or set()) & SHAREABLE_BUILDS
    included = {b.build_id for b in built}
    addons = []
    for b in eligible_builds(c):
        if b["id"] in included or b["id"] in ("raised_bed", "container_setup"):
            continue
        if b["id"] in owned:
            where = f" at {c.place}" if c.place else ""
            budget_notes.append(f"♻️ You already have a {b['name'].lower()} in another garden{where}, "
                                "so it isn't suggested or counted again.")
            continue
        bp = compute_build(b["id"], c, allocs, db)
        if b["id"] in addon_ids:
            built.append(bp)
            spent += bp.total_usd
        else:
            addons.append(bp)

    if c.budget_max is not None:
        if spent > c.budget_max:
            over = spent - c.budget_max
            tips = ["choose a smaller space size", "untick a plant or two",
                    "use free fill (leaves, logs) under the soil"]
            if c.space_type == "raised_bed":
                tips.insert(0, "grow in containers this year and build beds next year")
            if c.space_type == "raised_bed" and c.area_sqft > 16:
                small = c.model_copy(update={"width_ft": 4, "length_ft": 4})
                tips.insert(0, f"start with one 4 × 4 ft bed (about "
                               f"${compute_build('raised_bed', small, allocs, db).total_usd:,.0f})")
            budget_notes.append(f"About ${over:,.0f} over your ${c.budget_max:,} maximum. To cut cost: "
                                + "; ".join(tips) + ".")
        elif spent < c.budget_min:
            budget_notes.append(f"You're ${c.budget_min - spent:,.0f} under your minimum. "
                                "The add-ons below can make the garden easier or extend the season.")
        else:
            budget_notes.append(f"✅ Fits your ${c.budget_min:,}–${c.budget_max:,} budget.")

    first_build_weeks = [(b.name, get_build(b.build_id)["build_weeks_before_planting"]) for b in built]
    has_ground_edibles = any(p.edible for p in chosen) and c.space_type in ("in_ground", "raised_bed")
    tasks = prep_tasks(schedules, c.start_date, has_ground_edibles, first_build_weeks)
    for s in schedules:
        tasks.extend(s.tasks)
    tasks.extend(summer_care_tasks(schedules, c))
    tasks.sort(key=lambda t: t.when)

    from .goals import unmet_goal_warnings
    warnings = unmet_goal_warnings(c, loc) + safety_warnings(c, chosen)
    if c.plot_history:
        from .rotation import FAMILY_LABEL, conflicts, tips
        warnings = tips(c.plot_history, c.start_date.year, c.space_type) + warnings
        for pid, f, y in conflicts([p.id for p in chosen], c.plot_history, c.start_date.year):
            warnings.append(f"🔁 **{db[pid].name}** is in the {FAMILY_LABEL[f]}, which grew in this plot in {y}. "
                            "Plant it in a different spot this year if you can, or refresh the soil.")
    if c.audience == "school" and not c.summer_care:
        summer = [p.name for p, s in zip(chosen, schedules) if not harvest_in_school(s, c)]
        if summer:
            warnings.append(f"🏫 **{', '.join(summer)} will be ready mostly over summer break.** "
                            "Line up summer care (families, staff, a summer program) or untick them.")

    used = sum(a.containers if a.containers else a.squares for a in allocs)
    return Plan(
        rec=rec, location=loc, chosen_ids=[p.id for p in chosen], plants=chosen,
        allocations=allocs, schedules=schedules, builds=built, addons=addons,
        plant_costs=plant_costs, tasks=tasks, grid=layout_grid(allocs, db, c),
        free_space=max(0, capacity(c) - used),
        warnings=warnings, budget_notes=budget_notes, coverage=coverage(allocs, db, c),
    )


# ---------- saving / loading (used by the optional accounts feature) ----------
def rec_to_json(rec: Recommendation) -> dict:
    r = rec.report
    return {
        "run_id": rec.run_id,
        "constraints": rec.constraints.model_dump(mode="json"),
        "picks": [p.model_dump() for p in rec.picks],
        "alternates": [p.model_dump() for p in rec.alternates],
        "summary": rec.summary,
        "build_recs": [list(x) for x in rec.build_recs],
        "report": None if r is None else {
            "checks": [c.__dict__ for c in r.checks], "attempts": r.attempts, "repaired": r.repaired},
    }


def rec_from_json(d: dict) -> Recommendation:
    from .verifier import Check

    rep = None
    if d.get("report"):
        rep = Report(checks=[Check(**c) for c in d["report"]["checks"]],
                     attempts=d["report"]["attempts"], repaired=d["report"]["repaired"])
    return Recommendation(
        run_id=d["run_id"], constraints=Constraints.model_validate(d["constraints"]),
        picks=[PlantPick(**p) for p in d["picks"]],
        alternates=[PlantPick(**p) for p in d.get("alternates", [])],
        summary=d["summary"], report=rep,
        build_recs=[tuple(x) for x in d.get("build_recs", [])],
    )


def task_key(t: Task) -> str:
    """Stable id for a checklist item (dates are deterministic, but keys don't depend on them)."""
    return f"task|{t.kind}|{t.plant_id or ''}|{t.title}"


def shop_key(group: str, item: str) -> str:
    """group is "plants" or a build id: the same item (e.g. zip ties) can appear in two builds."""
    return f"shop|{group}|{item}"
