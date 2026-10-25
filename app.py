"""Gardenwise — Streamlit entry point.

Run:  streamlit run app.py

Pages: Plan a garden (guests welcome) · My gardens and This week (optional login).
"""

from __future__ import annotations

import uuid

import streamlit as st

from garden import config, llm, seed, ui
from garden.views import about, account, community, dashboard, gardens, helper_ui, home, planner, week

st.set_page_config(page_title=config.APP_NAME, page_icon="🌱", layout="wide")
ui.inject_css()
ui.reset_cards()


@st.cache_resource
def _seed_once() -> bool:
    seed.ensure_demo()
    return True


_seed_once()

if "budget" not in st.session_state:
    st.session_state.budget = llm.Budget(session_id=uuid.uuid4().hex[:8])

pages = {
    "home": st.Page(home.page, title="Home", icon="🏠", default=True),
    "plan": st.Page(planner.page, title="Plan a garden", icon="🌱", url_path="plan"),
    "week": st.Page(week.page, title="This week", icon="📋", url_path="week"),
    "gardens": st.Page(gardens.page, title="My gardens", icon="🌿", url_path="gardens"),
    "community": st.Page(community.page, title="Community gardens", icon="🏘️", url_path="community"),
    "dashboard": st.Page(dashboard.page, title="My dashboard", icon="📊", url_path="dashboard"),
    "about": st.Page(about.page, title="About & credits", icon="ℹ️", url_path="about"),
}
st.session_state.pages = pages
SECTION_STATE = {"gardens": ("open_garden",), "community": ("open_group",)}

# Custom sidebar order: main pages, then account, AI usage, and the dashboard button under it.
nav = st.navigation(list(pages.values()), position="hidden")
with st.sidebar:
    with st.container(key="brand_link"):   # clicking the name goes Home
        st.page_link(pages["home"], label=config.APP_NAME, icon="🌱")
    st.markdown(f'<div class="brand-sub">{config.APP_TAGLINE}</div>', unsafe_allow_html=True)
    st.markdown('<div class="nav-label">Menu</div>', unsafe_allow_html=True)
    # Buttons instead of plain links, so clicking a section you're already in (e.g. while inside one
    # community garden) takes you back to that section's main page.
    for key in ("home", "plan", "week", "gardens", "community"):
        pg = pages[key]
        active = nav.url_path == pg.url_path
        with st.container(key=f"navbtn_{key}{'_on' if active else ''}"):
            if st.button(f"{pg.icon}  {pg.title}", key=f"nav_{key}", type="tertiary", width="stretch"):
                for k in SECTION_STATE.get(key, ()):
                    st.session_state.pop(k, None)
                st.switch_page(pg)
    st.divider()
account.topbar()
ui.usage_panel(st.session_state.budget)
st.sidebar.page_link(pages["dashboard"], label="My dashboard", icon="📊")
st.sidebar.page_link(pages["about"], label="About & credits", icon="ℹ️")
if st.sidebar.button("❓ How Gardenwise works", type="tertiary"):
    st.session_state.show_guide = True
    st.session_state.hidden_tips = set()
    st.switch_page(pages["home"])
helper_ui.render()
nav.run()
