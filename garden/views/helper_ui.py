"""Floating "💬 Garden helper" button on every page, opening a chat panel."""

from __future__ import annotations

import streamlit as st

from .. import llm, store
from ..agents.helper import PAGES, run_helper
from ..data import plants
from ..safety import screen_text

FAB_CSS = """
<style>
.st-key-helper_fab {position: fixed; bottom: 26px; right: 30px; z-index: 999; width: auto !important;}
.st-key-helper_fab button {border-radius: 999px !important; padding: .65rem 1.2rem !important;
    box-shadow: 0 8px 22px rgba(31,95,173,.35); font-weight: 700;}
</style>
"""
STARTERS = ["Help me plan a garden", "What's due in my gardens this week?", "When is the last frost in Boston?",
            "Which herbs grow in shade?"]


def render() -> None:
    """Call once per run, from app.py, before the page renders."""
    nav = st.session_state.pop("helper_nav", None)
    if nav in PAGES:
        st.switch_page(st.session_state.pages[nav])
    st.markdown(FAB_CSS, unsafe_allow_html=True)
    with st.container(key="helper_fab"):
        if st.button("💬 Garden helper", type="primary"):
            helper_dialog()


def _say(role: str, text: str) -> None:
    st.session_state.setdefault("helper_history", []).append({"role": role, "text": text})


def _ask(text: str) -> None:
    screen = screen_text(text)
    _say("user", screen.text)
    if screen.refused:
        _say("assistant", screen.refusal)
        return
    history = st.session_state.helper_history[:-1]
    try:
        with st.spinner("Thinking…"):
            out = run_helper(history, screen.text, st.session_state.get("user"), st.session_state.budget)
    except llm.BudgetExceeded as e:
        _say("assistant", f"🛑 {e} This limit protects against runaway costs.")
        return
    except llm.ContentFiltered:
        _say("assistant", "🛡️ That message was blocked by the AI provider's safety filter. Try rephrasing?")
        return
    except llm.LLMError:
        _say("assistant", "Sorry, I couldn't reach the AI just now. Please try again in a moment.")
        return
    _say("assistant", out["reply"])
    st.session_state.helper_actions = out["actions"]


def _confirm(a: dict) -> None:
    user = st.session_state.get("user")
    if not user:
        return
    if a["kind"] == "task":
        store.set_check(a["garden_id"], user["id"], a["key"], True)   # ownership checked in store
    elif a["kind"] == "harvest":
        p = plants()[a["plant_id"]]
        store.log_harvest(a["garden_id"], user["id"], p.id, a["size"],
                          store.size_to_lb(a["size"], p.category, p.edible))
    _say("assistant", f"✅ Done: {a['label']}.")


@st.dialog("💬 Garden helper", width="large")
def helper_dialog() -> None:
    hist = st.session_state.setdefault("helper_history", [])
    if not hist:
        with st.chat_message("assistant", avatar="🌱"):
            st.write("Hi! I can answer gardening questions, look up your frost dates, fill in the planning "
                     "form for you, or check what's due in your gardens. What would you like to do?")
        cols = st.columns(2)
        for i, q in enumerate(STARTERS):
            if cols[i % 2].button(q, key=f"starter_{i}", width="stretch"):
                _ask(q)
                st.rerun(scope="fragment")
    for m in hist:
        with st.chat_message(m["role"], avatar="🧑‍🌾" if m["role"] == "user" else "🌱"):
            st.markdown(m["text"].replace("$", "\\$"))

    actions = st.session_state.get("helper_actions") or []
    for i, a in enumerate(actions):
        if a["kind"] == "prefill":
            if st.button("📝 Open the filled-in planning form", key=f"act_{i}", type="primary"):
                fields = a["fields"]
                st.session_state.prefill = fields | {"from_helper": True}
                if fields.get("audience"):
                    st.session_state["audience"] = fields["audience"]
                st.session_state.rec = None
                st.session_state.helper_actions = []
                st.session_state.helper_nav = "plan"
                st.rerun()
        elif a["kind"] == "navigate":
            if st.button(f"➡️ Go to {PAGES[a['page']]}", key=f"act_{i}", type="primary"):
                st.session_state.helper_actions = []
                st.session_state.helper_nav = a["page"]
                st.rerun()
        else:  # a proposed change: nothing is written until the user confirms
            with st.container(border=True):
                st.markdown(f"**Confirm this change?** {a['label']}")
                c1, c2 = st.columns(2)
                if c1.button("✅ Confirm", key=f"ok_{i}", type="primary", width="stretch"):
                    _confirm(a)
                    st.session_state.helper_actions = [x for j, x in enumerate(actions) if j != i]
                    st.rerun(scope="fragment")
                if c2.button("Cancel", key=f"no_{i}", width="stretch"):
                    _say("assistant", "No problem, I didn't change anything.")
                    st.session_state.helper_actions = [x for j, x in enumerate(actions) if j != i]
                    st.rerun(scope="fragment")

    prompt = st.chat_input("Ask about plants, frost dates, your gardens…", max_chars=500)
    if prompt:
        _ask(prompt)
        st.rerun(scope="fragment")
    if hist and st.button("Clear chat", type="tertiary"):
        st.session_state.helper_history = []
        st.session_state.helper_actions = []
        st.rerun(scope="fragment")
    st.caption("The helper uses AI. It can suggest changes, but nothing in your gardens changes until you press Confirm.")
