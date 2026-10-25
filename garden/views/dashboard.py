"""Page: My dashboard — what you've grown across all your gardens."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from .. import config, store, ui
from ..data import plants
from ..pipeline import task_key
from .gardens import load_plan, need_login

GREEN = "#2F6B3F"         # app primary; single-series charts need no legend
INK_MUTED = "#5C6B5F"
GRID = "#E3EDE0"


def _bar(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str, horizontal: bool,
         tooltip: list, fmt: str = ",.1f") -> alt.Chart:
    axis_q = alt.Axis(format=fmt, gridColor=GRID, labelColor=INK_MUTED, titleColor=INK_MUTED)
    if horizontal:
        enc = dict(y=alt.Y(f"{y}:N", sort="-x", title=None, axis=alt.Axis(labelColor="#1E2A22", labelLimit=260)),
                   x=alt.X(f"{x}:Q", title=x_title, axis=axis_q))
    else:
        enc = dict(x=alt.X(f"{x}:O", title=None, sort=None, axis=alt.Axis(labelAngle=0, labelColor="#1E2A22")),
                   y=alt.Y(f"{y}:Q", title=y_title, axis=axis_q))
    return (alt.Chart(df).mark_bar(color=GREEN, cornerRadiusEnd=4)
            .encode(**enc, tooltip=tooltip)
            .properties(height=max(160, 34 * len(df)) if horizontal else 260)
            .configure_view(strokeWidth=0))


def page() -> None:
    if need_login("My dashboard"):
        return
    user = st.session_state.user
    today = date.today()
    ui.hero("📊 My dashboard", "What you've planned, planted and picked, across all your gardens.")
    ui.page_tip("dashboard", "Totals come from tasks you tick and harvests you log. Use the filters to focus on "
                             "current or past gardens, a date range, a place or a crop.")

    all_gardens = store.list_gardens(user["id"])
    groups = store.my_groups(user["id"])
    if not all_gardens and not groups:
        st.info("Save a garden plan first; your dashboard fills in as you tick off tasks and log harvests.")
        return

    f = filter_bar(all_gardens, groups, today)
    gardens = [g for g in all_gardens
               if store.garden_status(g) in f.statuses
               and (not f.places or (store.place_of(g) or "(no place)") in f.places)]
    if all_gardens:
        st.markdown("## 🌿 My gardens")
        if gardens:
            personal_section(user, gardens, today, f)
        else:
            st.caption("No gardens match these filters.")
    if f.community:
        for grp in groups:
            community_section(grp, user, today, f)


@dataclass
class Filters:
    statuses: set[str]
    start: date | None          # harvest date range (inclusive); None = open-ended
    end: date | None
    places: set[str]            # empty = all
    crops: set[str]             # plant ids; empty = all
    donated_only: bool
    community: bool

    def harvest_ok(self, h: dict) -> bool:
        d = date.fromisoformat(h["picked_on"])
        return ((self.start is None or d >= self.start) and (self.end is None or d <= self.end)
                and (not self.crops or h["plant_id"] in self.crops)
                and (not self.donated_only or bool(h["donated"])))

    def in_range(self, d: date) -> bool:
        return (self.start is None or d >= self.start) and (self.end is None or d <= self.end)


DATE_PRESETS = ["All time", "This year", "Last year", "Last 12 months", "Custom range"]
STATUS_LABELS = {"current": "🌱 Current", "future": "🗓️ Future", "past": "📚 Past"}


def filter_bar(gardens: list[dict], groups: list[dict], today: date) -> Filters:
    """Filters live in one row above the charts; everything defaults to 'show all'."""
    n = st.session_state.setdefault("dash_gen", 0)   # bumping this gives every filter a fresh widget
    with st.container(border=True, key=ui.card_key()):
        c1, c2, c3, c4 = st.columns([2.2, 1.6, 2, 0.9], vertical_alignment="bottom")
        statuses = c1.pills("Gardens", list(STATUS_LABELS), format_func=STATUS_LABELS.get,
                            selection_mode="multi", default=list(STATUS_LABELS), key=f"dash_status_{n}")
        preset = c2.selectbox("Harvest dates", DATE_PRESETS, key=f"dash_dates_{n}")
        start = end = None
        if preset == "This year":
            start, end = date(today.year, 1, 1), date(today.year, 12, 31)
        elif preset == "Last year":
            start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        elif preset == "Last 12 months":
            start, end = today - timedelta(days=365), today
        elif preset == "Custom range":
            rng = c3.date_input("From – to", value=(today - timedelta(days=365), today), key=f"dash_custom_{n}")
            if isinstance(rng, (tuple, list)) and len(rng) == 2:
                start, end = rng
            elif isinstance(rng, (tuple, list)) and len(rng) == 1:
                start = rng[0]
        if c4.button("Reset", help="Clear all filters", width="stretch"):
            st.session_state.dash_gen = n + 1
            st.rerun()

        places = sorted({store.place_of(g) or "(no place)" for g in gardens})
        crop_ids = sorted({pid for g in gardens for pid in g["chosen"]}, key=lambda i: plants()[i].name)
        with st.expander("More filters"):
            m1, m2 = st.columns(2)
            sel_places = m1.multiselect("Place", places, key=f"dash_places_{n}",
                                        placeholder="All places") if len(places) > 1 else []
            sel_crops = m2.multiselect("Crops", crop_ids, format_func=lambda i: plants()[i].name,
                                       key=f"dash_crops_{n}", placeholder="All crops")
            m3, m4 = st.columns(2)
            donated_only = m3.toggle("Donated harvests only", key=f"dash_donated_{n}")
            community = m4.toggle("Show community gardens", value=True, key=f"dash_community_{n}",
                                  disabled=not groups) if groups else False
    f = Filters(statuses=set(statuses or []), start=start, end=end, places=set(sel_places),
                crops=set(sel_crops), donated_only=donated_only, community=bool(community))
    active = []
    if f.statuses != set(STATUS_LABELS):
        active.append("gardens: " + (", ".join(sorted(f.statuses)) or "none"))
    if start or end:
        active.append(f"harvests {start:%b %d, %Y} – {end:%b %d, %Y}" if start and end else "custom dates")
    if f.places:
        active.append("place: " + ", ".join(sorted(f.places)))
    if f.crops:
        active.append(f"{len(f.crops)} crop(s)")
    if donated_only:
        active.append("donated only")
    if active:
        st.caption("Filtered by " + " · ".join(active) + ". Date and crop filters apply to harvests.")
    return f


def community_section(grp: dict, user: dict, today: date, f: Filters) -> None:
    from .. import community as cm

    stats = cm.group_stats(grp, user["id"], today, harvest_filter=f.harvest_ok, in_range=f.in_range)
    is_admin = stats.per_plot is not None
    st.markdown(f"## 🏘️ {grp['name']}")
    st.caption("Garden-wide totals for everyone's plots." +
               (" As an admin you also see each plot." if is_admin else
                " Individual plots are visible to the garden's admins only."))
    t = st.columns(4)
    t[0].metric("Harvested (approx.)", f"{stats.total_lb:,.1f} lb", help=f"{stats.harvests} harvests logged")
    t[1].metric("Donated", f"{stats.donated_lb:,.1f} lb")
    t[2].metric("Plots that reached harvest", f"{stats.plots_reached}/{stats.plots_due}" if stats.plots_due else "—",
                help="Of plots with a crop whose harvest window has started.")
    t[3].metric("Work days done", f"{stats.workdays_done}/{stats.workdays_past}" if stats.workdays_past else "—")
    if stats.by_month:
        bm = pd.DataFrame(stats.by_month)
        bm["Month"] = pd.to_datetime(bm["Month"]).dt.strftime("%b %Y")
        st.markdown("#### Garden harvest by month")
        st.altair_chart(_bar(bm, "Month", "lb", "", "Approx. pounds", False,
                             [alt.Tooltip("Month:O"), alt.Tooltip("lb:Q", title="Approx. lb", format=",.2f")]),
                        width="stretch")
    else:
        st.caption("No harvests logged in this garden yet.")
    if is_admin and stats.per_plot:
        with st.expander("🔒 Per-plot detail (admins only)"):
            st.table(pd.DataFrame(stats.per_plot).set_index("Plot"))


def personal_section(user: dict, gardens: list[dict], today: date, f: Filters) -> None:
    status_counts = defaultdict(int)
    crop_rows, garden_rows, harvest_rows = [], [], []
    tasks_done = tasks_total = 0
    due_crops = reached = 0
    for g in gardens:
        status = store.garden_status(g)
        status_counts[status] += 1
        rec, plan = load_plan(g, user["id"])
        done = store.get_checks(g["id"])
        all_logs = store.list_harvests(g["id"])
        logs = [h for h in all_logs if f.harvest_ok(h)]
        n_done = sum(task_key(t) in done for t in plan.tasks)
        tasks_done += n_done
        tasks_total += len(plan.tasks)
        garden_rows.append({"Garden": g["name"], "Status": status,
                            "Tasks done (%)": round(100 * n_done / max(1, len(plan.tasks)))})
        logged = defaultdict(float)
        for h in logs:
            p = plants().get(h["plant_id"])
            logged[h["plant_id"]] += h["est_lb"]
            harvest_rows.append({"Crop": p.name if p else h["plant_id"], "lb": h["est_lb"],
                                 "Value": h["est_lb"] * ((p.retail_price_per_lb or 0) if p else 0),
                                 "Month": date.fromisoformat(h["picked_on"]).strftime("%Y-%m"),
                                 "Donated": bool(h["donated"]), "Garden": g["name"]})
        for s in plan.schedules:
            p = plants()[s.plant_id]
            if f.crops and p.id not in f.crops:
                continue
            harvest_task_done = any(t.kind == "harvest" and t.plant_id == p.id and task_key(t) in done
                                    for t in plan.tasks)
            got_harvest = harvest_task_done or any(h["plant_id"] == p.id for h in all_logs)
            if s.harvest_start <= today and f.in_range(s.harvest_start):
                due_crops += 1
                reached += got_harvest
            state = ("🧺 harvested" if got_harvest else
                     "🌱 growing" if s.plant_out <= today and status != "past" else
                     "🗓️ planned" if status != "past" else "— no harvest logged")
            crop_rows.append({"Crop": p.name, "Garden": g["name"], "Season": s.season_label, "Status": state,
                              "Logged lb": round(logged.get(p.id, 0), 2)})

    hv = pd.DataFrame(harvest_rows)
    total_lb = float(hv["lb"].sum()) if not hv.empty else 0.0
    value = float(hv["Value"].sum()) if not hv.empty else 0.0
    donated = float(hv.loc[hv["Donated"], "lb"].sum()) if not hv.empty else 0.0

    # Headline tiles: single numbers are better as numbers than as charts.
    t = st.columns(4)
    t[0].metric("Gardens", len({g["plot_id"] for g in gardens}),
                help=f"{len(gardens)} seasons: {status_counts['current']} current · {status_counts['future']} "
                     f"future · {status_counts['past']} past")
    t[1].metric("Different crops", len({r["Crop"] for r in crop_rows}))
    t[2].metric("Harvested (approx.)", f"{total_lb:,.1f} lb",
                help="From one-tap harvest logs (handful ≈ ¼ lb, bowl ≈ 1 lb, basket ≈ 5 lb; herbs less).")
    t[3].metric("Reached harvest", f"{reached}/{due_crops}" if due_crops else "—",
                help="Of crops whose harvest window has started: how many you ticked as harvested or logged. "
                     "This is the number that shows whether a first season worked.")
    st.caption(ui.md(f"✅ {tasks_done} of {tasks_total} tasks done across all gardens"
                     + (f" · 🎁 {donated:,.1f} lb donated" if donated else "")
                     + (f" · 🛒 worth roughly ${round(value):,} at grocery prices" if value else "")))
    if value:
        st.caption(config.GROCERY_PRICE_NOTE)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Harvest by crop")
        if hv.empty:
            st.caption("No harvests match these filters yet. Tap a size on **This week** when something's ready.")
        else:
            by_crop = hv.groupby("Crop", as_index=False)["lb"].sum().round(2)
            st.altair_chart(_bar(by_crop, "lb", "Crop", "Approx. pounds", "", True,
                                 [alt.Tooltip("Crop:N"), alt.Tooltip("lb:Q", title="Approx. lb", format=",.2f")]),
                            width="stretch")
    with c2:
        st.markdown("#### Harvest by month")
        if not hv.empty:
            by_month = hv.groupby("Month", as_index=False)["lb"].sum().round(2).sort_values("Month")
            by_month["Month"] = pd.to_datetime(by_month["Month"]).dt.strftime("%b %Y")
            st.altair_chart(_bar(by_month, "Month", "lb", "", "Approx. pounds", False,
                                 [alt.Tooltip("Month:O"), alt.Tooltip("lb:Q", title="Approx. lb", format=",.2f")]),
                            width="stretch")
        else:
            st.caption("Your monthly harvest shows up here once you start logging.")

    st.markdown("#### Progress by garden")
    gd = pd.DataFrame(garden_rows)
    st.altair_chart(_bar(gd, "Tasks done (%)", "Garden", "Tasks done (%)", "", True,
                         [alt.Tooltip("Garden:N"), alt.Tooltip("Status:N"),
                          alt.Tooltip("Tasks done (%):Q", format=".0f")], fmt=".0f"),
                    width="stretch")

    with st.expander("🌿 Everything you've grown or planned (table view)"):
        st.dataframe(pd.DataFrame(crop_rows), hide_index=True, width="stretch")
    if not hv.empty:
        with st.expander("🧺 Harvest data (table view)"):
            st.dataframe(hv.assign(Value=hv["Value"].round(2)), hide_index=True, width="stretch")
