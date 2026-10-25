"""Shared Streamlit building blocks for every page (planner, saved gardens, this week)."""

from __future__ import annotations

import html
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd
import streamlit as st

from . import config, llm, store
from .data import Location, plants
from .pipeline import Plan, Recommendation, shop_key, task_key

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
html, body, p, li, label, input, textarea, button,
[data-testid="stMarkdownContainer"], [data-testid="stMetricValue"], [data-testid="stMetricLabel"] {
    font-family: 'Inter', system-ui, sans-serif;}
h1, h2, h3, .hero h1, .cal-title, .step-title {font-family: 'Fraunces', Georgia, serif !important;}
[data-testid="stIconMaterial"], .material-symbols-rounded {font-family: 'Material Symbols Rounded' !important;}
/* page: warm paper background with a faint leafy wash */
[data-testid="stAppViewContainer"] {
    background:
      radial-gradient(1200px 500px at 100% -10%, rgba(78,154,94,.10), transparent 60%),
      radial-gradient(900px 400px at -10% 110%, rgba(196,154,92,.08), transparent 60%),
      #F3F2E8;}
[data-testid="stHeader"] {background: transparent;}
.block-container {padding-top: 1.5rem; max-width: 1180px;}
h1, h2, h3, h4 {color: #1E2A22; letter-spacing: -0.01em;}
h2 {font-weight: 700; margin-top: 1.4rem;}
h3 {font-weight: 700; margin-top: 1rem;}
h3::after {content: ""; display: block; width: 42px; height: 3px; border-radius: 3px; margin-top: .35rem;
           background: linear-gradient(90deg, #2F6B3F, #9BC27E);}
/* sidebar */
[data-testid="stSidebar"] {background: linear-gradient(180deg, #EEF5EA 0%, #F6F9F2 100%);
                           border-right: 1px solid #E3EDE0;}
.brand-sub {font-size: .8rem; color: #5C6B5F; margin: -.2rem 0 .9rem .2rem;}
.nav-label {font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
            color: #5C6B5F; margin: .3rem 0 .2rem .2rem;}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {border-radius: 10px; padding: .35rem .6rem;}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {background: #E2EFDE;}
/* cards: white and raised off the page */
[class*="st-key-card_"], [class*="st-key-step_"], .st-key-welcome_guide, [class*="st-key-finish_"] {
    background: #FFFFFF !important; border: 1px solid #E1E9DC !important; border-radius: 18px !important;
    box-shadow: 0 1px 2px rgba(30,42,34,.06), 0 10px 28px rgba(30,42,34,.10) !important;
    transition: transform .15s ease, box-shadow .15s ease;}
[data-testid="stColumn"] > div > [class*="st-key-card_"]:hover {
    transform: translateY(-3px); box-shadow: 0 2px 4px rgba(30,42,34,.06), 0 16px 34px rgba(30,42,34,.14) !important;}
[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E3EDE0; border-radius: 14px;
                          padding: .7rem 1rem; box-shadow: 0 4px 14px rgba(30,42,34,.04);}
[data-testid="stMetricValue"] {color: #2F6B3F; font-weight: 700;}
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: 12px; font-weight: 600; transition: transform .08s ease, box-shadow .15s ease;}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #2F6B3F, #3F8650); border: none;
    box-shadow: 0 4px 12px rgba(47,107,63,.25);}
.stButton > button:hover {transform: translateY(-1px);}
.stTabs [data-baseweb="tab-list"] {gap: .4rem; border-bottom: 1px solid #E3EDE0;}
.stTabs [data-baseweb="tab"] {font-weight: 600; padding: .45rem .9rem; border-radius: 12px 12px 0 0;}
.stTabs [aria-selected="true"] {background: #EEF6EC;}
[data-testid="stExpander"] details {border-radius: 14px; background: #FFFFFF;}
/* hero banner with drawn leaves (pure CSS/SVG, no images) */
.hero {position: relative; overflow: hidden;
       background:
         url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='180' viewBox='0 0 260 180'%3E%3Cg fill='none' stroke='%23ffffff' stroke-opacity='.22' stroke-width='3'%3E%3Cpath d='M30 170 C 90 120, 120 60, 230 20'/%3E%3Cpath fill='%23ffffff' fill-opacity='.10' d='M95 118 C 70 80, 95 50, 140 48 C 135 90, 120 110, 95 118 Z'/%3E%3Cpath fill='%23ffffff' fill-opacity='.10' d='M150 80 C 160 40, 200 30, 228 40 C 210 75, 185 88, 150 80 Z'/%3E%3Cpath fill='%23ffffff' fill-opacity='.08' d='M70 140 C 40 130, 30 100, 45 80 C 70 95, 78 120, 70 140 Z'/%3E%3C/g%3E%3C/svg%3E") no-repeat right -10px bottom -10px,
         radial-gradient(circle at 85% 15%, rgba(255,255,255,.16) 0, transparent 45%),
         linear-gradient(135deg, #24553A 0%, #2F6B3F 45%, #5C9E5F 100%);
       color: white; padding: 1.7rem 2.1rem; border-radius: 22px; margin-bottom: 1.2rem;
       box-shadow: 0 14px 34px rgba(47,107,63,.22);}
.hero h1 {color: white; margin: 0 0 .35rem 0; font-size: 2.2rem;}
.hero p {margin: 0; opacity: .94; font-size: 1.05rem; max-width: 780px;}
.badge {display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: .78rem;
        margin-right: 4px; background: #EEF6EC; color: #2F6B3F; border: 1px solid #D6E6D3;}
.badge.warn {background: #FFF4E5; color: #9A5B00; border-color: #F5D9A8;}
.badge.community {background: #FFF7E6; color: #8A5A00; border-color: #F1DDB0;}
.badge.done {background: #E6F4EA; color: #1E7B3A; border-color: #BFE3D0;}
.muted {color: #5C6B5F; font-size: .9rem;}
.grid {border-collapse: collapse; margin: .4rem 0 1rem 0;}
.grid td {width: 44px; height: 44px; text-align: center; font-size: 1.25rem; line-height: 1;
          border: 2px solid #FFFFFF; border-radius: 6px;}
.plant-photo {border-radius: 12px; object-fit: cover; border: 1px solid #E3EDE0; display: block;}
.plant-photo-empty {display: flex; align-items: center; justify-content: center; font-size: 2.2rem;
                    background: #EEF6EC;}
.region-note {background: #EEF6EC; border: 1px solid #D6E6D3; color: #1E2A22; border-radius: 10px;
              padding: .45rem .8rem; font-size: .88rem; margin: .2rem 0 .8rem 0;}
.guide-grid {display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin: .4rem 0 .9rem 0;}
@media (max-width: 900px) {.guide-grid {grid-template-columns: repeat(2, 1fr);}}
.guide-step {display: flex; gap: .6rem; background: #F8FBF6; border: 1px solid #E3EDE0; border-radius: 12px;
             padding: .7rem .8rem; font-size: .92rem;}
.guide-num {flex: 0 0 auto; width: 28px; height: 28px; border-radius: 50%; background: #2F6B3F; color: #fff;
            display: flex; align-items: center; justify-content: center; font-weight: 700;}
.page-tip {background: #FFFBEA; border: 1px solid #F3E3A4; border-radius: 10px; padding: .45rem .8rem;
           font-size: .9rem; color: #1E2A22;}
[class*="st-key-navbtn_"] button {justify-content: flex-start !important; padding: .4rem .65rem !important;
    border-radius: 10px !important; color: #1E2A22 !important; font-weight: 500 !important; min-height: 0 !important;}
[class*="st-key-navbtn_"] button > div, [class*="st-key-navbtn_"] button p {justify-content: flex-start !important;
    text-align: left !important; width: 100%;}
[class*="st-key-navbtn_"] button:hover {background: #E2EFDE !important;}
[class*="st-key-navbtn_"][class*="_on"] button {background: #DCEBD6 !important; font-weight: 700 !important;}
[class*="st-key-navbtn_"] {gap: 0 !important;}
.st-key-brand_link a {padding: .2rem .2rem !important;}
.st-key-brand_link a p {font-family: 'Fraunces', Georgia, serif !important; font-size: 1.35rem !important;
    font-weight: 700 !important; color: #2F6B3F !important;}
.home-hero {padding: 2.2rem 2.2rem;}
.home-hero h1 {font-size: 2.4rem;}
.home-hero p {font-size: 1.12rem; max-width: 760px;}
.aud-icon {font-size: 1.8rem; margin-bottom: .2rem;}
.aud-desc {min-height: 3.2rem; margin: .2rem 0 .6rem 0;}
.why-card {background: #FFFFFF; border: 1px solid #E3EDE0; border-radius: 12px; padding: .8rem .9rem;
           font-size: .92rem;}
/* pills / segmented buttons wrap onto new lines instead of scrolling sideways */
[data-testid="stButtonGroup"] > div {flex-wrap: wrap !important; overflow-x: visible !important; row-gap: .35rem;}
/* planning form steps */
.step-head {display: flex; gap: .85rem; align-items: flex-start; margin-bottom: .6rem;}
.step-num {flex: 0 0 auto; width: 38px; height: 38px; border-radius: 50%; color: #fff; font-weight: 700;
           display: flex; align-items: center; justify-content: center; font-size: 1.05rem;
           background: linear-gradient(135deg, #2F6B3F, #5C9E5F); box-shadow: 0 4px 10px rgba(47,107,63,.25);}
.step-kicker {font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #6E8B67;}
.step-title {font-size: 1.25rem; font-weight: 700; color: #1E2A22; line-height: 1.25;}
.step-optional {font-family: 'Inter', sans-serif; font-size: .7rem; font-weight: 600; color: #6E8B67;
                background: #EEF6EC; border: 1px solid #D6E6D3; border-radius: 999px; padding: 1px 8px;
                vertical-align: middle;}
[class*="st-key-step_"] {border-left: 4px solid #9BC27E !important;}
.st-key-go_recommend button {font-size: 1.1rem; padding: .8rem 1rem;}
/* dismiss ✕ inside alerts and tips */
[class*="st-key-alert_"], [class*="st-key-tipbox_"] {position: relative; gap: 0 !important;}
[class*="st-key-alert_"] [data-testid="stAlert"] {padding-right: 2.6rem;}
[class*="st-key-tipbox_"] .page-tip {padding-right: 2.6rem;}
[class*="st-key-alert_"] > [data-testid="stElementContainer"]:has(.stButton),
[class*="st-key-tipbox_"] > [data-testid="stElementContainer"]:has(.stButton) {
    position: absolute !important; top: .55rem; right: .6rem; width: auto !important; z-index: 2; margin: 0;}
[class*="st-key-alert_"] .stButton button, [class*="st-key-tipbox_"] .stButton button {
    width: 28px; height: 28px; min-height: 28px; padding: 0; border-radius: 50%;
    border: 1px solid rgba(30,42,34,.15); background: rgba(255,255,255,.75); font-size: .8rem; line-height: 1;}
[class*="st-key-tipbox_"] > [data-testid="stElementContainer"]:has(.stButton) {top: .3rem;}
.legend-chip {display: inline-block; padding: 4px 10px; border-radius: 999px; margin: 0 6px 6px 0;
              font-size: .85rem; color: #1E2A22;}
.month {color: #2F6B3F; margin: 1rem 0 .3rem 0; font-weight: 700;}
.cal {width: 100%; border-collapse: separate; border-spacing: 4px; table-layout: fixed; margin-bottom: .8rem;}
.cal th {color: #5C6B5F; font-size: .8rem; font-weight: 600; text-align: left; padding: 2px 6px;}
.cal td {vertical-align: top; height: 92px; background: #F8FBF6; border: 1px solid #E3EDE0;
         border-radius: 8px; padding: 4px 6px; overflow: hidden;}
.cal td.cal-empty {background: transparent; border: none;}
.cal td.cal-today {border: 2px solid #2F6B3F; background: #EEF6EC;}
.cal-day {font-size: .78rem; font-weight: 700; color: #1E2A22; margin-bottom: 2px;}
.cal-chip {font-size: .72rem; background: #FFFFFF; border: 1px solid #D6E6D3; border-radius: 6px;
           padding: 1px 5px; margin-bottom: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.cal-chip.cal-done {text-decoration: line-through; color: #8A99AD; background: #F0F3F7;}
.cal-title {text-align: center; font-size: 1.3rem; font-weight: 700; color: #2F6B3F;}
.task {padding: .25rem 0 .25rem .6rem; border-left: 3px solid #D6E6D3; margin-left: .2rem;}
.shop td, .shop th {padding: 4px 10px; border-bottom: 1px solid #EEF6EC; font-size: .9rem;}
.shop th {text-align: left; color: #2F6B3F;}
</style>
"""

PLANT_ICONS = {
    "arugula": "🥬", "basil": "🌿", "bean_bush": "🫘", "bean_pole": "🫘", "bee_balm": "🌺", "beet": "🟣",
    "calendula": "🌼", "carrot": "🥕", "chamomile": "🌼", "chives": "🌱", "cilantro": "🌿", "coneflower": "🌸",
    "corn_sweet": "🌽", "cosmos": "🌸", "cucumber_pickling": "🥒", "dill": "🌿", "garlic": "🧄", "kale": "🥬",
    "lavender": "💜", "lemon_balm": "🍋", "lettuce": "🥬", "marigold": "🌼", "microgreens": "🌱", "mint": "🌿",
    "nasturtium": "🏵️", "onion_sets": "🧅", "oregano": "🌿", "parsley": "🌿", "pea_snap": "🫛",
    "pepper_bell": "🫑", "pepper_jalapeno": "🌶️", "potato": "🥔", "pumpkin": "🎃", "radish": "🔴",
    "scallion": "🧅", "spinach": "🥬", "squash_butternut": "🎃", "strawberry": "🍓", "sunflower": "🌻",
    "swiss_chard": "🥬", "thyme": "🌿", "tomatillo": "🟢", "tomato_cherry": "🍅", "tomato_paste": "🍅",
    "tomato_slicing": "🍅", "winter_rye": "🌾", "zinnia": "🌺", "zucchini": "🥒",
}


def plant_icon(pid: str) -> str:
    return PLANT_ICONS.get(pid, "🌱")


@st.cache_data(show_spinner=False)
def photo_credits() -> dict:
    import json
    p = config.DATA_DIR / "plant_images" / "credits.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


@st.cache_data(show_spinner=False)
def plant_photo_url(pid: str) -> str | None:
    """Local photo as a data URL (photos ship with the repo; the app never fetches from the web)."""
    import base64
    p = config.DATA_DIR / "plant_images" / f"{pid}.jpg"
    if not p.exists():
        return None
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def plant_photo_html(pid: str, size: int = 92) -> str:
    url = plant_photo_url(pid)
    name = html.escape(plants()[pid].name)
    if not url:
        return (f'<div class="plant-photo plant-photo-empty" style="width:{size}px;height:{size}px">'
                f'{plant_icon(pid)}</div>')
    cr = photo_credits().get(pid, {})
    credit = html.escape(f"Photo: {cr.get('author', 'Wikimedia Commons')} · {cr.get('license', '')} "
                         "· Wikimedia Commons")
    return (f'<img class="plant-photo" src="{url}" alt="{name}" title="{credit}" '
            f'style="width:{size}px;height:{size}px">')


GRID_COLORS = ["#CFE3F2", "#BFE3D0", "#FCE3B6", "#F5C9C9", "#DCD3F2", "#C9EEF2", "#F2E6C9", "#D9EBC5"]
TASK_ICONS = {"prep": "🧪", "build": "🔨", "buy": "🛒", "start_indoors": "🌡️", "plant": "🌱",
              "harvest": "🧺", "now": "⭐", "care": "💧"}
METHOD_LABEL = {"buy_transplants": "buy transplants", "start_indoors": "start from seed indoors",
                "direct_sow": "sow seeds directly", "indoor": "grow indoors"}


@dataclass
class Checklist:
    """Present when viewing a saved garden: tasks and shopping items become tickable (and movable)."""
    garden_id: int
    owner_id: int
    done: dict[str, str]
    loc: Location | None = None


_card_counter = {"n": 0}


def card_key() -> str:
    """Stable per-run key for bordered cards, so CSS can style them on any Streamlit version."""
    _card_counter["n"] += 1
    return f"card_{_card_counter['n']}"


def reset_cards() -> None:
    _card_counter["n"] = 0


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def money(x: float) -> str:
    """Rounded estimate, safe inside st.markdown (a bare $ pair renders as LaTeX)."""
    return f"~&#36;{round(x):,}"


def est(x: float) -> str:
    """Rounded estimate for plain-text widgets (metrics, captions)."""
    return f"~${round(x):,}"


def md(text: str) -> str:
    return text.replace("$", "\\$")


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def _toggle(cl: Checklist, key: str, widget_key: str) -> None:
    store.set_check(cl.garden_id, cl.owner_id, key, bool(st.session_state.get(widget_key)))


def check_box(cl: Checklist, item_key: str, label: str, help: str | None = None) -> bool:
    wk = f"chk_{cl.garden_id}_{item_key}"
    return st.checkbox(label, value=item_key in cl.done, key=wk, help=help,
                       on_change=_toggle, args=(cl, item_key, wk))


# ---------- sidebar ----------
def usage_panel(budget: llm.Budget) -> None:
    with st.sidebar.expander("📊 AI usage this session", expanded=False):
        used = budget.tokens_used
        st.progress(min(1.0, used / budget.token_cap), text=f"{used:,} / {budget.token_cap:,} tokens")
        c1, c2 = st.columns(2)
        c1.metric("AI calls", f"{len(budget.calls)} / {budget.call_cap}")
        c2.metric("Cost", f"${budget.cost_usd:.4f}")
        if budget.calls:
            cached = sum(c.cached_tokens for c in budget.calls)
            inp = sum(c.input_tokens for c in budget.calls)
            st.caption(f"Cached input: {cached:,} of {inp:,} tokens "
                       f"({(cached / inp * 100) if inp else 0:.0f}%)")
            st.dataframe(pd.DataFrame([{
                "agent": c.agent, "in": c.input_tokens, "cached": c.cached_tokens,
                "out": c.output_tokens, "ms": c.latency_ms, "$": round(c.cost_usd, 5),
                "ok": "✅" if c.ok else "❌",
            } for c in budget.calls]), hide_index=True, width="stretch")
        st.caption(f"Model: `{config.MODEL_NAME}` · every call is logged to `logs/usage.jsonl`.")
    status = config.env_status()
    if not (status["portkey_key"] or status["openai_key"]):
        st.sidebar.error("No API key found. Add PORTKEY_API_KEY to a .env in this folder "
                         "or the folder above it.")


# ---------- plan header ----------
def location_header(loc: Location, total: float) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("USDA hardiness zone", loc.zone,
              help="Tells you which perennial plants survive your winters. Lower numbers = colder winters.")
    m2.metric("Avg last spring frost", loc.last_frost_on(2000).strftime("%b %d"),
              help="After this date, frost is unlikely (about a 50/50 chance). "
                   "Frost-tender plants like tomatoes go out 1–3 weeks later.")
    m3.metric("Avg first fall frost", loc.first_frost_on(2000).strftime("%b %d"),
              help="Around this date, the first frost usually kills tender plants.")
    m4.metric("Estimated cost", est(total), help=config.SHOP_PRICE_NOTE)
    with st.popover("ℹ️ What do zone and frost dates mean?"):
        lf, ff = loc.last_frost_on(2000), loc.first_frost_on(2000)
        st.markdown(f"""
**USDA hardiness zone ({loc.zone})** — The US Department of Agriculture splits the country into
zones by the coldest night of an average winter. Zone {loc.zone_num} means winters typically
bottom out around **{-60 + 10 * loc.zone_num}°F to {-50 + 10 * loc.zone_num}°F**.
It matters most for **plants that come back every year** (perennials like lavender, strawberries,
coneflower): a plant labeled "zones 5–9" survives winter here only if {loc.zone_num} is in that range.

**Frost dates** — The average dates of the last frost in spring (**{lf:%B %d}**) and the first
frost in fall (**{ff:%B %d}**). The time between them is your growing season, about
**{(ff - lf).days} days** here. Every date in your calendar is counted from these two days.

*Rule of thumb:* cool-season crops (lettuce, peas, spinach) go in a few weeks **before** the last
frost; warm-season crops (tomatoes, peppers, basil) go in 1–3 weeks **after** it.
""")


def verification_panel(rec: Recommendation) -> None:
    r = rec.report
    if r is None:
        return
    n_pass = sum(c.status == "pass" for c in r.checks)
    n_warn = sum(c.status == "warn" for c in r.checks)
    n_fail = sum(c.status == "fail" for c in r.checks)
    title = f"🔎 How we checked these plants: {n_pass}/{len(r.checks)} checks passed"
    if n_warn:
        title += f", {n_warn} warning(s)"
    if r.attempts > 1:
        title += " · selector retried once"
    if r.repaired:
        title += " · failing picks removed"
    with st.expander(title):
        st.caption("Every AI pick is checked against the plant database and your frost dates before "
                   "you see it. If a check fails, the AI gets one retry with the errors; after that, "
                   "failing picks are removed instead of looping.")
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
        for c in r.checks:
            st.markdown(f"{icon[c.status]} **{html.escape(c.name)}** "
                        f"<span class='muted'>{html.escape(c.detail)}</span>".replace("$", "&#36;"),
                        unsafe_allow_html=True)
        if n_fail:
            st.caption(f"{n_fail} check(s) still failing after the retry; those plants were dropped.")


# ---------- plants ----------
def plant_chooser(rec: Recommendation, plan: Plan, key_prefix: str, chosen_default: set[str]) -> None:
    alloc = {a.plant_id: a for a in plan.allocations}
    sched = {s.plant_id: s for s in plan.schedules}
    cols = st.columns(2)
    picked_ids = {pk.plant_id for pk in rec.picks}
    options = list(rec.picks) + list(rec.alternates)
    for i, pk in enumerate(options):
        p = plants()[pk.plant_id]
        with cols[i % 2].container(border=True, key=card_key()):
            ph, txt = st.columns([1, 3.2])
            ph.markdown(plant_photo_html(p.id), unsafe_allow_html=True)
            label = f"**{p.name}**" + ("" if p.id in picked_ids else "  ·  *also a good fit*")
            txt.checkbox(label, key=f"{key_prefix}_pick_{p.id}", value=p.id in chosen_default)
            pets = [k for k, v in p.pet_toxic.model_dump().items() if v]
            badges = f'<span class="badge">{p.difficulty}</span>'
            if p.id in alloc:
                a = alloc[p.id]
                if a.count == 0:
                    badges += '<span class="badge warn">no room left — untick something</span>'
                else:
                    qty = (f"{a.count} plant(s) in {a.containers} pot(s)" if a.containers
                           else f"{a.count} plant(s) · {a.squares} sq ft")
                    badges += f'<span class="badge">{qty}</span>'
            if pets:
                badges += f'<span class="badge warn">toxic to {"/".join(pets)}</span>'
            body = f'{badges}<p style="margin:.5rem 0">{html.escape(pk.reason)}</p>'
            if pk.lesson:
                body += f'<div class="muted">🍎 <b>Classroom tie-in:</b> {html.escape(pk.lesson)}</div>'
            if p.id in sched:
                s = sched[p.id]
                body += (f'<div class="muted">🌱 {METHOD_LABEL[s.method]}, plant out '
                         f'<b>{s.plant_out:%b %d, %Y}</b> · 🧺 harvest {s.harvest_start:%b %d} – '
                         f'{s.harvest_end:%b %d}</div>')
            else:
                body += '<div class="muted">Not in your plan — tick the box to add it.</div>'
            txt.markdown(body, unsafe_allow_html=True)


def chosen_from_state(rec: Recommendation, key_prefix: str, chosen_default: set[str]) -> list[str]:
    return [pk.plant_id for pk in list(rec.picks) + list(rec.alternates)
            if st.session_state.get(f"{key_prefix}_pick_{pk.plant_id}", pk.plant_id in chosen_default)]


# ---------- calendar ----------
def _date_warning(t, new, loc: Location | None) -> str:
    """Code check when someone moves a task: frost-tender plantings before the last frost, etc."""
    if loc is None or t.plant_id not in plants():
        return ""
    p = plants()[t.plant_id]
    lf = loc.last_frost_on(new.year)
    if t.kind == "plant" and p.frost_tender and new < lf:
        return (f"⚠️ That's before your average last frost ({lf:%b %d}). Frost can kill {p.name.lower()}; "
                "cover it or wait if a cold night is forecast.")
    if t.kind == "plant" and p.frost_tender and new > loc.first_frost_on(new.year) - timedelta(days=p.days_to_maturity):
        return f"⚠️ That's late: {p.name.lower()} may not ripen before your first fall frost."
    return ""


def _task_line(t, cl: Checklist | None, seen: set[str]) -> None:
    if cl and task_key(t) in seen:
        return  # identical task listed twice: show it once
    seen.add(task_key(t))
    if cl:
        key = task_key(t)
        moved = f" *(moved from {t.recommended:%b %d})*" if t.recommended else ""
        a, b = st.columns([14, 1.4], vertical_alignment="center")
        with a:
            check_box(cl, key, md(f"{TASK_ICONS[t.kind]} **{t.when:%b %d}** · {t.title}{moved}"),
                      help=t.detail or None)
        with b.popover("📅", help="Change this task's date"):
            st.markdown(f"**{md(t.title)}**")
            st.caption(f"Recommended: {(t.recommended or t.when):%b %d, %Y}")
            new = st.date_input("New date", value=t.when, key=f"td_{cl.garden_id}_{key}")
            warn = _date_warning(t, new, cl.loc)
            if warn:
                st.warning(md(warn))
            c1, c2 = st.columns(2)
            if c1.button("Save", key=f"tds_{cl.garden_id}_{key}", type="primary", width="stretch"):
                store.set_task_date(cl.garden_id, cl.owner_id, key, None if new == (t.recommended or t.when) and
                                    t.recommended else new)
                st.rerun()
            if t.recommended and c2.button("Reset", key=f"tdr_{cl.garden_id}_{key}", width="stretch",
                                           help="Go back to Gardenwise's recommended date"):
                store.set_task_date(cl.garden_id, cl.owner_id, key, None)
                st.rerun()
    else:
        detail = f' <span class="muted">— {html.escape(t.detail)}</span>' if t.detail else ""
        st.markdown(f'<div class="task">{TASK_ICONS[t.kind]} <b>{t.when:%b %d}</b> · '
                    f'{html.escape(t.title)}{detail}</div>'.replace("$", "&#36;"), unsafe_allow_html=True)


def _month_grid(year: int, month: int, tasks: list, cl: Checklist | None) -> str:
    import calendar as pycal
    from datetime import date as _date

    today = _date.today()
    by_day: dict[int, list] = defaultdict(list)
    for t in tasks:
        if t.when.year == year and t.when.month == month:
            by_day[t.when.day].append(t)
    head = "".join(f"<th>{d}</th>" for d in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
    rows = []
    for week in pycal.Calendar(firstweekday=6).monthdayscalendar(year, month):
        cells = []
        for day in week:
            if day == 0:
                cells.append('<td class="cal-empty"></td>')
                continue
            cls = "cal-today" if _date(year, month, day) == today else ""
            chips = ""
            for t in by_day.get(day, []):
                done = cl is not None and task_key(t) in cl.done
                chips += (f'<div class="cal-chip{" cal-done" if done else ""}" title="{html.escape(t.title)}">'
                          f'{TASK_ICONS[t.kind]} {html.escape(t.title)}</div>')
            cells.append(f'<td class="{cls}"><div class="cal-day">{day}</div>{chips}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="cal"><tr>{head}</tr>{"".join(rows)}</table>'


task_line = _task_line   # used by This week too


def calendar_view(plan: Plan, cl: Checklist | None = None, key_prefix: str = "cal") -> None:
    from datetime import date as _date

    if cl:
        n_done = sum(task_key(t) in cl.done for t in plan.tasks)
        st.progress(n_done / max(1, len(plan.tasks)), text=f"{n_done} of {len(plan.tasks)} tasks done")
    mode = st.segmented_control("View", ["📆 Month", "📋 List"], default="📆 Month",
                                key=f"{key_prefix}_calmode", label_visibility="collapsed") or "📆 Month"
    seen: set[str] = set()
    if mode == "📋 List":
        by_month: dict[str, list] = defaultdict(list)
        for t in plan.tasks:
            by_month[t.when.strftime("%B %Y")].append(t)
        for month, tasks in by_month.items():
            st.markdown(f'<div class="month">{month}</div>', unsafe_allow_html=True)
            for t in tasks:
                _task_line(t, cl, seen)
        return

    # Month view: every month from the first task to the last, opening on this month if it has tasks.
    if not plan.tasks:
        st.caption("No tasks yet.")
        return
    first, last = plan.tasks[0].when.replace(day=1), plan.tasks[-1].when.replace(day=1)
    months, m = [], first
    while m <= last:
        months.append(m)
        m = _date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    this_month = _date.today().replace(day=1)
    upcoming = [mo for mo in months if mo >= this_month]
    idx_key = f"{key_prefix}_calidx"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = months.index(upcoming[0]) if upcoming else 0
    idx = min(st.session_state[idx_key], len(months) - 1)

    c1, c2, c3 = st.columns([1, 3, 1], vertical_alignment="center")
    if c1.button("◀ Previous", key=f"{key_prefix}_prev", disabled=idx == 0, width="stretch"):
        st.session_state[idx_key] = idx - 1
        st.rerun()
    c2.markdown(f'<div class="cal-title">{months[idx]:%B %Y}</div>', unsafe_allow_html=True)
    if c3.button("Next ▶", key=f"{key_prefix}_next", disabled=idx == len(months) - 1, width="stretch"):
        st.session_state[idx_key] = idx + 1
        st.rerun()
    month = months[idx]
    st.markdown(_month_grid(month.year, month.month, plan.tasks, cl), unsafe_allow_html=True)
    month_tasks = [t for t in plan.tasks if t.when.year == month.year and t.when.month == month.month]
    if month_tasks:
        st.markdown(f"**This month's tasks**" + (" — tick them off here" if cl else ""))
        for t in month_tasks:
            _task_line(t, cl, seen)
    else:
        st.caption("Nothing scheduled this month. Use ◀ ▶ to look ahead.")


# ---------- layout ----------
def layout_view(plan: Plan) -> None:
    c = plan.constraints
    db = plants()
    color = {a.plant_id: GRID_COLORS[i % len(GRID_COLORS)] for i, a in enumerate(plan.allocations)}
    if not plan.grid:
        for a in plan.allocations:
            st.markdown(f"- **{db[a.plant_id].name}**: {a.containers} pot(s), {a.count} plant(s)")
    else:
        st.caption("Top-down view, north at the top. Each square is 1 × 1 ft. "
                   "Tall plants sit on the north side so they don't shade the rest.")
        rows = []
        for row in plan.grid:
            tds = "".join(
                f'<td style="background:{color[cid]}" title="{html.escape(db[cid].name)}">'
                f'{plant_icon(cid)}</td>' if cid else
                '<td style="background:#F3F6F0" title="open space"></td>' for cid in row)
            rows.append(f"<tr>{tds}</tr>")
        st.markdown(f'<table class="grid">{"".join(rows)}</table>', unsafe_allow_html=True)
        legend = " ".join(f'<span class="legend-chip" style="background:{color[a.plant_id]}">'
                          f'{plant_icon(a.plant_id)} <b>{html.escape(db[a.plant_id].name)}</b> × {a.count}'
                          f'<span class="muted"> · {a.squares} sq ft</span></span>'
                          for a in plan.allocations if a.count)
        st.markdown(legend, unsafe_allow_html=True)
        if c.space_type == "in_ground":
            st.caption("About 30% of an in-ground plot is left for paths.")
    if plan.free_space:
        unit = "pot(s)" if c.space_type in ("containers", "windowsill") else "sq ft"
        st.info(f"🟦 {plan.free_space} {unit} still open — tick another recommended plant to use it.")


# ---------- shopping ----------
def _material_table(lines) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(m.item)}</td><td>{m.qty}</td><td>{money(m.unit_price)}</td>"
        f"<td>{money(m.subtotal)}</td><td>"
        + " · ".join(f'<a href="{u}" target="_blank">{s}</a>' for s, u in m.store_links.items())
        + "</td></tr>" for m in lines)
    return (f'<table class="shop"><tr><th>Item</th><th>Qty</th><th>Each</th><th>Subtotal</th>'
            f"<th>Find it</th></tr>{rows}</table>")


def _material_checklist(lines, cl: Checklist, group: str) -> None:
    for m in lines:
        links = " · ".join(f"[{s}]({u})" for s, u in m.store_links.items())
        check_box(cl, shop_key(group, m.item), md(f"{m.item} × {m.qty} — {est(m.subtotal)}"))
        st.caption(links)


def shopping_view(rec: Recommendation, plan: Plan, key_prefix: str, advised_default: set[str],
                  cl: Checklist | None = None) -> None:
    c = plan.constraints
    if cl:
        all_lines = plan.shopping_lines()
        got = sum(shop_key(g, m.item) in cl.done for g, m in all_lines)
        st.progress(got / max(1, len(all_lines)), text=f"{got} of {len(all_lines)} items bought")
    st.markdown(f"#### 🌱 Plants & seeds — **{money(plan.plant_total)}**", unsafe_allow_html=True)
    if cl:
        _material_checklist(plan.plant_costs, cl, "plants")
    else:
        st.markdown(_material_table(plan.plant_costs), unsafe_allow_html=True)
    for b in plan.builds:
        st.markdown(f"#### 🔨 {html.escape(b.name)} — **{money(b.total_usd)}**", unsafe_allow_html=True)
        st.caption(md(b.why))
        if cl:
            _material_checklist(b.materials, cl, b.build_id)
        else:
            st.markdown(_material_table(b.materials), unsafe_allow_html=True)
        for n in b.notes:
            st.caption(md(f"• {n}"))

    st.markdown("---")
    lo, hi = c.budget_min, c.budget_max
    budget_txt = (f"&#36;{lo:,} – &#36;{hi:,}" if hi is not None else f"&#36;{lo:,}+ (no maximum)")
    st.markdown(f"### Estimated total: {money(plan.total)}", unsafe_allow_html=True)
    st.caption(config.SHOP_PRICE_NOTE)
    st.markdown(f'<span class="muted">Your budget: {budget_txt}</span>', unsafe_allow_html=True)
    for n in plan.budget_notes:
        (st.success if n.startswith("✅") else st.warning)(md(n))

    advised = dict(rec.build_recs)
    included = {b.build_id: b for b in plan.builds if b.build_id not in ("raised_bed", "container_setup")}
    options = {b.build_id: b for b in plan.addons} | included
    if options:
        st.markdown("#### ➕ Optional add-ons")
        st.caption("Tick any you'd like; the total and calendar update instantly.")
        for bid, b in sorted(options.items(), key=lambda kv: kv[0] not in advised):
            st.checkbox(md(f"{b.name} — {est(b.total_usd)}"), key=f"{key_prefix}_addon_{bid}",
                        value=bid in advised_default, help=b.why)
            if bid in advised:
                st.caption(f"⭐ Recommended for you: {md(advised[bid])}")



def addons_from_state(key_prefix: str, addon_default: set[str]) -> list[str]:
    from .data import builds
    return [b["id"] for b in builds()["builds"]
            if st.session_state.get(f"{key_prefix}_addon_{b['id']}", b["id"] in addon_default)]


def _alert_id(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def dismissible_alerts(warnings: list[str], scope: str, cl: Checklist | None = None) -> None:
    """Warnings with a ✕ button. Saved gardens remember dismissals in the database;
    guests' dismissals last for the browser session."""
    session_dismissed: set[str] = st.session_state.setdefault("dismissed_alerts", set())

    def is_dismissed(aid: str) -> bool:
        return (f"dismiss|{aid}" in cl.done) if cl else (f"{scope}|{aid}" in session_dismissed)

    def dismiss(aid: str) -> None:
        if cl:
            store.set_check(cl.garden_id, cl.owner_id, f"dismiss|{aid}", True)
        else:
            session_dismissed.add(f"{scope}|{aid}")

    def restore_all() -> None:
        for w in warnings:
            aid = _alert_id(w)
            if cl:
                store.set_check(cl.garden_id, cl.owner_id, f"dismiss|{aid}", False)
            else:
                session_dismissed.discard(f"{scope}|{aid}")

    hidden = 0
    for w in warnings:
        aid = _alert_id(w)
        if is_dismissed(aid):
            hidden += 1
            continue
        with st.container(key=f"alert_{scope}_{aid}"):   # ✕ sits inside the alert's top-right corner
            st.warning(md(w))
            st.button("✕", key=f"dismiss_{scope}_{aid}", help="Dismiss this alert",
                      on_click=dismiss, args=(aid,))
    if hidden:
        st.button(f"Show {hidden} dismissed alert(s)", key=f"restore_{scope}", type="tertiary",
                  on_click=restore_all)


def harvest_panel(plan: Plan) -> None:
    """How much the garden should produce, and (for households) how much of the need it covers."""
    c = plan.constraints
    lb, value = plan.expected_harvest()
    if not lb and not plan.coverage:
        return
    with st.container(border=True, key=card_key()):
        cols = st.columns(2)
        cols[0].metric("Expected harvest", f"~{lb:,.0f} lb",
                       help="Typical home-garden yields per plant (extension guides). Weather, pests "
                            "and care can easily move this ±50%.")
        if plan.coverage:
            planned = sum(min(have, need) for _, have, need in plan.coverage)
            needed = sum(need for _, _, need in plan.coverage)
            who = (f"{c.adults} adult(s)" + (f" + {c.kids} kid(s)" if c.kids else "")
                   if c.audience == "household" else "1 person")
            cols[1].metric(f"Covers {who}", f"{planned / max(1, needed):.0%}",
                           help="Share of the plants a household this size would eat fresh in a "
                                "season, for the crops you picked.")
            short = [(pid, have, need) for pid, have, need in plan.coverage if have < need]
            if short:
                names = "; ".join(f"{plants()[pid].name}: {have} of ~{need}" for pid, have, need in short)
                st.caption(f"🍽️ Space-limited: {names}. More room (or fewer crops) gets you closer.")
            extra = [(pid, have, need) for pid, have, need in plan.coverage if have > need]
            if extra:
                st.caption("🫙 Extra for sharing or preserving: " +
                           "; ".join(f"{plants()[pid].name} +{have - need}" for pid, have, need in extra))
        if value:
            st.caption(md(f"🛒 Worth roughly ${round(value):,} at grocery prices. ") + config.GROCERY_PRICE_NOTE)


# ---------- harvest log ----------
SIZE_BUTTONS = [("handful", "🤏 Handful"), ("bowl", "🥣 Bowl"), ("basket", "🧺 Basket")]


def _log(cl: Checklist, plant, size: str, donate_key: str) -> None:
    lb = store.size_to_lb(size, plant.category, plant.edible)
    store.log_harvest(cl.garden_id, cl.owner_id, plant.id, size, lb,
                      donated=bool(st.session_state.get(donate_key)))
    what = f"a {size} of {plant.name.lower()}" if plant.edible else f"{plant.name.lower()} flowers"
    st.toast(f"🧺 Logged {what}" + (f" (~{lb:g} lb)" if lb else ""))


def quick_harvest_row(cl: Checklist, plant, key: str, in_season: bool = True) -> None:
    """One tap to log a harvest. No weighing: sizes convert to approximate pounds."""
    cols = st.columns([3, 1, 1, 1, 1.3], vertical_alignment="center")
    cols[0].markdown(f"**{plant.name}**" + ("" if in_season else " <span class='muted'>(not in season)</span>"),
                     unsafe_allow_html=True)
    donate_key = f"don_{key}"
    cols[4].checkbox("🎁 Donated", key=donate_key, help="Tick before tapping a size if this harvest was given away "
                                                       "(food pantry, neighbors).")
    if plant.edible:
        for i, (size, label) in enumerate(SIZE_BUTTONS, start=1):
            cols[i].button(label, key=f"hv_{key}_{size}", on_click=_log, args=(cl, plant, size, donate_key),
                           width="stretch")
    else:
        cols[1].button("💐 Picked", key=f"hv_{key}_bunch", on_click=_log, args=(cl, plant, "bunch", donate_key),
                       width="stretch")


def harvest_tab(plan: Plan, cl: Checklist) -> None:
    from datetime import date as _date
    today = _date.today()
    st.caption("Totally optional. Tap a size when you pick something; no scale needed. "
               "Ticking a “Start harvesting” task in the calendar also counts as a harvest.")
    in_season = {s.plant_id for s in plan.schedules if s.harvest_start <= today <= s.harvest_end}
    for p in sorted(plan.plants, key=lambda p: p.id not in in_season):
        quick_harvest_row(cl, p, f"{cl.garden_id}_{p.id}", p.id in in_season)
    logs = store.list_harvests(cl.garden_id)
    if not logs:
        return
    st.markdown("#### So far")
    by_crop: dict[str, list] = defaultdict(list)
    for h in logs:
        by_crop[h["plant_id"]].append(h)
    names = {p.id: p.name for p in plan.plants}
    total = sum(h["est_lb"] for h in logs)
    donated = sum(h["est_lb"] for h in logs if h["donated"])
    m1, m2, m3 = st.columns(3)
    m1.metric("Harvests logged", len(logs))
    m2.metric("Approx. pounds", f"{total:,.1f}")
    m3.metric("Donated", f"{donated:,.1f} lb")
    st.table(pd.DataFrame([{"Crop": names.get(pid, pid), "Times": len(hs),
                            "Approx. lb": f'{sum(h["est_lb"] for h in hs):,.2f}'}
                           for pid, hs in by_crop.items()]).set_index("Crop"))
    with st.expander("Recent entries (undo mistakes here)"):
        for h in logs[:15]:
            c1, c2 = st.columns([6, 1], vertical_alignment="center")
            c1.markdown(f"{h['picked_on']} · {names.get(h['plant_id'], h['plant_id'])} · {h['size']}"
                        + (" · 🎁 donated" if h["donated"] else ""))
            if c2.button("✕", key=f"delhv_{h['id']}", help="Delete this entry"):
                store.delete_harvest(h["id"], cl.owner_id)
                st.rerun()


def plan_tabs(rec: Recommendation, plan: Plan, key_prefix: str, addon_default: set[str],
              cl: Checklist | None = None) -> None:
    dismissible_alerts(plan.warnings, key_prefix, cl)
    harvest_panel(plan)
    names = ["🗺️ Layout", "📅 Calendar", "🛒 Shopping list & budget"] + (["🧺 Harvest log"] if cl else [])
    tabs = st.tabs(names)
    with tabs[0]:
        layout_view(plan)
    with tabs[1]:
        calendar_view(plan, cl, key_prefix)
    with tabs[2]:
        shopping_view(rec, plan, key_prefix, addon_default, cl)
    if cl:
        with tabs[3]:
            harvest_tab(plan, cl)


# ---------- onboarding ----------
GUIDE_STEPS = [
    ("1", "Tell us about your spot", "Who it's for, where you are, your skill and goals, and your space. "
                                      "About a minute. Sun, pets, budget and photos are optional."),
    ("2", "Pick your plants", "We recommend plants that fit, checked against your local frost dates. "
                              "Tick or untick any of them."),
    ("3", "Get your plan", "A bed layout, a dated calendar and a costed shopping list, all updated "
                           "instantly as you change your picks."),
    ("4", "Save and track (optional)", "Make a free account to save gardens, tick off tasks, log harvests "
                                       "and join a community garden."),
]


def welcome_guide() -> None:
    """First-visit guide on the planner. Hidden once dismissed; reopen from the sidebar."""
    if not st.session_state.get("show_guide", True):
        return
    steps = "".join(f'<div class="guide-step"><div class="guide-num">{n}</div><div><b>{html.escape(t)}</b>'
                    f'<div class="muted">{html.escape(d)}</div></div></div>' for n, t, d in GUIDE_STEPS)
    with st.container(border=True, key="welcome_guide"):
        st.markdown(f"#### 👋 New here? Here's how {config.APP_NAME} works")
        st.markdown(f'<div class="guide-grid">{steps}</div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1.2, 1.6, 1])
        c1.markdown("**Just exploring?** Log in at the top right as **demo** (password **garden-demo-2026**) "
                    "to see gardens already in progress.")
        c2.markdown("**Prefer to just talk?** Press **💬 Garden helper** (bottom right) and describe your "
                    "garden in a sentence. It fills in the form for you.")
        if c3.button("Got it, hide this", type="primary", width="stretch", key="hide_guide"):
            st.session_state.show_guide = False
            st.rerun()


def page_tip(key: str, text: str) -> None:
    """One-line 'what this page is for' tip with a dismiss button (remembered for the session)."""
    hidden: set = st.session_state.setdefault("hidden_tips", set())
    if key in hidden:
        return
    with st.container(key=f"tipbox_{key}"):
        st.markdown(f'<div class="page-tip">💡 {text}</div>', unsafe_allow_html=True)
        if st.button("✕", key=f"tip_{key}", help="Hide this tip"):
            hidden.add(key)
            st.rerun()


def step_header(n: int, total: int, title: str, hint: str = "", optional: bool = False) -> None:
    """Numbered section header for the planning form."""
    tag = '<span class="step-optional">Optional</span>' if optional else ""
    st.markdown(f'<div class="step-head"><div class="step-num">{n}</div><div>'
                f'<div class="step-kicker">Step {n} of {total}</div>'
                f'<div class="step-title">{html.escape(title)} {tag}</div>'
                f'<div class="muted">{html.escape(hint)}</div></div></div>', unsafe_allow_html=True)
