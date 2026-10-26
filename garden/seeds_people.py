"""Test personas for local testing: one account per kind of user, with gardens across the US.

TEST credentials for local copies only (listed in the README, never shown on the website).
Disable with GARDENWISE_TEST_ACCOUNTS=0 for any public deployment. Everything here is built
in code (no AI calls), so seeding is free and instant.

| username          | who                                   | where                         |
|-------------------|---------------------------------------|-------------------------------|
| test_individual   | first-time gardener, several gardens  | New Haven CT (+ Boise ID)     |
| test_household    | family of 4                           | Atlanta GA                    |
| test_school       | 3rd–5th grade teacher                 | Minneapolis MN                |
| test_organizer    | runs Elm Street Community Garden      | New Haven CT                  |
| test_admin        | admin at Elm Street; runs a garden    | New Haven CT + Seattle WA     |
| test_member       | member of both community gardens      | New Haven CT + Seattle WA     |
| demo              | showcase: a gardener with a bit of everything (several gardens, seasons,
|                   | harvests, and an admin's plot at Elm Street) for showing people the app    |
"""

from __future__ import annotations

from datetime import date, timedelta

from . import store
from .agents.selector import candidates
from .data import locations, plants
from .pipeline import Recommendation, assemble, rec_from_json, rec_to_json, task_key
from .rotation import history_from_seasons
from .schemas import Constraints, PlantPick
from .verifier import verify

TEST_PASSWORD = "gardenwise-test-2026"
USERS = ["test_individual", "test_household", "test_school", "test_organizer", "test_admin", "test_member"]
DEMO_USER = "demo"


def _rec(c: Constraints, picks: list[tuple[str, str] | tuple[str, str, str]], summary: str,
         build_recs=None) -> Recommendation:
    pp = [PlantPick(plant_id=p[0], reason=p[1], lesson=p[2] if len(p) > 2 else "") for p in picks]
    loc = locations()[c.location_id]
    return Recommendation(run_id=f"seed{abs(hash(summary)) % 100000:05d}", constraints=c, picks=pp,
                          alternates=[], summary=summary,
                          report=verify(pp, c, loc, {p.id for p in candidates(c, loc)}),
                          build_recs=build_recs or [])


def _save(uid: int, name: str, rec: Recommendation, addons: list[str], start: date, end: date | None,
          tick_before: date | None, plot_id: int | None = None, harvests=(), **kw) -> int:
    ids = [p.plant_id for p in rec.picks]
    gid = store.save_garden(uid, name, rec_to_json(rec), ids, addons, plot_id=plot_id, **kw)
    store.set_dates(gid, uid, start, end)
    if tick_before:
        keys = [task_key(t) for t in assemble(rec, ids, addons).tasks if t.when < tick_before]
        store.set_checks_bulk(gid, uid, keys)
    for pid, size, when, *don in harvests:
        p = plants()[pid]
        store.log_harvest(gid, uid, pid, size, store.size_to_lb(size, p.category, p.edible),
                          donated=bool(don), picked_on=when)
    return gid


def _c(**kw) -> Constraints:
    base = dict(start_mode="month", sun="full", sun_basis="your estimate: “mostly sunny”", budget_min=50,
                budget_max=400, skill_level="beginner")
    return Constraints(**(base | kw))


def ensure_people(today: date | None = None) -> None:
    today = today or date.today()
    try:
        ids = {u: store.create_user(u, TEST_PASSWORD)["id"] for u in USERS}
    except store.AuthError:
        return   # already seeded
    y = today.year
    _individual(ids["test_individual"], today, y)
    _household(ids["test_household"], today, y)
    _school(ids["test_school"], today, y)
    _communities(ids, today, y)


# ---------- test_individual: New Haven, several kinds of garden ----------
def _individual(uid: int, today: date, y: int) -> None:
    # Backyard bed: last year's season (tomatoes) + this season (rotation tip shows)
    c1 = _c(location_id="new_haven_ct", goals=["salsa", "pesto_herbs"], start_date=date(y - 1, 4, 1),
            space_type="raised_bed", width_ft=4, length_ft=8, has_cats=True, place="Home")
    r1 = _rec(c1, [("tomato_cherry", "A forgiving first tomato."), ("basil", "Pesto, and tomatoes' best friend."),
                   ("lettuce", "Quick spring greens.")], "First season: a salsa-and-pesto bed.")
    prev = _save(uid, "Backyard bed", r1, ["raised_bed"], date(y - 1, 4, 1), date(y - 1, 10, 20), date(y - 1, 10, 20),
                 harvests=[("lettuce", "bowl", date(y - 1, 5, 25)), ("tomato_cherry", "basket", date(y - 1, 8, 12)),
                           ("basil", "bowl", date(y - 1, 8, 2)), ("tomato_cherry", "basket", date(y - 1, 8, 30))])
    hist = history_from_seasons([store.get_garden(prev, uid)])
    c2 = _c(location_id="new_haven_ct", goals=["salad", "salsa"], start_mode="now",
            start_date=today - timedelta(days=21), space_type="raised_bed", width_ft=4, length_ft=8,
            has_cats=True, place="Home", plot_history=hist)
    r2 = _rec(c2, [("garlic", "Plant cloves this fall for a big summer harvest."),
                   ("kale", "Tough greens from spring into fall."), ("tomato_cherry", "Next summer's salsa."),
                   ("lettuce", "Fast spring greens.")], "Garlic now; greens and tomatoes next spring.",
              build_recs=[("compost_bin", "Fall leaves make free compost.")])
    _save(uid, "Backyard bed", r2, ["compost_bin"], today - timedelta(days=21), None, today, plot_id=prev)
    # Indoor windowsill (indoor garden)
    c3 = _c(location_id="new_haven_ct", goals=["pesto_herbs", "salad"], start_mode="now", start_date=today - timedelta(days=10),
            space_type="windowsill", num_containers=3, sun="full", sun_basis="south-facing window",
            place="Home – kitchen")
    r3 = _rec(c3, [("microgreens", "Ready in two weeks on a sunny sill."), ("basil", "Fresh pesto year-round."),
                   ("chives", "Snip as you need them.")], "A kitchen windowsill of fast greens and herbs.")
    _save(uid, "Kitchen windowsill", r3, [], today - timedelta(days=10), None, today,
          harvests=[("microgreens", "handful", today - timedelta(days=2))])
    # Finished patio containers from last year
    c4 = _c(location_id="new_haven_ct", goals=["pesto_herbs"], start_date=date(y - 1, 4, 15), space_type="containers",
            num_containers=4, budget_max=150, place="Home – patio")
    r4 = _rec(c4, [("basil", "The heart of pesto."), ("oregano", "Tough and drought-tolerant."),
                   ("chives", "Comes back every spring.")], "A small container herb garden.")
    _save(uid, "Patio herbs", r4, [], date(y - 1, 4, 15), date(y - 1, 10, 15), date(y - 1, 9, 1),
          harvests=[("basil", "bowl", date(y - 1, 7, 18)), ("basil", "basket", date(y - 1, 8, 10), True),
                    ("oregano", "handful", date(y - 1, 7, 25)), ("chives", "handful", date(y - 1, 6, 10))])
    # Future garden in another part of the country: a cabin in Boise, ID
    c5 = _c(location_id="boise_id", goals=["kids", "pollinator"], start_date=date(y + 1, 4, 1), space_type="in_ground",
            width_ft=6, length_ft=10, budget_max=250, place="Boise cabin")
    r5 = _rec(c5, [("sunflower", "Giant and fast in Boise's sunny, dry summers."),
                   ("zinnia", "Butterflies love them."), ("bean_bush", "Easy, quick and kid-friendly.")],
              "A sunny cabin strip of easy flowers and beans.")
    _save(uid, "Cabin garden (Boise)", r5, [], date(y + 1, 4, 1), None, None)


# ---------- test_household: Atlanta, family of 4 ----------
def _household(uid: int, today: date, y: int) -> None:
    c = _c(location_id="atlanta_ga", audience="household", adults=2, kids=2, skill_level="intermediate",
           goals=["salsa", "kids"], start_date=date(y, 3, 10), space_type="in_ground", width_ft=10, length_ft=10,
           has_dogs=True, budget_max=500, place="Home")
    r = _rec(c, [("tomato_paste", "Sauce and salsa for four."), ("pepper_jalapeno", "Mild heat for salsa."),
                 ("bean_bush", "Kids can pick these by the handful."), ("zucchini", "Very productive in Georgia heat."),
                 ("basil", "Grows like a weed in Atlanta summers.")], "A family salsa garden with kid-friendly beans.")
    _save(uid, "Backyard family garden", r, [], date(y, 3, 10), None, today,
          harvests=[("bean_bush", "bowl", date(y, 6, 5)), ("zucchini", "basket", date(y, 6, 25)),
                    ("tomato_paste", "basket", date(y, 7, 20)), ("pepper_jalapeno", "bowl", date(y, 8, 2)),
                    ("tomato_paste", "basket", date(y, 8, 15), True)])


# ---------- test_school: Minneapolis, grades 3–5 ----------
def _school(uid: int, today: date, y: int) -> None:
    def school(start: date, ss: date, se: date):
        return _c(location_id="minneapolis_mn", audience="school", grade_band="3-5", skill_level="intermediate",
                  goals=["salad", "kids"], start_date=start, space_type="raised_bed", width_ft=8, length_ft=8,
                  school_start=ss, school_end=se, summer_care=False, budget_max=300, place="Lincoln Elementary")
    lessons = [("radish", "Ready in about a month: fast results for kids.", "3-5: measure and graph growth each week"),
               ("lettuce", "Harvested before summer break.", "3-5: compare leaf shapes and textures"),
               ("spinach", "Cool-season greens picked in May.", "3-5: count leaves and predict the harvest")]
    r1 = _rec(school(date(y - 1, 3, 20), date(y - 2, 9, 2), date(y - 1, 6, 12)), lessons, "Spring classroom bed.")
    prev = _save(uid, "Classroom raised beds", r1, [], date(y - 1, 3, 20), date(y - 1, 6, 12), date(y - 1, 6, 12),
                 harvests=[("radish", "bowl", date(y - 1, 5, 15)), ("lettuce", "bowl", date(y - 1, 5, 28)),
                           ("spinach", "handful", date(y - 1, 5, 30))])
    r2 = _rec(school(date(y, 8, 25), date(y, 9, 2), date(y + 1, 6, 12)),
              [("radish", "A quick fall harvest in the first weeks of school.", "3-5: graph days to harvest"),
               ("spinach", "A cool fall crop picked in October.", "3-5: test which leaves survive the first frost"),
               ("garlic", "Planted in fall, harvested before summer break.", "3-5: track a crop across seasons")],
              "Fall classroom bed with an overwintering crop.")
    _save(uid, "Classroom raised beds", r2, [], date(y, 8, 25), None, today, plot_id=prev)


# ---------- community gardens: New Haven (organizer) and Seattle (admin runs it) ----------
ELM_PLOTS = [("1", "Maria", "beginner", ["salsa", "salad"], ["tomato_cherry", "scallion", "lettuce"]),
             ("2", "Dev", "intermediate", ["pickling"], ["cucumber_pickling", "dill", "beet"]),
             ("3", "Ana & kids", "beginner", ["kids", "pollinator"], ["radish", "nasturtium", "sunflower"]),
             ("4", "", "beginner", ["salad"], ["lettuce", "kale", "arugula"])]
SEA_PLOTS = [("A", "Kim", "beginner", ["salad"], ["lettuce", "kale", "pea_snap"]),
             ("B", "Luis", "intermediate", ["salsa"], ["tomato_cherry", "tomatillo", "cilantro"]),
             ("C", "", "beginner", ["pollinator"], ["calendula", "zinnia", "cosmos"])]


def _community(organizer: int, name: str, loc_id: str, place: str, start: date, plots, today: date,
               shared: list[str], harvest_rows: dict) -> tuple[dict, dict[str, int]]:
    settings = {"location_id": loc_id, "place": place, "start_date": start.isoformat(), "space_type": "raised_bed",
                "plot_w": 4, "plot_l": 8, "plot_budget": 150, "shared_builds": shared, "beds_ready": True}
    grp = store.create_group(organizer, name, settings)
    out: dict[str, int] = {}
    for plot, who, skill, goals, ids in plots:
        c = _c(location_id=loc_id, place=place, start_date=start, space_type="raised_bed", width_ft=4, length_ft=8,
               goals=goals, skill_level=skill, sun_basis="from the sign-up sheet", budget_max=150,
               audience="community", beds_ready=True)
        r = _rec(c, [(i, "Picked for this plot's goals.") for i in ids], "Community plot.")
        gid = store.save_garden(organizer, f"Plot {plot}" + (f" – {who}" if who else ""), rec_to_json(r), ids, [],
                                group_id=grp["id"], plot_label=plot)
        store.set_dates(gid, organizer, start, None)
        if who:
            keys = [task_key(t) for t in assemble(r, ids, []).tasks if t.when < today]
            store.set_checks_bulk(gid, organizer, keys)
        for pid, size, when, *don in harvest_rows.get(plot, []):
            p = plants()[pid]
            store.log_harvest(gid, organizer, pid, size, store.size_to_lb(size, p.category, p.edible),
                              donated=bool(don), picked_on=when)
        out[plot] = gid
    return store.get_group(grp["id"], organizer), out


def _communities(ids: dict[str, int], today: date, y: int) -> None:
    from .community import work_days
    start = date(y, 3, 1) if today.month >= 7 else date(y - 1, 3, 1)
    sy = start.year
    elm, elm_plots = _community(
        ids["test_organizer"], "Elm Street Community Garden", "new_haven_ct", "Elm St lot", start, ELM_PLOTS, today,
        ["compost_bin", "rain_barrel"],
        {"1": [("lettuce", "bowl", date(sy, 5, 18)), ("tomato_cherry", "basket", date(sy, 8, 9)),
               ("tomato_cherry", "basket", date(sy, 8, 23), True)],
         "2": [("cucumber_pickling", "basket", date(sy, 7, 22)), ("beet", "bowl", date(sy, 7, 1))],
         "3": [("radish", "bowl", date(sy, 5, 12)), ("sunflower", "bunch", date(sy, 8, 20))]})
    for d in work_days(elm, today - timedelta(days=365), months=13):
        if d < today and d.month != 7:
            store.set_group_task(elm["id"], ids["test_organizer"], f"workday|{d.isoformat()}", claim=True, done=True)
    for key in ("shared|build|compost_bin", "shared|build|rain_barrel", "shared|seed-order", "shared|seed-handout"):
        store.set_group_task(elm["id"], ids["test_organizer"], key, claim=True, done=True)
    store.join_group(ids["test_admin"], elm["join_code"])
    store.set_role(elm["id"], ids["test_organizer"], ids["test_admin"], "admin")
    store.join_group(ids["test_member"], elm["join_code"])
    store.claim_plot(elm_plots["1"], elm["id"], ids["test_member"], "test_member")
    store.claim_plot(elm_plots["2"], elm["id"], ids["test_admin"], "test_admin")

    sea_start = date(y, 3, 15) if today.month >= 7 else date(y - 1, 3, 15)
    sea, sea_plots = _community(
        ids["test_admin"], "Rainier Valley Community Garden", "seattle_wa", "Rainier Ave lot", sea_start, SEA_PLOTS,
        today, ["compost_bin"],
        {"A": [("lettuce", "bowl", date(sea_start.year, 5, 20)), ("pea_snap", "bowl", date(sea_start.year, 6, 15))],
         "B": [("tomato_cherry", "bowl", date(sea_start.year, 8, 28))]})
    store.join_group(ids["test_member"], sea["join_code"])
    store.claim_plot(sea_plots["A"], sea["id"], ids["test_member"], "test_member")


# ---------- demo: one showcase account with a bit of everything ----------
def ensure_demo(today: date | None = None) -> None:
    """Separate from the personas so it can be added to a database that already has them."""
    today = today or date.today()
    try:
        uid = store.create_user(DEMO_USER, TEST_PASSWORD)["id"]
    except store.AuthError:
        return   # already there
    y = today.year
    # Backyard bed in New Haven: last year's salsa season, then this fall's garlic and greens
    c1 = _c(location_id="new_haven_ct", goals=["salsa", "pesto_herbs"], start_date=date(y - 1, 4, 1),
            space_type="raised_bed", width_ft=4, length_ft=8, has_cats=True, place="Home")
    r1 = _rec(c1, [("tomato_cherry", "A forgiving first tomato that keeps producing."),
                   ("arugula", "Peppery leaves for pesto and salads, ready in weeks."),
                   ("basil", "Pesto, and a good neighbor for tomatoes."), ("scallion", "Quick, easy salsa onions.")],
              "First season: a salsa-and-pesto bed.", build_recs=[("trellis", "Keeps cherry tomatoes off the ground.")])
    prev = _save(uid, "Backyard bed", r1, ["raised_bed", "trellis"], date(y - 1, 4, 1), date(y - 1, 10, 20),
                 date(y - 1, 10, 20),
                 harvests=[("scallion", "handful", date(y - 1, 6, 20)), ("basil", "bowl", date(y - 1, 7, 14)),
                           ("tomato_cherry", "basket", date(y - 1, 8, 5)),
                           ("arugula", "bowl", date(y - 1, 5, 28)),
                           ("tomato_cherry", "basket", date(y - 1, 8, 26), True),
                           ("tomato_cherry", "basket", date(y - 1, 9, 12))])
    hist = history_from_seasons([store.get_garden(prev, uid)])
    c2 = _c(location_id="new_haven_ct", goals=["salad"], start_mode="now", start_date=today - timedelta(days=28),
            space_type="raised_bed", width_ft=4, length_ft=8, has_cats=True, place="Home", plot_history=hist)
    r2 = _rec(c2, [("garlic", "Plant cloves now for a big harvest next July."),
                   ("radish", "Ready about a month after spring sowing."),
                   ("kale", "Sweeter after frost; picks into winter."), ("lettuce", "Fast spring greens.")],
              "Garlic and kale this fall; lettuce and radishes in early spring.",
              build_recs=[("compost_bin", "Fall leaves make free compost.")])
    _save(uid, "Backyard bed", r2, ["compost_bin"], today - timedelta(days=28), None, today, plot_id=prev,
          harvests=[("kale", "handful", today - timedelta(days=4))])
    # Kitchen windowsill, growing now
    c3 = _c(location_id="new_haven_ct", goals=["pesto_herbs", "salad"], start_mode="now",
            start_date=today - timedelta(days=18), space_type="windowsill", num_containers=3,
            sun_basis="south-facing window", place="Home – kitchen")
    r3 = _rec(c3, [("microgreens", "Ready in about two weeks on a sunny sill."),
                   ("basil", "Fresh leaves all winter."), ("chives", "Snip as you need them.")],
              "A kitchen windowsill of fast greens and herbs.")
    _save(uid, "Kitchen windowsill", r3, [], today - timedelta(days=18), None, today,
          harvests=[("microgreens", "handful", today - timedelta(days=5)),
                    ("microgreens", "handful", today - timedelta(days=1))])
    # Last summer's balcony containers, finished
    c4 = _c(location_id="new_haven_ct", goals=["herbal_tea"], start_date=date(y - 1, 5, 1), space_type="containers",
            num_containers=4, budget_max=150, place="Home – balcony")
    r4 = _rec(c4, [("lemon_balm", "Lemony tea, almost impossible to kill."),
                   ("thyme", "A soothing tea, and it shrugs off dry spells."), ("mint", "Keep it in its own pot.")],
              "A balcony tea garden in pots.")
    _save(uid, "Balcony tea pots", r4, [], date(y - 1, 5, 1), date(y - 1, 10, 1), date(y - 1, 10, 1),
          harvests=[("mint", "handful", date(y - 1, 6, 28)), ("thyme", "handful", date(y - 1, 7, 10)),
                    ("lemon_balm", "bowl", date(y - 1, 7, 30))])
    # Next spring: a front-yard flower strip for pollinators
    c5 = _c(location_id="new_haven_ct", goals=["pollinator", "cut_flowers"], start_date=date(y + 1, 4, 15),
            space_type="in_ground", width_ft=3, length_ft=12, budget_max=200, place="Home – front yard")
    r5 = _rec(c5, [("zinnia", "Bright, easy and loved by butterflies."), ("cosmos", "Airy flowers for bouquets."),
                   ("sunflower", "A tall back row for bees.")], "A cheerful pollinator strip by the sidewalk.")
    _save(uid, "Front-yard flowers", r5, [], date(y + 1, 4, 15), None, None)
    # Community garden: admin at Elm Street with its own plot (Plot 4)
    elm = next((g for u in ("test_organizer",) for g in _groups_of(u) if g["name"].startswith("Elm")), None)
    if not elm:
        return
    org = elm["organizer_id"]
    store.join_group(uid, elm["join_code"])
    store.set_role(elm["id"], org, uid, "admin")
    plot = next((p for p in store.group_plots(elm["id"]) if p["plot_label"] == "4"), None)
    if plot and store.claim_plot(plot["id"], elm["id"], uid, DEMO_USER):
        store.update_garden(plot["id"], uid, name=f"Plot 4 – {DEMO_USER}")
        g = store.get_garden(plot["id"], uid)
        r = rec_from_json(g["rec"])
        keys = [task_key(t) for t in assemble(r, g["chosen"], []).tasks if t.when < today]
        store.set_checks_bulk(plot["id"], uid, keys)
        sy = r.constraints.start_date.year
        for pid, size, when, *don in [("arugula", "bowl", date(sy, 5, 10)), ("lettuce", "bowl", date(sy, 5, 24)),
                                      ("kale", "bowl", date(sy, 6, 30)), ("kale", "basket", date(sy, 9, 15), True)]:
            if when <= today:
                p = plants()[pid]
                store.log_harvest(plot["id"], uid, pid, size, store.size_to_lb(size, p.category, p.edible),
                                  donated=bool(don), picked_on=when)


def _groups_of(username: str) -> list[dict]:
    with store.connect() as db:
        row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return store.my_groups(row["id"]) if row else []
