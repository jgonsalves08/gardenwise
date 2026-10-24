"""Sidebar: optional log in / sign up. Guests can use everything except saving."""

from __future__ import annotations

import streamlit as st

from .. import store


def sidebar() -> None:
    user = st.session_state.get("user")
    with st.sidebar:
        if user:
            st.markdown(f"👤 Logged in as **{user['username']}**")
            if st.button("Log out", width="stretch"):
                for k in ("user", "open_garden", "saved_run"):
                    st.session_state.pop(k, None)
                st.rerun()
            return
        with st.expander("👤 Log in / sign up (optional)"):
            st.caption("Save gardens, tick off tasks and shopping, and see what's due each week. "
                       "No email or address needed.")
            mode = st.radio("mode", ["Log in", "Create account"], horizontal=True,
                            label_visibility="collapsed")
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
            st.caption("Just looking? Try the demo accounts (password **garden-demo-2026**): "
                       "**demo** (organizer of a community garden) or **demo_member** (a regular member).")
