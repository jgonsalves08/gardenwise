"""Page: plan a garden (works for guests; logged-in users can save the result)."""

from __future__ import annotations

import uuid
from datetime import date

import streamlit as st

from .. import config, llm, store
from ..agents.intake import run_intake
from ..data import locations, location_for_zip
from ..forms import (AUDIENCE_LABELS, FACINGS, SIZE_PRESETS, SKILL_LABELS, SPACE_LABELS, START_LABELS,
                     SUN_GUESSES, estimate_sun, month_options, start_date_for)
from ..pipeline import Recommendation, assemble, rec_to_json, recommend
from ..agents.site_scout import (JUGLONE_SENSITIVE, MAX_PHOTOS, SURFACE_LABEL, SiteFindings,
                                 prepare_photo, scout)
from ..safety import clean_place, screen_text
from ..schemas import GOAL_LABELS, Constraints
from .. import ui

BUDGET_SLIDER_MAX = 1500


def page() -> None:
    budget: llm.Budget = st.session_state.budget
    ui.hero(f"🌱 {config.APP_NAME}",
            "Tell us your space, skill and goals. Get the right plants, a dated planting calendar, "
            "a bed layout and a costed shopping list — checked against your local frost dates.")

    pf: dict = st.session_state.get("prefill") or {}
    if pf:
        b1, b2 = st.columns([5, 1], vertical_alignment="center")
        if pf.get("from_helper"):
            b1.info("💬 The garden helper filled in this form from your chat. Check it over, change anything, "
                    "then press **Recommend plants**.")
        else:
            b1.info(f"🏷️ New garden at **{pf.get('place') or locations()[pf['location_id']].name}** — location, "
                    f"skill, pets and budget copied from “{pf.get('from_name', 'your garden')}”. "
                    "Change anything you like (for example sun and space for a different spot).")
        if b2.button("Clear", key="clear_prefill"):
            st.session_state.prefill = None
            st.rerun()


    # ---------- intake form ----------
    today = date.today()
    locs = locations()
    loc_ids = sorted(locs, key=lambda i: (locs[i].state, locs[i].name))

    with st.container(border=True):
        st.subheader("1 · About you and your garden")
        st.markdown(f'<div class="region-note">📍 {config.REGION_NOTE}</div>', unsafe_allow_html=True)
        audience = st.segmented_control(
            "👥 Who is this garden for?", list(AUDIENCE_LABELS), format_func=AUDIENCE_LABELS.get,
            default=pf.get("audience", "me"), key="audience")
        audience = audience or "me"
        adults, kids, grade_band, summer_care = 1, 0, None, False
        school_start = school_end = None
        if audience == "community":
            st.info("🏘️ **Community gardens** are planned plot-by-plot by an organizer, with a join "
                    "code for members, a shared work-day calendar and a combined shopping list.")
            st.page_link(st.session_state.pages["community"], label="Go to Community gardens →", icon="🏘️")
            return
        if audience == "household":
            h1, h2, _ = st.columns([1, 1, 2])
            adults = h1.number_input("Adults", 1, 20, pf.get("adults", 2))
            kids = h2.number_input("Kids", 0, 20, pf.get("kids", 0))
            st.caption("Plant counts are sized to how much your household will actually eat "
                       "(kids count as half), as far as your space allows.")
        if audience == "school":
            s1, s2, s3 = st.columns(3)
            grade_band = s1.selectbox("Grade band", ["K-2", "3-5", "6-8", "9-12"], index=1)
            yr = today.year if today.month < 7 else today.year
            school_start = s2.date_input("School year starts", date(yr, 9, 1) if today.month >= 7
                                         else date(yr - 1, 9, 1))
            school_end = s3.date_input("Last day before summer", date(school_start.year + 1, 6, 15))
            summer_care = st.checkbox("Someone (families, staff, a summer program) can water and "
                                      "harvest over the summer", value=False)
            st.caption("Without summer care, the plan favors crops that are harvested while school is in "
                       "session, and each plant comes with a classroom tie-in.")
        a, b = st.columns(2)
        with a:
            loc_id = st.selectbox("📍 Nearest location", loc_ids, format_func=lambda i: locs[i].label,
                                  index=loc_ids.index(pf.get("location_id", "new_haven_ct")))
            zip_code = st.text_input("…or your ZIP code (optional, not saved)", max_chars=5,
                                     placeholder="e.g. 06511")
            if zip_code:
                zl = location_for_zip(zip_code)
                if zl:
                    loc_id = zl.id
                    st.caption(f"Using frost data for **{zl.label}**.")
                else:
                    st.caption("That ZIP is outside the Northeast states GroundWork covers (CT, MA, RI, NH, "
                               "VT, ME, NY, NJ, PA), so the dropdown location is used instead.")
            place_raw = st.text_input(
                "🏷️ Place nickname (optional)", value=pf.get("place", ""), max_chars=40,
                placeholder="e.g. Home, Home – side yard, Lincoln School",
                help="Groups gardens at the same place, so shared things like a compost bin "
                     "aren't suggested twice. Please don't enter a street address.")
            skill = st.radio("🧑‍🌾 Gardening experience", list(SKILL_LABELS),
                             format_func=SKILL_LABELS.get, horizontal=False,
                             index=list(SKILL_LABELS).index(pf.get("skill_level", "beginner")))
            goals = st.pills("🎯 What do you want to grow for? (pick 1–4)", list(GOAL_LABELS),
                             format_func=GOAL_LABELS.get, selection_mode="multi",
                             default=pf.get("goals", ["salad"]))
        with b:
            start_mode = st.radio("📅 When do you want to start?", list(START_LABELS),
                                  format_func=START_LABELS.get, horizontal=True,
                                  index=list(START_LABELS).index(pf.get("start_mode", "now")))
            month_choice = None
            if start_mode == "month":
                month_choice = st.selectbox("Month", month_options(today),
                                            format_func=lambda d: d.strftime("%B %Y"), index=4)
            space_type = st.radio("📐 Where will it grow?", list(SPACE_LABELS),
                                  format_func=SPACE_LABELS.get, horizontal=True,
                                  index=list(SPACE_LABELS).index(pf.get("space_type", "raised_bed")))
            width = length = 4.0
            n_cont = 4
            if space_type in SIZE_PRESETS:
                presets = list(SIZE_PRESETS[space_type]) + ["Custom size"]
                has_size = "width_ft" in pf or "length_ft" in pf
                size = st.selectbox("How much room?", presets, index=len(presets) - 1 if has_size else 1)
                if size == "Custom size":
                    w1, w2 = st.columns(2)
                    width = w1.number_input("Width (ft)", 1.0, 50.0, float(pf.get("width_ft", 4.0)), 0.5)
                    length = w2.number_input("Length (ft)", 1.0, 50.0, float(pf.get("length_ft", 8.0)), 0.5)
                else:
                    width, length = SIZE_PRESETS[space_type][size]
            else:
                n_cont = st.slider("How many pots?", 1, 20,
                                   pf.get("num_containers", 4 if space_type == "containers" else 3))

            st.markdown("**☀️ How sunny is the spot?** *(optional — a rough answer is fine)*")
            s1, s2 = st.columns(2)
            sun_opts = ["—"] + list(SUN_GUESSES)
            pf_sun = {v: k for k, v in SUN_GUESSES.items()}.get(pf.get("sun", ""), "—")
            sun_guess = s1.selectbox("Rough guess", sun_opts, index=sun_opts.index(pf_sun))
            facing = s2.selectbox("…or which way it faces", ["—"] + FACINGS + ["Not sure"])
            blocked = st.checkbox("Trees or buildings block it for part of the day", value=False)
            p1, p2 = st.columns(2)
            has_cats = p1.checkbox("🐈 I have cats", value=pf.get("has_cats", False))
            has_dogs = p2.checkbox("🐕 I have dogs", value=pf.get("has_dogs", False))

        budget_range = st.slider(
            "💵 Budget range for this season (plants, seeds and materials)",
            min_value=0, max_value=BUDGET_SLIDER_MAX, value=pf.get("budget", (100, 400)), step=25, format="$%d",
            help=f"Drag both ends. Setting the top to ${BUDGET_SLIDER_MAX:,} means no upper limit.",
        )
        chat_text = st.text_area(
            "💬 Anything else we should know? (optional)",
            placeholder="e.g. “I want to make hot sauce for my brother, and I killed basil last year.”",
            max_chars=config.MAX_FREE_TEXT_CHARS, height=80,
            help="Plain words are fine. The assistant may ask up to 2 short follow-up questions.",
        )
        scout_updates = photo_section(budget)
        go = st.button("🌱 Recommend plants for me", type="primary", width="stretch")


    def do_recommend(c: Constraints) -> None:
        with st.spinner("Picking plants, checking them against your frost dates, and pricing builds…"):
            try:
                st.session_state.rec = recommend(c, budget)
                st.session_state.chat = None
                st.rerun()  # refresh the usage panel
            except llm.BudgetExceeded as e:
                st.error(f"🛑 {e} This cap protects against runaway costs. Start a new session to continue.")
            except llm.ContentFiltered:
                st.error("🛡️ The AI provider's safety filter blocked this request. Try rephrasing.")
            except llm.LLMError as e:
                st.error(f"The AI step failed: {e}")
            except ValueError as e:
                st.error(str(e))


    def run_chat_turn(chat: dict, user_text: str) -> None:
        """One intake turn. Code screens the text first; the LLM may ask ≤ 2 follow-ups."""
        screen = screen_text(user_text)
        if screen.refused:
            st.session_state.notice = ("error", screen.refusal)
            st.session_state.chat = None
            st.rerun()
        chat["messages"].append(("user", screen.text))
        if screen.injection_flag:
            chat["flags"].append("injection")
        try:
            with st.spinner("Reading your message…"):
                res = run_intake(chat["base"], chat["messages"], chat["used"], budget)
        except llm.BudgetExceeded as e:
            st.error(f"🛑 {e}")
            return
        except llm.LLMError as e:
            st.error(f"The AI step failed: {e}")
            return
        chat["changes"] = res.changes
        chat["constraints"] = res.constraints
        if res.injection_attempt or "injection" in chat["flags"]:
            chat["shield"] = True
        if res.off_topic:
            st.session_state.notice = ("info", "That message didn't seem to be about your garden, "
                                               "so I used your form answers only.")
        if res.follow_up_question and chat["used"] < config.MAX_CHAT_FOLLOWUPS:
            chat["used"] += 1
            chat["messages"].append(("assistant", res.follow_up_question))
            st.session_state.chat = chat
            st.rerun()
        st.session_state.understood = (res.changes, chat.get("shield", False))
        do_recommend(res.constraints)


    if go:
        place, place_err = clean_place(place_raw)
        if place_err:
            st.error(place_err)
        elif not goals:
            st.warning("Pick at least one goal.")
        elif len(goals) > 4:
            st.warning("Pick at most 4 goals so the plan stays focused.")
        else:
            sun, basis = estimate_sun(sun_guess, facing, blocked)
            lo, hi = budget_range
            c = Constraints(
                location_id=loc_id, skill_level=skill, goals=goals, start_mode=start_mode,
                start_date=start_date_for(start_mode, today, month_choice),
                space_type=space_type, width_ft=width, length_ft=length, num_containers=n_cont,
                sun=sun, sun_basis=basis, budget_min=lo,
                budget_max=None if hi >= BUDGET_SLIDER_MAX else hi,
                has_cats=has_cats, has_dogs=has_dogs, place=place,
                audience=audience, adults=adults, kids=kids, grade_band=grade_band,
                school_start=school_start, school_end=school_end, summer_care=summer_care,
            )
            if scout_updates:
                avoid = list(dict.fromkeys(c.avoid_plants + scout_updates.pop("avoid", [])))[:10]
                c = c.model_copy(update=scout_updates | {"avoid_plants": avoid})
            st.session_state.understood = None
            st.session_state.rec = None  # hide the previous plan while we work on the new one
            if chat_text.strip():
                run_chat_turn({"base": c, "messages": [], "used": 0, "flags": []}, chat_text)
            else:
                do_recommend(c)

    notice = st.session_state.pop("notice", None)
    if notice:
        (st.error if notice[0] == "error" else st.info)(notice[1])

    chat = st.session_state.get("chat")
    if chat:
        with st.container(border=True):
            st.markdown("**💬 Quick question before I pick your plants**")
            for role, text in chat["messages"]:
                st.chat_message("user" if role == "user" else "assistant",
                                avatar="🧑‍🌾" if role == "user" else "🌱").write(text)
            answer = st.text_input("Your answer", max_chars=config.MAX_FREE_TEXT_CHARS,
                                   key=f"chat_answer_{chat['used']}")
            b1, b2 = st.columns(2)
            if b1.button("Send", type="primary", width="stretch") and answer.strip():
                run_chat_turn(chat, answer)
            if b2.button("Skip — just recommend", width="stretch"):
                st.session_state.understood = (chat.get("changes", []), chat.get("shield", False))
                do_recommend(chat.get("constraints", chat["base"]))

    results(budget)


def results(budget: llm.Budget) -> None:
    rec: Recommendation | None = st.session_state.get("rec")
    if not rec:
        return
    c = rec.constraints
    loc = locations()[c.location_id]
    prefix = f"r{rec.run_id}"
    picked = {pk.plant_id for pk in rec.picks}
    advised = {bid for bid, _ in rec.build_recs}
    chosen = ui.chosen_from_state(rec, prefix, picked)
    addons = ui.addons_from_state(prefix, advised)
    user = st.session_state.get("user")
    owned = store.builds_at_place(user["id"], c.place) if user else set()
    pf = st.session_state.get("prefill") or {}
    if user and pf.get("group_id"):
        grp = store.get_group(pf["group_id"], user["id"])
        if grp:
            owned |= set(grp["settings"].get("shared_builds", []))
    plan = assemble(rec, chosen, addons, owned=owned)

    st.subheader(f"2 · Your garden in {loc.name}, {loc.state}" + (f" · {c.place}" if c.place else ""))
    ui.location_header(loc, plan.total)
    st.caption(ui.md(f"Sun: **{c.sun}** ({c.sun_basis}) · Start: **{c.start_date:%b %d, %Y}** · "
                     f"Soil: {loc.soil_note}"))
    understood = st.session_state.get("understood")
    if understood:
        changes, shield = understood
        if changes:
            st.caption("💬 From your message: " + ui.md("; ".join(changes)))
        if shield:
            st.info("🛡️ Part of your message looked like instructions to the AI. It was treated as "
                    "plain text and ignored; your plan uses your form answers.")
    ui.verification_panel(rec)

    st.markdown("#### 🌿 Recommended plants — choose what you want to grow")
    st.caption("Untick anything you don't want. The calendar, layout and shopping list update "
               "instantly (no extra AI cost).")
    st.info(rec.summary)
    ui.plant_chooser(rec, plan, prefix, picked)

    if not plan.plants:
        st.warning("Tick at least one plant to see your calendar, layout and shopping list.")
        return
    ui.plan_tabs(rec, plan, prefix, advised)
    save_box(rec, plan.chosen_ids, addons)


def save_box(rec: Recommendation, chosen: list[str], addons: list[str]) -> None:
    st.markdown("---")
    user = st.session_state.get("user")
    if not user:
        st.info("💾 **Want to keep this plan?** Log in or create a free account in the sidebar to "
                "save it, tick off tasks as you go, and see what's due each week. Totally optional.")
        return
    saved = st.session_state.get("saved_run")
    if saved == rec.run_id:
        st.success("Saved to **My gardens**.")
        st.page_link(st.session_state.pages["gardens"], label="Open My gardens →", icon="🌿")
        return
    loc = locations()[rec.constraints.location_id]
    with st.form("save_form", border=True):
        st.markdown("**💾 Save this plan to track it**")
        default_name = (f"{rec.constraints.place} garden" if rec.constraints.place
                        else f"{loc.name} garden") + f" {rec.constraints.start_date.year}"
        name = st.text_input("Garden name", value=default_name,
                             max_chars=60)
        if st.form_submit_button("Save to My gardens", type="primary"):
            pf = st.session_state.get("prefill") or {}
            if pf.get("group_id") and store.get_group(pf["group_id"], user["id"]):
                store.save_garden(user["id"], name, rec_to_json(rec), chosen, addons,
                                  group_id=pf["group_id"], plot_label=user["username"],
                                  assigned_to=user["username"])
            else:
                store.save_garden(user["id"], name, rec_to_json(rec), chosen, addons)
            st.session_state.saved_run = rec.run_id
            st.session_state.prefill = None
            st.rerun()


def photo_section(budget: llm.Budget) -> dict:
    """Optional photos → Site Scout → the user confirms each finding before it changes the plan."""
    found = st.session_state.get("scout")
    with st.expander("📷 Add photos of the spot (optional: helps with sun, surface and hazards)",
                     expanded=bool(found)):
        st.caption("Up to 3 photos. Location data (GPS) and all other metadata are removed before anything "
                   "is sent, and photos are never saved. Nothing changes your plan until you confirm it.")
        files = st.file_uploader("Photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
                                 label_visibility="collapsed", key="scout_files")
        if files and len(files) > MAX_PHOTOS:
            st.caption(f"Using the first {MAX_PHOTOS} photos.")
        if files and st.button("🔍 Scout my photos", key="scout_go"):
            prepared, errors = [], []
            for f in files[:MAX_PHOTOS]:
                try:
                    prepared.append(prepare_photo(f.getvalue()))
                except ValueError as e:
                    errors.append(f"{f.name}: {e}")
            for e in errors:
                st.error(e)
            if prepared:
                with st.spinner("Looking at your photos…"):
                    try:
                        res = scout(prepared, budget)
                        st.session_state.scout = {"id": uuid.uuid4().hex[:6], "f": res.model_dump(),
                                                  "n": len(prepared),
                                                  "gps": sum(p.had_location for p in prepared)}
                        st.rerun()
                    except llm.BudgetExceeded as e:
                        st.error(f"🛑 {e}")
                    except llm.ContentFiltered:
                        st.error("🛡️ The AI provider's safety filter blocked these photos.")
                    except llm.LLMError as e:
                        st.error(f"Photo check failed: {e}")
        if not found:
            return {}
        f = SiteFindings.model_validate(found["f"])
        sid = found["id"]
        if found["gps"]:
            st.caption(f"🔒 Removed location data from {found['gps']} photo(s).")
        if f.text_in_image:
            st.info("🛡️ A photo contained written text. It was treated as part of the picture, not as "
                    "instructions.")
        if not f.usable:
            st.warning(ui.md(f.summary or "These photos don't seem to show a place to garden."))
            return {}
        st.markdown(f"**What the Site Scout sees:** {ui.md(f.summary)}")
        updates: dict = {"site_summary": f.summary}
        if f.sun != "unclear":
            if st.checkbox(ui.md(f"☀️ Use **{f.sun} sun** ({f.sun_confidence} confidence: {f.sun_evidence})"),
                           value=f.sun_confidence != "low", key=f"sc_sun_{sid}"):
                updates |= {"sun": f.sun, "sun_basis": f"estimated from your photo ({f.sun_confidence} confidence)"}
        if f.suggested_space != "unclear":
            if st.checkbox(ui.md(f"📐 Plan for **{f.suggested_space.replace('_', ' ')}** "
                                 f"(surface looks like {SURFACE_LABEL[f.surface]}"
                                 + (f"; {f.size_hint}" if f.size_hint else "") + ")"),
                           value=False, key=f"sc_space_{sid}",
                           help="Overrides “Where will it grow?” above. Size still comes from the form."):
                updates["space_type"] = f.suggested_space
        hazards = []
        for h in f.hazards:
            if st.checkbox(ui.md(f"⚠️ {h.kind.replace('_', ' ')}: {h.evidence.rstrip('. ')}. Yes, that's right"),
                           value=True, key=f"sc_hz_{sid}_{h.kind}"):
                hazards.append(h.kind)
        updates["site_hazards"] = hazards
        if "black_walnut" in hazards:
            updates["avoid"] = JUGLONE_SENSITIVE
        if st.button("Clear photo findings", key=f"sc_clear_{sid}", type="tertiary"):
            st.session_state.scout = None
            st.rerun()
        return updates
