"""Page: Home — what Gardenwise is, how it works, and where to start."""

from __future__ import annotations

import html

import streamlit as st

from .. import config, store, ui
from ..pipeline import task_key

AUDIENCES = [
    ("🧑", "Just me", "A first garden that fits your space, skill and budget.", "me"),
    ("👨‍👩‍👧", "My household", "Plant counts sized to how much your family will actually eat.", "household"),
    ("🏫", "A school", "Harvests while students are there, summer care, classroom tie-ins.", "school"),
    ("🏘️", "A community garden", "Plan every plot at once, share the work and split the costs.", "community"),
]
WHY = [
    ("📅", "Timed to your frost dates", "Every planting and harvest date is calculated from your area's "
                                         "frost data, and every AI pick is double-checked by code."),
    ("💵", "Fits your budget", "A costed shopping list (soil, lumber, pots, seeds) with store links and "
                               "cheaper options when you're over."),
    ("📋", "Helps all season", "Save your garden to get a weekly to-do list, tick things off, and log "
                               "harvests in one tap."),
    ("🛡️", "Safe and private", "Pet-toxicity and lead-in-soil warnings, no addresses stored, and photos "
                               "stripped of location data and never saved."),
]


def _go_plan(audience: str | None = None) -> None:
    if audience:
        st.session_state.prefill = {"audience": audience, "from_home": True}
        st.session_state["audience"] = audience
        st.session_state.rec = None
    st.switch_page(st.session_state.pages["plan"])


def page() -> None:
    st.markdown(
        f'<div class="hero home-hero"><h1>🌱 Welcome to {config.APP_NAME}</h1>'
        "<p>Not sure what to grow or where to start? Tell us about your space, skill and goals, and get a "
        "garden plan made for your yard, your budget and your local frost dates. Then keep it on track "
        "all season.</p></div>", unsafe_allow_html=True)

    user = st.session_state.get("user")
    if user:
        welcome_back(user)

    c1, c2, c3 = st.columns([1.2, 1.2, 2])
    if c1.button("🌱 Plan my garden", type="primary", width="stretch"):
        _go_plan()
    if c2.button("💬 Ask the garden helper", width="stretch"):
        from .helper_ui import open_helper
        open_helper()
    c3.caption("Takes about a minute. No account needed to plan; sign up (top right) only if you want "
               "to save and track your garden.")

    st.markdown("### How it works")
    steps = "".join(f'<div class="guide-step"><div class="guide-num">{n}</div><div><b>{html.escape(t)}</b>'
                    f'<div class="muted">{html.escape(d)}</div></div></div>' for n, t, d in ui.GUIDE_STEPS)
    st.markdown(f'<div class="guide-grid">{steps}</div>', unsafe_allow_html=True)

    st.markdown("### Who it's for")
    cols = st.columns(4)
    for col, (icon, title, desc, key) in zip(cols, AUDIENCES):
        with col.container(border=True, key=ui.card_key()):
            st.markdown(f'<div class="aud-icon">{icon}</div><b>{title}</b>'
                        f'<div class="muted aud-desc">{desc}</div>', unsafe_allow_html=True)
            if key == "community":
                if st.button("Set up or join", key=f"home_{key}", width="stretch"):
                    st.switch_page(st.session_state.pages["community"])
            elif st.button("Start planning", key=f"home_{key}", width="stretch"):
                _go_plan(key)

    st.markdown(f"### Why {config.APP_NAME}")
    why = "".join(f'<div class="why-card"><div class="aud-icon">{i}</div><b>{html.escape(t)}</b>'
                  f'<div class="muted">{html.escape(d)}</div></div>' for i, t, d in WHY)
    st.markdown(f'<div class="guide-grid">{why}</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="region-note">📍 {config.REGION_NOTE}</div>', unsafe_allow_html=True)
    st.caption("Just looking around? Log in at the top right as **demo** (password **garden-demo-2026**) to see "
               "gardens already in progress, including a community garden.")


def welcome_back(user: dict) -> None:
    from datetime import date, timedelta

    from .gardens import load_plan

    today = date.today()
    gardens = [g for g in store.list_gardens(user["id"]) if store.garden_status(g) != "past"]
    due = 0
    for g in gardens:
        _rec, plan = load_plan(g, user["id"])
        done = store.get_checks(g["id"])
        due += sum(1 for t in plan.tasks if task_key(t) not in done and t.when <= today + timedelta(days=14))
    with st.container(border=True, key=ui.card_key()):
        a, b, c = st.columns([2.4, 1, 1], vertical_alignment="center")
        a.markdown(f"**Welcome back, {html.escape(user['username'])}!** You have **{len(gardens)}** active "
                   f"garden(s) and **{due}** task(s) due in the next two weeks.")
        if b.button("📋 This week", width="stretch"):
            st.switch_page(st.session_state.pages["week"])
        if c.button("🌿 My gardens", width="stretch"):
            st.switch_page(st.session_state.pages["gardens"])
