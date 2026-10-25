"""Page: My gardens — saved plans with tickable tasks and shopping lists (login required)."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import llm, store, ui
from ..agents.selector import candidates
from ..data import location_for_zip, locations
from ..pipeline import assemble, rec_from_json, rec_to_json, recommend, shop_key, task_key
from ..safety import clean_place
from ..verifier import verify

SUN_LABELS = {"full": "☀️ Full sun (6+ hrs)", "part": "⛅ Part sun (3–6 hrs)",
              "shade": "🌥️ Mostly shade (about 2–4 hrs)", "unknown": "❓ Not sure"}


def need_login(what: str) -> bool:
    if st.session_state.get("user"):
        return False
    ui.hero("🌿 " + what, "Log in to save gardens and keep track of them across the season.")
    st.info("Accounts are optional. Use **👤 Log in / Sign up** at the top right. You can always plan a "
            "garden as a guest from **Plan a garden**.")
    return True


def load_plan(g: dict, owner_id: int | None = None):
    rec = rec_from_json(g["rec"])
    owned = store.builds_at_place(owner_id, rec.constraints.place, exclude_id=g["id"]) if owner_id else set()
    plan = assemble(rec, g["chosen"], g["addons"], owned=owned)
    moved = store.get_task_dates(g["id"])
    if moved:   # the gardener's own dates replace the recommended ones (and remember them)
        plan.tasks = sorted((t.model_copy(update={"when": moved[task_key(t)], "recommended": t.when})
                             if task_key(t) in moved else t for t in plan.tasks), key=lambda t: t.when)
    return rec, plan


def progress_badges(plan, done: dict[str, str]) -> str:
    today = date.today()
    tasks_done = sum(task_key(t) in done for t in plan.tasks)
    lines = plan.shopping_lines()
    bought = sum(shop_key(g, m.item) in done for g, m in lines)
    due = [t for t in plan.tasks if task_key(t) not in done and t.when <= today]
    out = (f'<span class="badge done">{tasks_done}/{len(plan.tasks)} tasks</span>'
           f'<span class="badge">{bought}/{len(lines)} items bought</span>')
    if due:
        out += f'<span class="badge warn">{len(due)} due now</span>'
    return out


SECTIONS = [
    ("current", "🌱 Current gardens", "Growing now. Tick off tasks as you go."),
    ("future", "🗓️ Future gardens", "Planned but not started yet. Prep tasks may already be due."),
    ("past", "📚 My past gardens", "Finished gardens, kept for reference and next season's ideas."),
]
STATUS_BADGE = {"current": '<span class="badge done">current</span>',
                "future": '<span class="badge">future</span>',
                "past": '<span class="badge warn">finished</span>'}


def date_line(g: dict) -> str:
    s, e = g["start_date"], g["end_date"]
    if e:
        return f"{s:%b %d, %Y} – {e:%b %d, %Y}"
    if s > date.today():
        return f"Starts {s:%b %d, %Y}"
    return f"Started {s:%b %d, %Y} · ongoing"


def page() -> None:
    if need_login("My gardens"):
        return
    user = st.session_state.user
    gid = st.session_state.get("open_garden")
    if gid:
        g = store.get_garden(gid, user["id"])
        if g:
            detail(g, user)
            return
        st.session_state.open_garden = None

    ui.hero("🌿 My gardens", "Each garden is a plot of land. Every year you plan it again as a new season, "
                            "and earlier seasons stay as history.")
    ui.page_tip("gardens", "Open a garden to see this season's layout, calendar and shopping list. When a season "
                           "ends, use 🔁 Plan next season here: your site settings carry over and you get "
                           "crop-rotation tips from earlier seasons.")
    st.page_link(st.session_state.pages["plan"], label="➕ Plan a new garden (a different plot)", icon="🌱")
    all_plots = store.plots(user["id"])
    if not all_plots:
        st.info("No saved gardens yet. Make a plan, then press **Save to My gardens** at the bottom.")
        return
    flash = st.session_state.pop("garden_flash", None)
    if flash:
        st.success(flash)

    places = sorted({store.place_of(p["latest"]) for p in all_plots if store.place_of(p["latest"])}, key=str.lower)
    if places:
        pick = st.selectbox("📍 Show gardens at", ["All places"] + places + ["(no place set)"])
        if pick == "(no place set)":
            all_plots = [p for p in all_plots if not store.place_of(p["latest"])]
        elif pick != "All places":
            all_plots = [p for p in all_plots if store.place_of(p["latest"]).lower() == pick.lower()]
    by_status: dict[str, list[dict]] = {"current": [], "future": [], "past": []}
    for p in all_plots:
        by_status[store.garden_status(p["active"])].append(p)
    for status, title, blurb in SECTIONS:
        group = by_status[status]
        if not group:
            continue
        st.markdown(f"## {title} ({len(group)})")
        st.caption(blurb)
        cols = st.columns(2)
        for i, p in enumerate(group):
            with cols[i % 2].container(border=True, key=ui.card_key()):
                plot_card(p, status, user)


def plot_card(p: dict, status: str, user: dict) -> None:
    g = p["active"]
    rec, plan = load_plan(g, user["id"])
    loc = locations()[rec.constraints.location_id]
    done = store.get_checks(g["id"])
    st.markdown(f"### {html.escape(p['name'])}")
    place = store.place_of(g)
    badges = STATUS_BADGE[status]
    badges += f'<span class="badge">📍 {html.escape(place)}</span>' if place else ""
    n = len(p["seasons"])
    badges += f'<span class="badge">🗂️ {n} season{"s" if n != 1 else ""}</span>'
    if p["latest"]["id"] != g["id"]:
        badges += f'<span class="badge">next: {store.season_label(p["latest"])}</span>'
    grp = community_of(g, user)
    if grp:
        badges += f'<span class="badge community">🏘️ Community plot · {html.escape(grp["name"])}</span>'
    st.markdown(f"{badges} <span class='muted'>{store.season_label(g)} · {date_line(g)}</span>",
                unsafe_allow_html=True)
    st.caption(f"{loc.label} · {', '.join(x.name for x in plan.plants)}")
    st.markdown(progress_badges(plan, done), unsafe_allow_html=True)
    if season_looks_done(g, plan, loc):
        st.markdown('<span class="badge warn">🍂 season looks finished</span>', unsafe_allow_html=True)
    b1, b2 = st.columns([1, 1])
    if b1.button("Open", key=f"open_{g['id']}", type="primary", width="stretch"):
        st.session_state.open_garden = g["id"]
        st.rerun()
    with b2.popover("⋯ More", width="stretch"):
        if grp:
            open_community_button(grp, key=f"card_{g['id']}")
            st.caption("This plot belongs to a community garden. Its organizers manage seasons and removal.")
        else:
            lifecycle_buttons(g, status, user, key=f"card_{g['id']}")
            next_season_button(g, rec, user, key=f"card_{g['id']}")
            new_garden_here(g, rec, key=f"card_{g['id']}")
            st.markdown("---")
            delete_control(g, user, key=f"card_{g['id']}", whole_plot=True)


def community_of(g: dict, user: dict) -> dict | None:
    """The community garden this plot belongs to (if the user is a member of it)."""
    return store.get_group(g["group_id"], user["id"]) if g.get("group_id") else None


def open_community_button(grp: dict, key: str) -> None:
    if st.button(f"🏘️ Open {grp['name']}", key=f"{key}_grp", width="stretch"):
        st.session_state.open_group = grp["id"]
        st.session_state.open_garden = None
        st.switch_page(st.session_state.pages["community"])


def season_looks_done(g: dict, plan, loc) -> bool:
    """Past the first fall frost of the season's year, with every harvest window over."""
    if store.garden_status(g) != "current" or not plan.schedules:
        return False
    today = date.today()
    last_harvest = max(s.harvest_end for s in plan.schedules)
    frost = loc.first_frost_on(last_harvest.year)
    return today > last_harvest and today >= min(frost, last_harvest + timedelta(days=1))


def next_season_prefill(g: dict, rec, user: dict) -> dict:
    """Carry the site over to a new season and pass this plot's history for crop rotation."""
    from ..rotation import history_from_seasons

    c = rec.constraints
    seasons = store.plot_seasons(user["id"], g["plot_id"])
    pf = {
        "location_id": c.location_id, "place": c.place, "skill_level": c.skill_level, "has_cats": c.has_cats,
        "has_dogs": c.has_dogs, "audience": c.audience if c.audience in ("me", "household", "school") else "me",
        "adults": c.adults, "kids": c.kids, "space_type": c.space_type, "num_containers": c.num_containers,
        "budget": (c.budget_min, c.budget_max if c.budget_max is not None else 1500),
        "goals": list(c.goals), "start_mode": "next_season",
        "plot_id": g["plot_id"], "plot_name": g["name"], "from_season": store.season_label(g),
        "plot_history": history_from_seasons(seasons), "prev_season_id": g["id"],
    }
    if c.space_type in ("raised_bed", "in_ground"):
        pf |= {"width_ft": c.width_ft, "length_ft": c.length_ft}
    if c.sun != "unknown":
        pf["sun"] = c.sun
    return pf


def next_season_button(g: dict, rec, user: dict, key: str, primary: bool = False) -> None:
    if st.button("🔁 Plan next season here", key=f"{key}_next", width="stretch",
                 type="primary" if primary else "secondary",
                 help="Same plot, new year: site settings carry over and you get crop-rotation tips."):
        st.session_state.prefill = next_season_prefill(g, rec, user)
        if st.session_state.prefill.get("audience"):
            st.session_state["audience"] = st.session_state.prefill["audience"]
        st.session_state.rec = None
        st.switch_page(st.session_state.pages["plan"])


def open_tasks(g: dict, user: dict) -> list:
    _rec, plan = load_plan(g, user["id"])
    done = store.get_checks(g["id"])
    return [t for t in plan.tasks if task_key(t) not in done]


def finish_season(g: dict, user: dict, mark_done: bool, plan_next: bool = False, rec=None) -> None:
    if mark_done:
        store.set_checks_bulk(g["id"], user["id"], [task_key(t) for t in open_tasks(g, user)])
    store.set_dates(g["id"], user["id"], g["start_date"], max(date.today(), g["start_date"]))
    st.session_state.garden_flash = f"Finished the {store.season_label(g)} of “{g['name']}”."
    if plan_next and rec is not None:
        st.session_state.prefill = next_season_prefill(store.get_garden(g["id"], user["id"]), rec, user)
        st.session_state.rec = None
        st.switch_page(st.session_state.pages["plan"])
    st.session_state.open_garden = None
    st.rerun()


@st.dialog("Finish this season?")
def finish_dialog(g: dict, user: dict, plan_next: bool = False) -> None:
    rec = rec_from_json(g["rec"])
    left = open_tasks(g, user)
    if not left:
        st.markdown("All tasks are ticked off. 🎉")
        if st.button("✅ Finish season", type="primary", width="stretch"):
            finish_season(g, user, mark_done=False, plan_next=plan_next, rec=rec)
        return
    st.markdown(f"**{len(left)} task(s) aren't ticked off yet**, for example:")
    for t in left[:5]:
        st.markdown(ui.md(f"- {ui.TASK_ICONS[t.kind]} {t.when:%b %d} · {t.title}"))
    st.caption("Did you do them and just not tick them? Mark them done. If you skipped them, leave them: "
               "they'll show as skipped in this season's history, which keeps your harvest stats honest.")
    if st.button("✅ I did them: mark all done and finish", type="primary", width="stretch"):
        finish_season(g, user, mark_done=True, plan_next=plan_next, rec=rec)
    if st.button("⏭️ Finish and keep them as skipped", width="stretch"):
        finish_season(g, user, mark_done=False, plan_next=plan_next, rec=rec)
    if st.button("Cancel", type="tertiary", width="stretch"):
        st.rerun()


def lifecycle_buttons(g: dict, status: str, user: dict, key: str) -> None:
    today = date.today()
    if status == "current":
        if st.button("✅ Mark as finished", key=f"{key}_finish", width="stretch",
                     help="Moves this season to your history. You'll choose what to do with any unticked tasks."):
            finish_dialog(g, user)
    elif status == "future":
        if st.button("▶️ Start it today", key=f"{key}_start", width="stretch",
                     help="Sets the start date to today; the calendar re-anchors to it."):
            store.set_dates(g["id"], user["id"], today, None)
            st.session_state.garden_flash = f"“{g['name']}” is now a current garden."
            st.rerun()
    else:
        if st.button("↩️ Reopen as current", key=f"{key}_reopen", width="stretch"):
            store.set_dates(g["id"], user["id"], g["start_date"], None)
            st.session_state.garden_flash = f"“{g['name']}” is current again."
            st.rerun()


def new_garden_here(g: dict, rec, key: str) -> None:
    c = rec.constraints
    label = f"➕ New garden at {store.place_of(g)}" if store.place_of(g) else "➕ New garden with these settings"
    if st.button(label, key=f"{key}_newhere", width="stretch",
                 help="Opens the planner with this garden's location, skill, pets and budget filled in."):
        st.session_state.prefill = {
            "location_id": c.location_id, "skill_level": c.skill_level, "has_cats": c.has_cats,
            "has_dogs": c.has_dogs, "place": c.place, "from_name": g["name"],
            "budget": (c.budget_min, c.budget_max if c.budget_max is not None else 1500),
        }
        st.session_state.rec = None
        st.switch_page(st.session_state.pages["plan"])


def delete_control(g: dict, user: dict, key: str, whole_plot: bool = False) -> None:
    what = "this garden and all its seasons" if whole_plot else "this season only"
    sure = st.checkbox(f"I want to delete {what}", key=f"{key}_delsure")
    if st.button("🗑️ Delete permanently", key=f"{key}_del", disabled=not sure, width="stretch"):
        if whole_plot:
            store.delete_plot(user["id"], g["plot_id"])
        else:
            store.delete_garden(g["id"], user["id"])
        st.session_state.garden_flash = f"Deleted {'“' + g['name'] + '”' if whole_plot else store.season_label(g)}."
        st.session_state.open_garden = None
        st.rerun()


def detail(g: dict, user: dict) -> None:
    rec, plan = load_plan(g, user["id"])
    c = rec.constraints
    loc = locations()[c.location_id]
    status = store.garden_status(g)
    cl = ui.Checklist(garden_id=g["id"], owner_id=user["id"], done=store.get_checks(g["id"]), loc=loc,
                      past=status == "past")

    if st.button("← All gardens"):
        st.session_state.open_garden = None
        st.rerun()
    seasons = store.plot_seasons(user["id"], g["plot_id"])
    ui.hero(f"🌿 {html.escape(g['name'])}", f"{loc.label} · {store.season_label(g)} · {date_line(g)}")
    if len(seasons) > 1:
        labels = {s_["id"]: store.season_label(s_) for s_ in seasons}
        pick = st.segmented_control("Season", list(labels), format_func=labels.get, default=g["id"],
                                    key=f"season_pick_{g['plot_id']}")
        if pick and pick != g["id"]:
            st.session_state.open_garden = pick
            st.rerun()
    grp = community_of(g, user)
    top1, top2, top3 = st.columns([2.2, 1, 1])
    top1.markdown(f"{STATUS_BADGE[status]}", unsafe_allow_html=True)
    if grp:
        top1.markdown(f"🏘️ **Your plot in {html.escape(grp['name'])}.** Shared work days, the pooled shopping "
                      "list and the cost split live on the community garden's page.")
        with top3:
            open_community_button(grp, key=f"detail_{g['id']}")
    else:
        with top2:
            lifecycle_buttons(g, status, user, key=f"detail_{g['id']}")
        with top3:
            if g["id"] == seasons[-1]["id"]:
                next_season_button(g, rec, user, key=f"detail_{g['id']}")
    finish_prompt(g, rec, plan, loc, user)
    ui.location_header(loc, plan.total)
    ui.verification_panel(rec)
    misfit_banner(g, rec, user)

    with st.expander("🌿 Plants in this garden (tick or untick to change the plan)"):
        prefix = f"g{g['id']}"
        ui.plant_chooser(rec, plan, prefix, set(g["chosen"]))
        chosen = ui.chosen_from_state(rec, prefix, set(g["chosen"]))
        addons = ui.addons_from_state(prefix, set(g["addons"]))
        if chosen and (chosen != g["chosen"] or addons != g["addons"]):
            store.update_garden(g["id"], user["id"], chosen=chosen, addons=addons)
            st.rerun()

    ui.plan_tabs(rec, plan, f"g{g['id']}", set(g["addons"]), cl)
    ui.export_row(plan, g["name"], store.season_label(g), cl.done, key=f"exp_{g['id']}")

    if len(seasons) > 1:
        season_history(seasons, g)
    with st.expander("⚙️ Garden settings"):
        settings(g, rec, user)


def finish_prompt(g: dict, rec, plan, loc, user: dict) -> None:
    dismissed = st.session_state.setdefault("finish_dismissed", set())
    if g["id"] in dismissed or not season_looks_done(g, plan, loc):
        return
    frost = loc.first_frost_on(max(s_.harvest_end for s_ in plan.schedules).year)
    with st.container(border=True, key=f"finish_{g['id']}"):
        st.markdown(f"**🍂 This season looks finished.** Your average first frost ({frost:%b %d}) has passed "
                    "and every harvest window is over. Wrap it up to keep it as history?")
        a, b, c = st.columns(3)
        if a.button("✅ Finish season", key=f"fin_now_{g['id']}", width="stretch"):
            finish_dialog(g, user)
        if b.button("🔁 Finish & plan next season", key=f"fin_next_{g['id']}", type="primary", width="stretch"):
            finish_dialog(g, user, plan_next=True)
        if c.button("Not yet", key=f"fin_no_{g['id']}", width="stretch"):
            dismissed.add(g["id"])
            st.rerun()


def season_history(seasons: list[dict], current: dict) -> None:
    from ..data import plants as plant_db
    from ..rotation import FAMILY_LABEL, family_of

    with st.expander(f"🗂️ Season history ({len(seasons)} seasons)", expanded=False):
        rows = []
        for s_ in reversed(seasons):
            logs = store.list_harvests(s_["id"])
            fams = sorted({FAMILY_LABEL[f].split(" (")[0] for pid in s_["chosen"] if (f := family_of(pid))})
            rows.append({"Season": store.season_label(s_) + (" (this one)" if s_["id"] == current["id"] else ""),
                         "Status": store.garden_status(s_),
                         "Grew": ", ".join(plant_db()[pid].name for pid in s_["chosen"] if pid in plant_db()),
                         "Families": ", ".join(fams) or "—",
                         "Harvest (approx. lb)": f"{sum(h['est_lb'] for h in logs):,.1f}"})
        st.table(pd.DataFrame(rows).set_index("Season"))
        st.caption("Families matter for crop rotation: Gardenwise suggests not repeating the tomato, squash, "
                   "cabbage, onion, beet and carrot families in the same plot for 3 years.")


def settings(g: dict, rec, user: dict) -> None:
    c = rec.constraints
    gid = g["id"]
    locs = locations()
    loc_ids = sorted(locs, key=lambda i: (locs[i].state, locs[i].name))
    new_name = st.text_input("Name", value=g["name"], max_chars=60, key=f"rename_{gid}")

    st.markdown("**📍 Where is it?**")
    l1, l2 = st.columns(2)
    loc_id = l1.selectbox("Nearest reference city", loc_ids, index=loc_ids.index(c.location_id),
                          format_func=lambda i: locs[i].label, key=f"loc_{gid}")
    zip_code = l2.text_input("…or ZIP code (not saved)", max_chars=5, key=f"zip_{gid}")
    if zip_code:
        zl = location_for_zip(zip_code)
        if zl:
            loc_id = zl.id
            l2.caption(f"Using frost data for **{zl.label}**.")
        else:
            l2.caption("Not in our Northeast list; using the dropdown.")
    p1, p2 = st.columns(2)
    place_raw = p1.text_input("Place nickname", value=c.place, max_chars=40, key=f"place_{gid}",
                              placeholder="e.g. Home – south side",
                              help="Same place = same compost bin and rain barrel. No street addresses.")
    sun = p2.selectbox("Sun at this spot", list(SUN_LABELS), index=list(SUN_LABELS).index(c.sun),
                       format_func=SUN_LABELS.get, key=f"sun_{gid}")

    st.markdown("**📅 Dates**")
    d1, d2 = st.columns(2)
    start = d1.date_input("Start date", value=g["start_date"], key=f"start_{gid}",
                          help="Changing this moves every date in the calendar with it.")
    finished = d2.checkbox("This garden is finished", value=g["end_date"] is not None, key=f"fin_{gid}")
    end = None
    if finished:
        end = d2.date_input("End date", value=g["end_date"] or max(date.today(), start), key=f"end_{gid}")

    if st.button("Save settings", type="primary", key=f"save_settings_{gid}"):
        place, err = clean_place(place_raw)
        if err:
            st.error(err)
            return
        try:
            store.set_dates(gid, user["id"], start, end)
        except ValueError as e:
            st.error(str(e))
            return
        if new_name != g["name"]:
            store.rename_plot(user["id"], g["plot_id"], new_name)   # every season keeps the garden's name
        if (loc_id, sun, place) != (c.location_id, c.sun, c.place):
            # Site changed: update constraints and re-run the (free, code-only) verifier.
            fresh = store.get_garden(gid, user["id"])
            new_c = rec_from_json(fresh["rec"]).constraints.model_copy(update={
                "location_id": loc_id, "sun": sun, "place": place,
                "sun_basis": "set in garden settings" if sun != c.sun else c.sun_basis})
            new_rec = rec_from_json(fresh["rec"])
            new_rec.constraints = new_c
            new_loc = locations()[loc_id]
            new_rec.report = verify(new_rec.picks, new_c, new_loc,
                                    {p.id for p in candidates(new_c, new_loc)})
            store.update_rec(gid, user["id"], rec_to_json(new_rec))
        st.rerun()
    if not g.get("group_id"):   # community plots are removed by the garden's organizers
        st.markdown("---")
        delete_control(g, user, key=f"detail_{gid}")


def misfit_banner(g: dict, rec, user: dict) -> None:
    """If the site changed and some plants no longer pass the verifier, say so and offer an AI re-plan."""
    c = rec.constraints
    loc = locations()[c.location_id]
    picks = [pk for pk in list(rec.picks) + list(rec.alternates) if pk.plant_id in g["chosen"]]
    report = verify(picks, c, loc, {p.id for p in candidates(c, loc)})  # free: code only
    if not report.bad_ids:
        return
    from ..data import plants
    bad = sorted(plants()[i].name for i in report.bad_ids if i in plants())
    reasons = [ch.detail for ch in report.checks if ch.status == "fail"
               and ch.name.split(":")[0] in bad and "candidate" not in ch.name][:4]
    with st.container(border=True, key=ui.card_key()):
        st.warning("⚠️ **Some plants may not suit this garden's current settings:** "
                   + ui.md(", ".join(bad) or "see the checks above") + ".\n\n"
                   + ui.md(" ".join(reasons)))
        a, b = st.columns(2)
        if a.button("🔄 Re-plan with AI for this site", type="primary", key=f"replan_{g['id']}",
                    help="Runs the plant picker again with the new location and sun (uses a few AI calls)."):
            with st.spinner("Re-planning for the new site…"):
                try:
                    new = recommend(rec.constraints, st.session_state.budget)
                except (llm.LLMError, ValueError) as e:
                    st.error(f"Re-plan failed: {e}")
                    return
            store.update_rec(g["id"], user["id"], rec_to_json(new),
                             chosen=[pk.plant_id for pk in new.picks],
                             addons=[bid for bid, _ in new.build_recs])
            st.rerun()
        a.caption("Your ticked tasks are kept where they still apply.")
        b.caption("Or keep the current plants anyway: untick the ones that don't fit "
                  "under “Plants in this garden”.")
