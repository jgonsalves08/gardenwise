"""Page: Community gardens — organizer setup, join codes, CSV import, shared calendar and costs."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import community as cm
from .. import config, store, ui
from ..data import builds, location_for_zip, locations, plants
from ..pipeline import task_key
from ..safety import clean_place
from .gardens import need_login

SHAREABLE = ["compost_bin", "rain_barrel"]
MAX_JOIN_TRIES = 5


def page() -> None:
    if need_login("Community gardens"):
        return
    user = st.session_state.user
    gid = st.session_state.get("open_group")
    if gid:
        group = store.get_group(gid, user["id"])
        if group:
            group_page(group, user)
            return
        st.session_state.open_group = None

    ui.hero("🏘️ Community gardens",
            "Plan every plot at once, share one compost bin and one seed order, and keep the whole "
            "garden on the same calendar.")
    ui.page_tip("community", "Organizers: start a garden on the right and share its join code, or import plots "
                             "from a sign-up sheet. Members: enter the code on the left, then claim a plot.")
    flash = st.session_state.pop("group_flash", None)
    if flash:
        st.success(flash)

    groups = store.my_groups(user["id"])
    if groups:
        st.markdown("### Your community gardens")
        cols = st.columns(2)
        for i, g in enumerate(groups):
            with cols[i % 2].container(border=True, key=ui.card_key()):
                loc = locations()[g["settings"]["location_id"]]
                n_plots = len(store.group_plots(g["id"]))
                st.markdown(f"#### {html.escape(g['name'])}")
                st.markdown(f'<span class="badge">{g["role"]}</span>'
                            f'<span class="badge">{n_plots} plots</span>'
                            f'<span class="badge">{len(store.group_members(g["id"]))} members</span>'
                            f'<span class="muted"> {loc.label}</span>', unsafe_allow_html=True)
                if st.button("Open", key=f"opengrp_{g['id']}", type="primary"):
                    st.session_state.open_group = g["id"]
                    st.rerun()

    left, right = st.columns(2)
    with left, st.container(border=True, key=ui.card_key()):
        join_form(user)
    with right, st.container(border=True, key=ui.card_key()):
        create_form(user)


def join_form(user: dict) -> None:
    st.markdown("#### 🔑 Join with a code")
    st.caption("Your organizer shares a code like **ELM-4821**.")
    tries = st.session_state.setdefault("join_tries", 0)
    with st.form("join_form", border=False):
        code = st.text_input("Join code", max_chars=12, placeholder="ELM-4821")
        go = st.form_submit_button("Join", disabled=tries >= MAX_JOIN_TRIES)
    if tries >= MAX_JOIN_TRIES:
        st.caption("Too many wrong codes this session. Double-check with your organizer and try again later.")
    if go:
        try:
            g = store.join_group(user["id"], code)
            st.session_state.join_tries = 0
            st.session_state.group_flash = f"You joined “{g['name']}”."
            st.session_state.open_group = g["id"]
            st.rerun()
        except store.AuthError as e:
            st.session_state.join_tries = tries + 1
            st.error(str(e))


def create_form(user: dict) -> None:
    st.markdown("#### ➕ Start a community garden")
    st.caption("You'll be the organizer. Members join with a code; you can also import plots from a CSV.")
    locs = locations()
    loc_ids = sorted(locs, key=lambda i: (locs[i].state, locs[i].name))
    with st.form("create_group", border=False):
        name = st.text_input("Garden name", max_chars=60, placeholder="Elm Street Community Garden")
        c1, c2 = st.columns(2)
        loc_id = c1.selectbox("Nearest reference city", loc_ids, index=loc_ids.index("new_haven_ct"),
                              format_func=lambda i: locs[i].label)
        zip_code = c2.text_input("…or ZIP (not saved)", max_chars=5)
        place_raw = st.text_input("Place nickname", max_chars=40, placeholder="e.g. Elm St lot",
                                  help="A nickname, not a street address.")
        today = date.today()
        default_start = date(today.year + 1, 3, 1) if today.month >= 7 else today
        c3, c4 = st.columns(2)
        start = c3.date_input("Season starts", default_start)
        space = c4.selectbox("Plots are", ["raised_bed", "in_ground"],
                             format_func={"raised_bed": "Raised beds", "in_ground": "In-ground plots"}.get)
        c5, c6, c7 = st.columns(3)
        w = c5.number_input("Plot width (ft)", 2.0, 30.0, 4.0, 0.5)
        l = c6.number_input("Plot length (ft)", 2.0, 50.0, 8.0, 0.5)
        plot_budget = c7.number_input("Max $ per plot", 0, 2000, 150, 25,
                                      help="Each plot's plan stays under this (0 = no limit).")
        beds_ready = st.checkbox("Plots already have beds and soil", value=True,
                                 help="Most community gardens do. Untick if each member builds their own bed.")
        shared = st.multiselect("Shared builds (bought once for everyone)", SHAREABLE,
                                default=["compost_bin"],
                                format_func=lambda b: next(x["name"] for x in builds()["builds"] if x["id"] == b))
        go = st.form_submit_button("Create community garden", type="primary")
    if go:
        place, err = clean_place(place_raw)
        if err:
            st.error(err)
            return
        if zip_code and location_for_zip(zip_code):
            loc_id = location_for_zip(zip_code).id
        settings = {"location_id": loc_id, "place": place, "start_date": start.isoformat(),
                    "space_type": space, "plot_w": w, "plot_l": l,
                    "plot_budget": int(plot_budget) or None, "shared_builds": shared,
                    "beds_ready": beds_ready}
        g = store.create_group(user["id"], name, settings)
        st.session_state.group_flash = f"Created! Share join code **{g['join_code']}** with your members."
        st.session_state.open_group = g["id"]
        st.rerun()


# ---------------------------------------------------------------------------
def group_page(group: dict, user: dict) -> None:
    is_org = group["role"] == "organizer"
    is_admin = group["role"] in ("organizer", "admin")
    s = group["settings"]
    loc = locations()[s["location_id"]]
    if st.button("← All community gardens"):
        st.session_state.open_group = None
        st.rerun()
    flash = st.session_state.pop("group_flash", None)
    if flash:
        st.success(flash)
    ui.hero(f"🏘️ {html.escape(group['name'])}",
            f"{loc.label}" + (f" · {html.escape(s['place'])}" if s.get("place") else "")
            + f" · season starts {date.fromisoformat(s['start_date']):%b %d, %Y}")

    views = cm.plot_views(group)
    members = store.group_members(group["id"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Plots", len(views))
    m2.metric("Members", len(members))
    m3.metric("Claimed plots", sum(bool(v.claimed_by) for v in views))
    if is_admin:
        m4.metric("Join code", group["join_code"], help="Share this with members so they can join.")
    else:
        m4.metric("Your role", group["role"])

    tabs = ["🌿 Plots", "📅 Work days & shared tasks", "🛒 Shopping & cost split", "👥 Members"]
    if is_admin:
        tabs += ["➕ Add plots (CSV)", "⚙️ Settings"]
    t = st.tabs(tabs)
    with t[0]:
        plots_tab(group, user, views, is_admin)
    with t[1]:
        tasks_tab(group, user, views)
    with t[2]:
        costs_tab(group, views)
    with t[3]:
        members_tab(group, user, members)
    if is_admin:
        with t[4]:
            import_tab(group, user)
        with t[5]:
            settings_tab(group, user, is_org)


def plots_tab(group: dict, user: dict, views: list[cm.PlotView], is_admin: bool) -> None:
    my_plots = [v for v in views if v.garden["owner_id"] == user["id"] and v.claimed_by == user["username"]]
    if not my_plots:
        c1, c2 = st.columns([3, 1])
        c1.info("You don't have a plot here yet. Claim one below, or plan your own.")
        if c2.button("🌱 Plan my own plot", type="primary"):
            s = group["settings"]
            st.session_state.prefill = {
                "location_id": s["location_id"], "place": s.get("place", ""), "skill_level": "beginner",
                "has_cats": False, "has_dogs": False, "from_name": group["name"],
                "budget": (0, s.get("plot_budget") or 1500), "audience": "me",
                "group_id": group["id"], "group_name": group["name"]}
            st.session_state.rec = None
            st.switch_page(st.session_state.pages["plan"])
    if not views:
        st.caption("No plots yet. The organizer can import plots from a CSV, or members can plan their own.")
        return
    cols = st.columns(3)
    for i, v in enumerate(views):
        g = v.garden
        with cols[i % 3].container(border=True, key=ui.card_key()):
            st.markdown(f"**{html.escape(g['name'])}**")
            who = (f'<span class="badge done">👤 {html.escape(v.claimed_by)}</span>' if v.claimed_by
                   else '<span class="badge warn">unclaimed</span>')
            st.markdown(who, unsafe_allow_html=True)
            st.caption(", ".join(p.name for p in v.plan.plants) or "—")
            done = store.get_checks(g["id"])
            n_done = sum(task_key(x) in done for x in v.plan.tasks)
            st.progress(n_done / max(1, len(v.plan.tasks)), text=f"{n_done}/{len(v.plan.tasks)} tasks")
            b1, b2 = st.columns(2)
            if g["owner_id"] == user["id"] and b1.button("Open", key=f"openplot_{g['id']}"):
                st.session_state.open_garden = g["id"]
                st.switch_page(st.session_state.pages["gardens"])
            if not v.claimed_by and b2.button("Claim", key=f"claim_{g['id']}",
                                              help="Make this your plot: it shows up in My gardens and This week."):
                if store.claim_plot(g["id"], group["id"], user["id"], user["username"]):
                    st.session_state.group_flash = f"{g['name']} is yours. Find it in My gardens."
                    st.rerun()
            if is_admin:
                with st.popover("🗑️ Remove plot", width="stretch"):
                    sure = st.checkbox("Delete this plot and its plan", key=f"rmplot_sure_{g['id']}")
                    if st.button("Delete plot", key=f"rmplot_{g['id']}", disabled=not sure):
                        store.delete_plot(group["id"], user["id"], g["id"])
                        st.session_state.group_flash = f"Removed {g['name']}."
                        st.rerun()


def _task_row(group: dict, user: dict, key: str, label: str, state: dict, help: str = "") -> None:
    st_ = state.get(key, {})
    c1, c2, c3 = st.columns([6, 2, 1], vertical_alignment="center")
    c1.markdown(ui.md(label), help=help or None)
    claimer = st_.get("username")
    if claimer:
        mine = st_.get("claimed_by") == user["id"]
        c2.markdown(f'<span class="badge done">🙋 {html.escape(claimer)}</span>', unsafe_allow_html=True)
        if mine and c2.button("Unclaim", key=f"unclaim_{key}", type="tertiary"):
            store.set_group_task(group["id"], user["id"], key, claim=False)
            st.rerun()
    elif c2.button("I'll do it", key=f"claimbtn_{key}"):
        store.set_group_task(group["id"], user["id"], key, claim=True)
        st.rerun()
    done = c3.checkbox("Done", value=bool(st_.get("done_at")), key=f"gdone_{key}", label_visibility="collapsed")
    if done != bool(st_.get("done_at")):
        store.set_group_task(group["id"], user["id"], key, done=done)
        st.rerun()


def shared_tasks(group: dict, views: list[cm.PlotView]) -> list[tuple[date, str, str, str]]:
    """(date, key, label, help) for everything the whole garden does together."""
    s = group["settings"]
    start = date.fromisoformat(s["start_date"])
    out = []
    for b in cm.shared_build_plans(group):
        out.append((start, f"shared|build|{b.build_id}", f"🔨 Build the shared {b.name.lower()} "
                    f"({ui.est(b.total_usd)})", b.why))
    later = [sch.plant_out for v in views for sch in v.plan.schedules if sch.plant_out > start]
    if later:
        first = min(later)
        out.append((max(date.today(), first - timedelta(weeks=6)), "shared|seed-order",
                    "🛒 Place the combined seed & plant order", "Pooled packets are cheaper; see Shopping & cost split."))
        out.append((max(date.today(), first - timedelta(weeks=1)), "shared|seed-handout",
                    "📦 Hand out seeds and transplants to plot holders", ""))
    for d in cm.work_days(group):
        out.append((d, f"workday|{d.isoformat()}", f"🧑‍🌾 Community work day — {d:%a %b %d}",
                    "Weed paths, turn the compost, water shared beds. Claim it to lead."))
    return sorted(out)


def tasks_tab(group: dict, user: dict, views: list[cm.PlotView]) -> None:
    st.caption("Claim a task so everyone knows who's on it. Work days are the first Saturday of each "
               "month in the growing season.")
    state = store.group_task_state(group["id"])
    for d, key, label, help in shared_tasks(group, views):
        _task_row(group, user, key, f"**{d:%b %d}** · {label}", state, help)


def costs_tab(group: dict, views: list[cm.PlotView]) -> None:
    if not views:
        st.caption("Add plots to see the combined shopping list and cost split.")
        return
    r = cm.rollup(group, views)
    m1, m2, m3 = st.columns(3)
    m1.metric("Whole garden (pooled)", ui.est(r.pooled_total), help=config.SHOP_PRICE_NOTE)
    m2.metric("If everyone bought alone", ui.est(r.separate_total))
    m3.metric("Saved by pooling", ui.est(r.separate_total - r.pooled_total),
              help="Shared builds bought once instead of per plot, and one seed packet per "
                   f"{cm.PLOTS_PER_SEED_PACKET} plots.")
    st.markdown("#### 🌱 Combined seed & plant order")
    st.table(pd.DataFrame([{
        "Item": d["item"], "Plots": d["plots"], "Buy": d["pooled_qty"],
        "Each": ui.est(d["unit_price"]), "Cost": ui.est(d["pooled_cost"])} for d in r.combined]
        ).set_index("Item"))
    if r.shared_builds:
        st.markdown("#### 🔨 Shared builds (bought once)")
        for b in r.shared_builds:
            st.markdown(ui.md(f"**{b.name}** — {ui.est(b.total_usd)}"))
    st.markdown("#### 💵 Cost per plot")
    df = pd.DataFrame([{"Plot": p["name"], "Own beds/pots": p["own_builds"], "Plants & seeds": p["plants"],
                        "Share of shared builds": p["shared_share"], "Total": p["total"]} for p in r.per_plot])
    st.table(df.set_index("Plot").map(ui.est))
    st.caption(config.SHOP_PRICE_NOTE)
    from .. import exports
    d1, d2 = st.columns(2)
    d1.download_button("📄 Grant-ready budget (Excel)", exports.community_budget(group, r),
                       file_name="community-garden-budget.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       help="Summary, pooled order, shared builds and cost per plot, for grant applications.")
    d2.download_button("⬇️ Cost split (CSV)", df.to_csv(index=False).encode(),
                       file_name="cost_split.csv", mime="text/csv", width="stretch")


ROLE_HELP = ("**Organizer:** everything, including deleting the garden and choosing admins. "
             "**Admins:** garden settings, CSV imports, removing plots and members. "
             "**Members:** claim a plot, plan their own, and claim shared tasks.")


def members_tab(group: dict, user: dict, members: list[dict]) -> None:
    me = group["role"]
    st.caption(ROLE_HELP)
    for m in members:
        c1, c2, c3 = st.columns([4, 2, 1], vertical_alignment="center")
        badge = {"organizer": "👑 organizer", "admin": "🛡️ admin", "member": "member"}[m["role"]]
        c1.markdown(f"👤 **{html.escape(m['username'])}** · {badge}")
        if me == "organizer" and m["role"] != "organizer":
            new_role = c2.selectbox("Role", ["member", "admin"], index=["member", "admin"].index(m["role"]),
                                    key=f"role_{m['id']}", label_visibility="collapsed")
            if new_role != m["role"]:
                store.set_role(group["id"], user["id"], m["id"], new_role)
                st.session_state.group_flash = f"{m['username']} is now {'an admin' if new_role == 'admin' else 'a member'}."
                st.rerun()
        if store.ROLE_RANK[me] >= 2 and store.ROLE_RANK[me] > store.ROLE_RANK[m["role"]]:
            if c3.button("Remove", key=f"rm_{m['id']}"):
                store.remove_member(group["id"], user["id"], m["id"])
                st.rerun()
    if me in ("organizer", "admin"):
        st.caption(f"Members join from the Community page with code **{group['join_code']}**.")


def settings_tab(group: dict, user: dict, is_org: bool) -> None:
    s = dict(group["settings"])
    with st.form(f"grp_settings_{group['id']}"):
        name = st.text_input("Garden name", value=group["name"], max_chars=60)
        place_raw = st.text_input("Place nickname", value=s.get("place", ""), max_chars=40)
        c1, c2 = st.columns(2)
        start = c1.date_input("Season starts", date.fromisoformat(s["start_date"]))
        space = c2.selectbox("Plots are", ["raised_bed", "in_ground"],
                             index=["raised_bed", "in_ground"].index(s.get("space_type", "raised_bed")),
                             format_func={"raised_bed": "Raised beds", "in_ground": "In-ground plots"}.get)
        c3, c4, c5 = st.columns(3)
        w = c3.number_input("Plot width (ft)", 2.0, 30.0, float(s.get("plot_w", 4)), 0.5)
        l = c4.number_input("Plot length (ft)", 2.0, 50.0, float(s.get("plot_l", 8)), 0.5)
        pb = c5.number_input("Max $ per plot", 0, 2000, int(s.get("plot_budget") or 0), 25)
        beds_ready = st.checkbox("Plots already have beds and soil", value=s.get("beds_ready", True))
        shared = st.multiselect("Shared builds", SHAREABLE, default=s.get("shared_builds", []),
                                format_func=lambda b: next(x["name"] for x in builds()["builds"] if x["id"] == b))
        st.caption("Changes apply to new plot plans and to the shared calendar and cost split.")
        if st.form_submit_button("Save settings", type="primary"):
            place, err = clean_place(place_raw)
            if err:
                st.error(err)
            else:
                s.update({"place": place, "start_date": start.isoformat(), "space_type": space,
                          "plot_w": w, "plot_l": l, "plot_budget": int(pb) or None,
                          "beds_ready": beds_ready, "shared_builds": shared})
                try:
                    store.update_group_settings(group["id"], user["id"], s, name=name)
                    st.session_state.group_flash = "Settings saved."
                    st.rerun()
                except PermissionError as e:
                    st.error(str(e))
    if is_org:
        with st.expander("⚠️ Delete this community garden"):
            sure = st.checkbox("I understand this deletes every plot in it", key="del_group_sure")
            if st.button("Delete permanently", disabled=not sure):
                store.delete_group(group["id"], user["id"])
                st.session_state.open_group = None
                st.session_state.group_flash = f"Deleted “{group['name']}”."
                st.rerun()
    else:
        st.caption("Only the organizer can delete the garden.")


def import_tab(group: dict, user: dict) -> None:
    s = group["settings"]
    st.markdown("Upload your member sign-up sheet. Each row becomes a plot with its own plan, checked "
                "by the verifier against your frost dates.")
    st.caption("Columns: " + ", ".join(cm.CSV_COLUMNS) + ". Only **plot** is required. Use first names "
               "or plot numbers only. No phone numbers, emails or addresses.")
    st.download_button("⬇️ Download template CSV", cm.TEMPLATE_CSV.encode(), file_name="plots_template.csv",
                       mime="text/csv")
    up = st.file_uploader("Sign-up CSV", type=["csv"], key=f"csv_{group['id']}")
    if not up:
        return
    rows, errors = cm.parse_member_csv(up.getvalue(), s.get("plot_w", 4), s.get("plot_l", 8))
    for e in errors:
        st.error(e)
    if not rows:
        return
    st.dataframe(pd.DataFrame([{
        "plot": r.plot, "gardener": r.gardener, "skill": r.skill, "goals": ", ".join(r.goals),
        "sun": r.sun, "size": f"{r.width_ft:g}×{r.length_ft:g}", "notes": r.notes[:40],
        "fixes": "; ".join(r.warnings)} for r in rows]), hide_index=True, width="stretch")
    est = cm.estimate_cost(rows)
    st.info(ui.md(f"**{len(rows)} plots** · estimated AI cost **~${est:.3f}** "
                  f"(hard cap: {len(rows) * 5 + 2} AI calls for this batch)."))
    if st.button(f"🌱 Generate {len(rows)} plot plans", type="primary"):
        bar = st.progress(0.0, text="Starting…")

        def progress(n, total, row):
            bar.progress((n - 1) / total, text=f"Planning plot {row.plot} ({n} of {total})…")

        results, batch = cm.plan_rows(group, user["id"], rows, progress)
        bar.progress(1.0, text="Done")
        ok = sum(r["ok"] for r in results)
        st.success(f"Planned {ok} of {len(rows)} plots · {len(batch.calls)} AI calls · "
                   f"{batch.tokens_used:,} tokens · ${batch.cost_usd:.4f}")
        st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
