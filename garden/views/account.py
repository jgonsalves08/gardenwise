"""Top-right account menu: optional log in / sign up. Guests can use everything except saving."""

from __future__ import annotations

import streamlit as st

from .. import store

TOPBAR_CSS = """
<style>
.st-key-account_bar {position: fixed; top: .55rem; right: 1.2rem; z-index: 1000001; width: auto !important;}
.st-key-account_bar button {border-radius: 999px !important; font-weight: 600; background: #FFFFFF;
    border: 1px solid #D5E3F3; box-shadow: 0 2px 8px rgba(18,36,58,.08);}
</style>
"""


def _logout() -> None:
    for k in ("user", "open_garden", "open_group", "saved_run"):
        st.session_state.pop(k, None)


def topbar() -> None:
    st.markdown(TOPBAR_CSS, unsafe_allow_html=True)
    user = st.session_state.get("user")
    with st.container(key="account_bar"):
        if user:
            with st.popover(f"👤 {user['username']}"):
                st.markdown(f"Logged in as **{user['username']}**")
                st.page_link(st.session_state.pages["gardens"], label="My gardens", icon="🌿")
                st.page_link(st.session_state.pages["dashboard"], label="My dashboard", icon="📊")
                if st.button("Log out", width="stretch", on_click=_logout):
                    st.rerun()
            return
        with st.popover("👤 Log in / Sign up"):
            st.caption("Optional. Save gardens, tick off tasks, and see what's due each week. "
                       "No email or address needed.")
            mode = st.radio("mode", ["Log in", "Create account"], horizontal=True,
                            label_visibility="collapsed", key="auth_mode")
            with st.form("auth_form", border=False):
                username = st.text_input("Username", max_chars=30)
                password = st.text_input("Password", type="password", max_chars=128)
                submitted = st.form_submit_button(mode, type="primary", width="stretch")
            if submitted:
                try:
                    if mode == "Log in":
                        st.session_state.user = store.authenticate(username, password)
                    else:
                        st.session_state.user = store.create_user(username, password)
                    st.rerun()
                except store.AuthError as e:
                    st.error(str(e))
            st.caption("Just looking? Try a demo account (password **garden-demo-2026**): "
                       "**demo** (organizes a community garden) or **demo_member** (a regular member).")
