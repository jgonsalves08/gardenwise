"""Page: This week — what's due across all your gardens, based on today's date."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from .. import store, ui
from ..pipeline import task_key
from .gardens import load_plan, need_login

HORIZON_DAYS = 14


def page() -> None:
    if need_login("This week"):
        return
    user = st.session_state.user
    today = date.today()
    ui.hero("📋 This week", f"What to do now, as of {today:%A, %B %d}. Tick things off as you go.")
    ui.page_tip("week", "Everything due in the next two weeks across your saved gardens. Tick tasks as you do them; "
                        "when something's ready to pick, tap a size to log the harvest (optional).")

    community_tasks(user, today)
    gardens = store.list_gardens(user["id"])
    if not gardens:
        st.info("Save a garden plan first, and its tasks will show up here.")
        return

    gardens = [g for g in gardens if store.garden_status(g) != "past"]
    if not gardens:
        st.info("All your gardens are finished. Plan a new one to see tasks here.")
        return
    anything = False
    for g in gardens:
        rec, plan = load_plan(g)
        cl = ui.Checklist(garden_id=g["id"], owner_id=user["id"], done=store.get_checks(g["id"]))
        open_tasks = [t for t in plan.tasks if task_key(t) not in cl.done]
        overdue = [t for t in open_tasks if t.when < today]
        soon = [t for t in open_tasks if today <= t.when <= today + timedelta(days=HORIZON_DAYS)]
        harvesting = [s for s in plan.schedules if s.harvest_start <= today <= s.harvest_end]
        nxt = next((t for t in open_tasks if t.when > today + timedelta(days=HORIZON_DAYS)), None)

        with st.container(border=True):
            future = store.garden_status(g) == "future"
            st.markdown(f"### {g['name']}" + (" · *starts " + f"{g['start_date']:%b %d}*" if future else ""))
            if overdue:
                anything = True
                st.markdown("**⏰ Overdue**")
                for t in overdue:
                    ui.check_box(cl, task_key(t), ui.md(f"{ui.TASK_ICONS[t.kind]} **{t.when:%b %d}** · {t.title}"),
                                 help=t.detail or None)
            if soon:
                anything = True
                st.markdown(f"**📅 Next {HORIZON_DAYS} days**")
                for t in soon:
                    ui.check_box(cl, task_key(t), ui.md(f"{ui.TASK_ICONS[t.kind]} **{t.when:%b %d}** · {t.title}"),
                                 help=t.detail or None)
            if harvesting:
                anything = True
                st.markdown("**🧺 Ready to pick now** <span class='muted'>(optional: tap a size to log it)</span>",
                            unsafe_allow_html=True)
                for sch in harvesting:
                    p = next(p for p in plan.plants if p.id == sch.plant_id)
                    ui.quick_harvest_row(cl, p, f"wk_{g['id']}_{p.id}")
            if not (overdue or soon or harvesting):
                msg = "Nothing due in the next two weeks. 🌤️"
                if nxt:
                    msg += f" Next up: **{nxt.title}** on {nxt.when:%b %d, %Y}."
                st.caption(ui.md(msg))
    if not anything:
        st.caption("You're all caught up.")


def community_tasks(user: dict, today: date) -> None:
    from .. import community as cm
    from .community import shared_tasks

    for grp in store.my_groups(user["id"]):
        state = store.group_task_state(grp["id"])
        upcoming = [(d, k, label) for d, k, label, _ in shared_tasks(grp, cm.plot_views(grp))
                    if d <= today + timedelta(days=HORIZON_DAYS) and not state.get(k, {}).get("done_at")]
        if not upcoming:
            continue
        with st.container(border=True):
            st.markdown(f"### 🏘️ {grp['name']}")
            for d, k, label in upcoming:
                who = state.get(k, {}).get("username")
                tag = f" — 🙋 {who}" if who else " — *unclaimed*"
                st.markdown(ui.md(f"**{d:%b %d}** · {label}{tag}"))
            if st.button("Open community garden", key=f"wk_grp_{grp['id']}"):
                st.session_state.open_group = grp["id"]
                st.switch_page(st.session_state.pages["community"])
