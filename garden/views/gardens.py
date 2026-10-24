"""Page: My gardens — saved plans with tickable tasks and shopping lists (login required)."""

from __future__ import annotations

from datetime import date

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
    return rec, assemble(rec, g["chosen"], g["addons"], owned=owned)


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

    ui.hero("🌿 My gardens", "Your saved plans: what's growing now, what's coming up, and what you've grown before.")
    ui.page_tip("gardens", "Open a garden to see its layout, calendar and shopping list, and tick things off. "
                           "Use ⋯ More to finish, reopen or delete a garden, or start a new one at the same place.")
    st.page_link(st.session_state.pages["plan"], label="➕ Plan a new garden", icon="🌱")
    gardens = store.list_gardens(user["id"])
    if not gardens:
        st.info("No saved gardens yet. Make a plan, then press **Save to My gardens** at the bottom.")
        return
    flash = st.session_state.pop("garden_flash", None)
    if flash:
        st.success(flash)

    places = sorted({store.place_of(g) for g in gardens if store.place_of(g)}, key=str.lower)
    if places:
        pick = st.selectbox("📍 Show gardens at", ["All places"] + places + ["(no place set)"])
        if pick == "(no place set)":
            gardens = [g for g in gardens if not store.place_of(g)]
        elif pick != "All places":
            gardens = [g for g in gardens if store.place_of(g).lower() == pick.lower()]
    by_status: dict[str, list[dict]] = {"current": [], "future": [], "past": []}
    for g in gardens:
        by_status[store.garden_status(g)].append(g)
    for status, title, blurb in SECTIONS:
        group = by_status[status]
        if not group:
            continue
        st.markdown(f"## {title} ({len(group)})")
        st.caption(blurb)
        cols = st.columns(2)
        for i, g in enumerate(group):
            with cols[i % 2].container(border=True):
                garden_card(g, status, user)


def garden_card(g: dict, status: str, user: dict) -> None:
    rec, plan = load_plan(g, user["id"])
    loc = locations()[rec.constraints.location_id]
    done = store.get_checks(g["id"])
    st.markdown(f"### {g['name']}")
    place = store.place_of(g)
    place_badge = f'<span class="badge">📍 {ui.html.escape(place)}</span>' if place else ""
    st.markdown(f"{STATUS_BADGE[status]}{place_badge} <span class='muted'>{date_line(g)}</span>",
                unsafe_allow_html=True)
    st.caption(f"{loc.label} · {', '.join(p.name for p in plan.plants)}")
    st.markdown(progress_badges(plan, done), unsafe_allow_html=True)
    b1, b2 = st.columns([1, 1])
    if b1.button("Open", key=f"open_{g['id']}", type="primary", width="stretch"):
        st.session_state.open_garden = g["id"]
        st.rerun()
    with b2.popover("⋯ More", width="stretch"):
        lifecycle_buttons(g, status, user, key=f"card_{g['id']}")
        new_garden_here(g, rec, key=f"card_{g['id']}")
        st.markdown("---")
        delete_control(g, user, key=f"card_{g['id']}")


def lifecycle_buttons(g: dict, status: str, user: dict, key: str) -> None:
    today = date.today()
    if status == "current":
        if st.button("✅ Mark as finished", key=f"{key}_finish", width="stretch",
                     help="Moves it to My past gardens with today as the end date."):
            store.set_dates(g["id"], user["id"], g["start_date"], max(today, g["start_date"]))
            st.session_state.garden_flash = f"“{g['name']}” moved to your past gardens."
            st.session_state.open_garden = None
            st.rerun()
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


def delete_control(g: dict, user: dict, key: str) -> None:
    sure = st.checkbox("I want to delete this garden", key=f"{key}_delsure")
    if st.button("🗑️ Delete permanently", key=f"{key}_del", disabled=not sure, width="stretch"):
        store.delete_garden(g["id"], user["id"])
        st.session_state.garden_flash = f"Deleted “{g['name']}”."
        st.session_state.open_garden = None
        st.rerun()


def detail(g: dict, user: dict) -> None:
    rec, plan = load_plan(g, user["id"])
    c = rec.constraints
    loc = locations()[c.location_id]
    status = store.garden_status(g)
    cl = ui.Checklist(garden_id=g["id"], owner_id=user["id"], done=store.get_checks(g["id"]))

    if st.button("← All gardens"):
        st.session_state.open_garden = None
        st.rerun()
    ui.hero(f"🌿 {g['name']}", f"{loc.label} · {date_line(g)}")
    top1, top2 = st.columns([3, 1])
    top1.markdown(f"{STATUS_BADGE[status]}", unsafe_allow_html=True)
    with top2:
        lifecycle_buttons(g, status, user, key=f"detail_{g['id']}")
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

    with st.expander("⚙️ Garden settings"):
        settings(g, rec, user)


def settings(g: dict, rec, user: dict) -> None:
    c = rec.constraints
    gid = g["id"]
    locs = locations()
    loc_ids = sorted(locs, key=lambda i: (locs[i].state, locs[i].name))
    new_name = st.text_input("Name", value=g["name"], max_chars=60, key=f"rename_{gid}")

    st.markdown("**📍 Where is it?**")
    l1, l2 = st.columns(2)
    loc_id = l1.selectbox("Nearest location", loc_ids, index=loc_ids.index(c.location_id),
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
            store.update_garden(gid, user["id"], name=new_name)
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
    with st.container(border=True):
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
