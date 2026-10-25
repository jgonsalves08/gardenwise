"""Garden helper: a small chat window docked in the bottom-right corner of every page."""

from __future__ import annotations

import html
import re

import streamlit as st

from .. import llm, store
from ..agents.helper import PAGES, run_helper
from ..data import plants
from ..safety import screen_text

CSS = """
<style>
.st-key-helper_fab {position: fixed; bottom: 22px; right: 26px; z-index: 1001; width: auto !important;}
.st-key-helper_fab button {border-radius: 999px !important; padding: .7rem 1.25rem !important; font-weight: 700;
    background: linear-gradient(135deg, #2F6B3F, #3F8650) !important; color: #fff !important; border: none !important;
    box-shadow: 0 10px 26px rgba(47,107,63,.38);}
.st-key-helper_panel {position: fixed; bottom: 84px; right: 26px; z-index: 1000; width: 380px !important;
    max-width: calc(100vw - 32px); background: #FFFFFF; border-radius: 20px; padding: 0 0 .6rem 0 !important;
    box-shadow: 0 18px 48px rgba(30,42,34,.22), 0 2px 6px rgba(30,42,34,.08); border: 1px solid #E3EDE0;
    gap: .4rem !important; overflow: hidden;}
.st-key-helper_panel > div {padding-left: .8rem; padding-right: .8rem;}
.helper-head {margin: 0 -.8rem; padding: .8rem 1rem; color: #fff;
    background: linear-gradient(135deg, #24553A, #3F8650); display: flex; gap: .7rem; align-items: center;}
.helper-avatar {width: 36px; height: 36px; border-radius: 50%; background: rgba(255,255,255,.18);
    display: flex; align-items: center; justify-content: center; font-size: 1.2rem;}
.helper-name {font-weight: 700; font-size: 1rem; line-height: 1.1;}
.helper-status {font-size: .75rem; opacity: .9;}
.helper-status::before {content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #9BE39A; margin-right: 5px; vertical-align: middle;}
.st-key-helper_msgs {background: #F8FBF6; border-radius: 14px;}
.bubble-row {display: flex; margin: .35rem 0;}
.bubble-row.user {justify-content: flex-end;}
.bubble {max-width: 82%; padding: .5rem .75rem; border-radius: 16px; font-size: .9rem; line-height: 1.4;}
.bubble.bot {background: #FFFFFF; border: 1px solid #E3EDE0; border-bottom-left-radius: 4px; color: #1E2A22;}
.bubble.user {background: #2F6B3F; color: #fff; border-bottom-right-radius: 4px;}
.st-key-helper_chips {flex-direction: row !important; flex-wrap: wrap; gap: .35rem !important;}
.st-key-helper_chips .stButton {width: auto !important;}
.st-key-helper_chips button {border-radius: 999px !important; padding: .2rem .7rem !important; min-height: 0 !important;
    font-size: .8rem !important; background: #EEF6EC !important; border: 1px solid #D6E6D3 !important;
    color: #2F6B3F !important; font-weight: 600 !important;}
.st-key-helper_actions button {font-size: .85rem !important;}
.helper-foot {font-size: .7rem; color: #6E7F70; text-align: center;}
</style>
"""
STARTERS = ["Help me plan a garden", "What's due in my gardens this week?", "When is my last frost?",
            "Which herbs grow in shade?"]
GREETING = ("Hi! I'm the Gardenwise helper 🌱 I can answer gardening questions, look up your frost dates, "
            "fill in the planning form for you, or check what's due in your gardens. How can I help?")


def render() -> None:
    """Call once per run, from app.py, before the page renders."""
    nav = st.session_state.pop("helper_nav", None)
    if nav in PAGES:
        st.switch_page(st.session_state.pages[nav])
    st.markdown(CSS, unsafe_allow_html=True)
    is_open = st.session_state.get("helper_open", False)
    with st.container(key="helper_fab"):
        if st.button("✕  Close" if is_open else "💬 Garden helper", key="helper_toggle"):
            st.session_state.helper_open = not is_open
            st.rerun()
    if is_open:
        with st.container(key="helper_panel"):
            chat_panel()


def _say(role: str, text: str) -> None:
    st.session_state.setdefault("helper_history", []).append({"role": role, "text": text})


def _bubble(role: str, text: str) -> str:
    safe = html.escape(text).replace("$", "&#36;")
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe).replace("\n", "<br>")
    side = "user" if role == "user" else "bot"
    return f'<div class="bubble-row {side}"><div class="bubble {side}">{safe}</div></div>'


def _ask(text: str) -> None:
    screen = screen_text(text)
    _say("user", screen.text)
    if screen.refused:
        _say("assistant", screen.refusal)
        return
    history = st.session_state.helper_history[:-1]
    try:
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


@st.fragment
def chat_panel() -> None:
    st.markdown('<div class="helper-head"><div class="helper-avatar">🌱</div><div>'
                '<div class="helper-name">Gardenwise helper</div>'
                '<div class="helper-status">AI assistant · replies in a few seconds</div></div></div>',
                unsafe_allow_html=True)
    hist = st.session_state.setdefault("helper_history", [])
    with st.container(height=330, key="helper_msgs", border=False):
        st.markdown(_bubble("assistant", GREETING) + "".join(_bubble(m["role"], m["text"]) for m in hist),
                    unsafe_allow_html=True)
        actions = st.session_state.get("helper_actions") or []
        with st.container(key="helper_actions"):
            for i, a in enumerate(actions):
                if a["kind"] == "prefill":
                    if st.button("📝 Open the filled-in form", key=f"act_{i}", type="primary", width="stretch"):
                        fields = a["fields"]
                        st.session_state.prefill = fields | {"from_helper": True}
                        if fields.get("audience"):
                            st.session_state["audience"] = fields["audience"]
                        st.session_state.rec = None
                        st.session_state.helper_actions = []
                        st.session_state.helper_nav = "plan"
                        st.rerun()
                elif a["kind"] == "navigate":
                    if st.button(f"➡️ Go to {PAGES[a['page']]}", key=f"act_{i}", type="primary", width="stretch"):
                        st.session_state.helper_actions = []
                        st.session_state.helper_nav = a["page"]
                        st.rerun()
                else:  # a proposed change: nothing is written until the user confirms
                    st.markdown(f"**Confirm?** {html.escape(a['label'])}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ Confirm", key=f"ok_{i}", type="primary", width="stretch"):
                        _confirm(a)
                        st.session_state.helper_actions = [x for j, x in enumerate(actions) if j != i]
                        st.rerun(scope="fragment")
                    if c2.button("Cancel", key=f"no_{i}", width="stretch"):
                        _say("assistant", "No problem, I didn't change anything.")
                        st.session_state.helper_actions = [x for j, x in enumerate(actions) if j != i]
                        st.rerun(scope="fragment")
    if not hist:
        with st.container(key="helper_chips"):
            for i, q in enumerate(STARTERS):
                if st.button(q, key=f"chip_{i}"):
                    with st.spinner("Typing…"):
                        _ask(q)
                    st.rerun(scope="fragment")
    prompt = st.chat_input("Type a message…", max_chars=500, key="helper_input")
    if prompt:
        with st.spinner("Typing…"):
            _ask(prompt)
        st.rerun(scope="fragment")
    f1, f2 = st.columns([3, 1], vertical_alignment="center")
    f1.markdown('<div class="helper-foot">AI can make mistakes. Nothing in your gardens changes until you '
                'press Confirm.</div>', unsafe_allow_html=True)
    if hist and f2.button("Clear", key="helper_clear", type="tertiary"):
        st.session_state.helper_history = []
        st.session_state.helper_actions = []
        st.rerun(scope="fragment")


def open_helper() -> None:
    """Used by the Home page button."""
    st.session_state.helper_open = True
    st.rerun()
