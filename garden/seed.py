"""Demo account so graders and first-time visitors can see a garden mid-season.

These are TEST credentials for this local app only (also listed in the README).
The demo garden is built entirely in code — no AI call — so seeding is free.
"""

from __future__ import annotations

from datetime import date, timedelta


from . import store
from .agents.selector import candidates
from .data import locations
from .pipeline import Recommendation, assemble, rec_to_json, task_key
from .schemas import Constraints, PlantPick
from .verifier import verify

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "garden-demo-2026"
DEMO_MEMBER = "demo_member"          # a regular member of the demo community garden (same password)


def ensure_demo(today: date | None = None) -> None:
    today = today or date.today()
    try:
        user = store.create_user(DEMO_USERNAME, DEMO_PASSWORD)
    except store.AuthError:
        return  # already exists
    c = Constraints(
        location_id="new_haven_ct", skill_level="beginner", goals=["salad", "salsa"],
        start_mode="now", start_date=today - timedelta(days=21), space_type="raised_bed",
        width_ft=4, length_ft=8, sun="full", sun_basis="your estimate: “mostly sunny”",
        budget_min=100, budget_max=400, has_cats=True, place="Home",
    )
    picks = [
        PlantPick(plant_id="garlic", reason="Plant cloves this fall for a big summer harvest — almost no work."),
        PlantPick(plant_id="kale", reason="Tough, cold-hardy greens — one planting feeds salads from spring into fall."),
        PlantPick(plant_id="tomato_cherry", reason="The easiest tomato for next summer's salsa."),
        PlantPick(plant_id="lettuce", reason="Fast, forgiving salad greens for early spring."),
    ]
    alternates = [PlantPick(plant_id="radish", reason="Ready in about a month; fun first harvest.")]
    loc = locations()[c.location_id]
    report = verify(picks, c, loc, {p.id for p in candidates(c, loc)})
    rec = Recommendation(run_id="demo0001", constraints=c, picks=picks, alternates=alternates,
                         summary="A beginner raised bed: garlic now, then kale, lettuce and "
                                 "cherry tomatoes next spring.",
                         report=report,
                         build_recs=[("compost_bin", "Fall leaves make free compost for spring.")])
    chosen = [p.plant_id for p in picks]
    gid = store.save_garden(user["id"], "Backyard bed (demo)", rec_to_json(rec), chosen, ["compost_bin"])
    plan = assemble(rec, chosen, ["compost_bin"])
    for t in plan.tasks:  # tick off everything that was due before today
        if t.when < today:
            store.set_check(gid, user["id"], task_key(t), True)

    _seed_extra(user["id"], today)
    _seed_community(user["id"], today)


def _make(user_id: int, name: str, c: Constraints, picks: list[PlantPick], summary: str,
          addons: list[str], start: date, end: date | None, tick_before: date | None) -> None:
    loc = locations()[c.location_id]
    report = verify(picks, c, loc, {p.id for p in candidates(c, loc)})
    rec = Recommendation(run_id=f"demo{abs(hash(name)) % 10000:04d}", constraints=c, picks=picks,
                         alternates=[], summary=summary, report=report, build_recs=[])
    chosen = [p.plant_id for p in picks]
    gid = store.save_garden(user_id, name, rec_to_json(rec), chosen, addons)
    store.set_dates(gid, user_id, start, end)
    if tick_before:
        for t in assemble(rec, chosen, addons).tasks:
            if t.when < tick_before:
                store.set_check(gid, user_id, task_key(t), True)


def _seed_extra(user_id: int, today: date) -> None:
    # A finished garden from last season...
    past_start = date(today.year - 1, 4, 1)
    c = Constraints(location_id="new_haven_ct", skill_level="beginner", goals=["pesto_herbs"],
                    start_mode="month", start_date=past_start, space_type="containers",
                    num_containers=4, sun="full", sun_basis="your estimate: “mostly sunny”",
                    budget_min=0, budget_max=150, place="Home")
    _make(user_id, "Patio herbs (last year)", c,
          [PlantPick(plant_id="basil", reason="The heart of pesto, and it loves a hot patio."),
           PlantPick(plant_id="oregano", reason="Tough, drought-tolerant and great on pizza."),
           PlantPick(plant_id="chives", reason="Comes back every spring with almost no care.")],
          "A small container herb garden for pesto and cooking.", [],
          past_start, date(today.year - 1, 10, 15), tick_before=date(today.year - 1, 10, 15))
    _seed_harvests(user_id, "Patio herbs (last year)", today.year - 1)
    # ...and one planned for next spring.
    fut_start = date(today.year + 1, 3, 1)
    c = Constraints(location_id="new_haven_ct", skill_level="beginner", goals=["pollinator", "kids"],
                    start_mode="month", start_date=fut_start, space_type="in_ground",
                    width_ft=5, length_ft=10, sun="full", sun_basis="estimated from south-facing",
                    budget_min=50, budget_max=250, place="Lincoln School")
    _make(user_id, "Pollinator strip (next spring)", c,
          [PlantPick(plant_id="sunflower", reason="Giant, fast and fun for kids to measure."),
           PlantPick(plant_id="zinnia", reason="Butterflies love them, and they bloom until frost."),
           PlantPick(plant_id="nasturtium", reason="Edible flowers that grow almost anywhere.")],
          "A sunny strip of easy flowers for bees, butterflies and kids.", [],
          fut_start, None, tick_before=None)


DEMO_PLOTS = [
    ("1", "Maria", "beginner", ["salsa", "salad"], ["tomato_cherry", "scallion", "lettuce"]),
    ("2", "Dev", "intermediate", ["pickling"], ["cucumber_pickling", "dill", "beet"]),
    ("3", "Ana & kids", "beginner", ["kids", "pollinator"], ["radish", "nasturtium", "sunflower"]),
    ("4", "", "beginner", ["salad"], ["lettuce", "kale", "arugula"]),
]


def _seed_community(user_id: int, today: date) -> None:
    """A community garden the demo user organizes, mid- or post-season, with harvests logged,
    plus a second account (demo_member) that has joined and claimed plot 1."""
    start = date(today.year, 3, 1) if today.month >= 7 else date(today.year - 1, 3, 1)
    settings = {"location_id": "new_haven_ct", "place": "Elm St lot", "start_date": start.isoformat(),
                "space_type": "raised_bed", "plot_w": 4, "plot_l": 8, "plot_budget": 150,
                "shared_builds": ["compost_bin", "rain_barrel"], "beds_ready": True}
    grp = store.create_group(user_id, "Elm Street Community Garden (demo)", settings)
    plot_ids: dict[str, int] = {}
    loc = locations()["new_haven_ct"]
    for plot, who, skill, goals, ids in DEMO_PLOTS:
        c = Constraints(location_id="new_haven_ct", place="Elm St lot", start_date=start,
                        start_mode="month", space_type="raised_bed", width_ft=4, length_ft=8,
                        goals=goals, skill_level=skill, sun="full", sun_basis="from the sign-up sheet",
                        budget_max=150, audience="community", beds_ready=True)
        picks = [PlantPick(plant_id=i, reason="Picked for this plot's goals.") for i in ids]
        rec = Recommendation(run_id=f"plot{plot}", constraints=c, picks=picks, alternates=[],
                             summary="Demo community plot.",
                             report=verify(picks, c, loc, {p.id for p in candidates(c, loc)}))
        gid = store.save_garden(user_id, f"Plot {plot}" + (f" – {who}" if who else ""), rec_to_json(rec),
                                ids, [], group_id=grp["id"], plot_label=plot)
        plot_ids[plot] = gid
        for t in assemble(rec, ids, []).tasks:
            if t.when < today and plot != "4":   # plot 4 was neglected: nothing ticked or logged
                store.set_check(gid, user_id, task_key(t), True)
    _seed_community_harvests(user_id, plot_ids, start.year)
    from .community import work_days
    group = store.get_group(grp["id"], user_id)
    for d in work_days(group, today - timedelta(days=365), months=13):
        if d < today and d.month != 7:     # skipped the July work day (vacations)
            store.set_group_task(grp["id"], user_id, f"workday|{d.isoformat()}", claim=True, done=True)
    member = store.create_user(DEMO_MEMBER, DEMO_PASSWORD)
    store.join_group(member["id"], grp["join_code"])
    store.claim_plot(plot_ids["1"], grp["id"], member["id"], member["username"])


def _seed_harvests(user_id: int, garden_name: str, year: int) -> None:
    """A season of one-tap harvest logs on last year's herb garden, so the dashboard has data."""
    g = next(x for x in store.list_gardens(user_id) if x["name"] == garden_name)
    entries = [("basil", "bowl", 6, 20), ("basil", "handful", 7, 4), ("basil", "bowl", 7, 18),
               ("basil", "basket", 8, 10), ("basil", "bowl", 8, 28), ("basil", "bowl", 9, 12),
               ("oregano", "handful", 6, 28), ("oregano", "bowl", 7, 25), ("oregano", "handful", 9, 5),
               ("chives", "handful", 5, 20), ("chives", "handful", 6, 10), ("chives", "bowl", 7, 8)]
    for pid, size, m, d in entries:
        from .data import plants
        p = plants()[pid]
        store.log_harvest(g["id"], user_id, pid, size, store.size_to_lb(size, p.category, p.edible),
                          donated=(pid == "basil" and m == 8 and size == "basket"), picked_on=date(year, m, d))


def _seed_community_harvests(user_id: int, plot_ids: dict[str, int], year: int) -> None:
    from .data import plants
    entries = {
        "1": [("lettuce", "bowl", 5, 18), ("lettuce", "bowl", 6, 2), ("scallion", "handful", 6, 9),
              ("tomato_cherry", "bowl", 7, 20), ("tomato_cherry", "basket", 8, 9),
              ("tomato_cherry", "basket", 8, 23, True), ("tomato_cherry", "bowl", 9, 6)],
        "2": [("beet", "bowl", 7, 1), ("cucumber_pickling", "basket", 7, 22),
              ("cucumber_pickling", "basket", 8, 5, True), ("dill", "handful", 7, 8)],
        "3": [("radish", "bowl", 5, 12), ("nasturtium", "handful", 7, 15), ("sunflower", "bunch", 8, 20)],
    }
    for plot, rows in entries.items():
        for pid, size, m, d, *don in rows:
            p = plants()[pid]
            store.log_harvest(plot_ids[plot], user_id, pid, size, store.size_to_lb(size, p.category, p.edible),
                              donated=bool(don), picked_on=date(year, m, d))
