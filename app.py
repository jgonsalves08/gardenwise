"""Northeast Garden Planner — Streamlit entry point.

Run:  streamlit run app.py

Pages: Plan a garden (guests welcome) · My gardens and This week (optional login).
"""

from __future__ import annotations

import uuid

import streamlit as st

from garden import llm, seed, ui
from garden.views import account, community, dashboard, gardens, planner, week

st.set_page_config(page_title="Northeast Garden Planner", page_icon="🌱", layout="wide")
ui.inject_css()


@st.cache_resource
def _seed_once() -> bool:
    seed.ensure_demo()
    return True


_seed_once()

if "budget" not in st.session_state:
    st.session_state.budget = llm.Budget(session_id=uuid.uuid4().hex[:8])

pages = {
    "plan": st.Page(planner.page, title="Plan a garden", icon="🌱", default=True),
    "week": st.Page(week.page, title="This week", icon="📋", url_path="week"),
    "gardens": st.Page(gardens.page, title="My gardens", icon="🌿", url_path="gardens"),
    "community": st.Page(community.page, title="Community gardens", icon="🏘️", url_path="community"),
    "dashboard": st.Page(dashboard.page, title="My dashboard", icon="📊", url_path="dashboard"),
}
st.session_state.pages = pages

# Custom sidebar order: main pages, then account, AI usage, and the dashboard button under it.
nav = st.navigation(list(pages.values()), position="hidden")
with st.sidebar:
    for key in ("plan", "week", "gardens", "community"):
        st.page_link(pages[key])
    st.divider()
account.sidebar()
ui.usage_panel(st.session_state.budget)
st.sidebar.page_link(pages["dashboard"], label="My dashboard", icon="📊")
nav.run()
