"""Community gardens (CODE + the existing agents): plan many plots at once and roll them up.

An organizer uploads a member sign-up CSV. Each row becomes its own plot plan (Intake if the row
has notes → Selector → Verifier → Build advisor), all sharing the same long cached prompt
prefix, so planning a 20-plot garden costs on the order of two cents in AI calls.
Shared builds (compost bin, rain barrel) are bought once and split across plots, and seed
packets are pooled (one packet covers several small plots).
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import config, llm, store
from .agents.build import compute_build
from .agents.intake import run_intake
from .data import locations, plants
from .pipeline import Plan, assemble, rec_from_json, rec_to_json, recommend
from .safety import screen_text
from .schemas import GOAL_LABELS, Constraints, MaterialLine

MAX_CSV_BYTES = 100_000
MAX_ROWS = 40
PLOTS_PER_SEED_PACKET = 3          # one packet of lettuce seed easily covers ~3 small plots
EST_COST_PER_PLOT = 0.0008         # measured: selector + build advisor ≈ $0.0006–0.0008
EST_COST_PER_NOTE = 0.0002         # intake call when a row has notes
CSV_COLUMNS = ["plot", "gardener", "skill", "goals", "sun", "width_ft", "length_ft", "notes"]
TEMPLATE_CSV = (
    "plot,gardener,skill,goals,sun,width_ft,length_ft,notes\n"
    "1,Maria,beginner,salsa; salad,full,4,8,First garden ever; has a dog\n"
    "2,Dev,intermediate,pickling,full,4,8,\n"
    "3,Ana & kids,beginner,kids; pollinator,part,4,8,Kids are 5 and 8\n"
)

_GOAL_ALIASES = {g: g for g in GOAL_LABELS} | {v.lower(): k for k, v in GOAL_LABELS.items()} | {
    "pesto": "pesto_herbs", "herbs": "pesto_herbs", "flowers": "cut_flowers", "tea": "herbal_tea",
    "three sisters": "three_sisters", "bees": "pollinator", "butterflies": "pollinator", "kid": "kids"}


@dataclass
class CsvRow:
    plot: str
    gardener: str
    skill: str
    goals: list[str]
    sun: str
    width_ft: float
    length_ft: float
    notes: str
    warnings: list[str] = field(default_factory=list)


def _cell(text: str) -> str:
    """Neutralize spreadsheet formula injection (=, +, -, @) and trim."""
    t = (text or "").strip()
    return "'" + t if t[:1] in ("=", "+", "-", "@") else t


def parse_member_csv(raw: bytes, default_w: float, default_l: float) -> tuple[list[CsvRow], list[str]]:
    errors: list[str] = []
    if len(raw) > MAX_CSV_BYTES:
        return [], [f"File is too large (max {MAX_CSV_BYTES // 1000} KB)."]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["Couldn't read the file. Save it as CSV (UTF-8)."]
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "plot" not in headers:
        return [], ["The CSV needs at least a 'plot' column. Download the template to see the format."]
    rows: list[CsvRow] = []
    for i, raw_row in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            errors.append(f"Only the first {MAX_ROWS} plots were read (limit per import).")
            break
        r = {k.strip().lower(): (v or "") for k, v in raw_row.items() if k}
        if not any(v.strip() for v in r.values()):
            continue
        warn = []
        skill = r.get("skill", "").strip().lower() or "beginner"
        if skill not in ("beginner", "intermediate", "experienced"):
            warn.append(f"skill '{skill}' → beginner")
            skill = "beginner"
        goals = []
        for g in r.get("goals", "").replace(",", ";").split(";"):
            g = g.strip().lower()
            if g and g in _GOAL_ALIASES and _GOAL_ALIASES[g] not in goals:
                goals.append(_GOAL_ALIASES[g])
            elif g:
                warn.append(f"unknown goal '{g}' skipped")
        if not goals:
            goals = ["salad"]
            warn.append("no goals → salad")
        sun = r.get("sun", "").strip().lower() or "unknown"
        if sun not in ("full", "part", "shade", "unknown"):
            warn.append(f"sun '{sun}' → unknown")
            sun = "unknown"

        def num(key: str, default: float) -> float:
            try:
                v = float(r.get(key, "") or default)
                return min(max(v, 1.0), 50.0)
            except ValueError:
                warn.append(f"{key} not a number → {default:g}")
                return default

        rows.append(CsvRow(
            plot=_cell(r.get("plot", ""))[:20] or str(i - 1),
            gardener=_cell(r.get("gardener", ""))[:30],
            skill=skill, goals=goals[:4], sun=sun,
            width_ft=num("width_ft", default_w), length_ft=num("length_ft", default_l),
            notes=r.get("notes", "").strip()[:config.MAX_FREE_TEXT_CHARS], warnings=warn))
    if not rows and not errors:
        errors.append("No plots found in the file.")
    return rows, errors


def estimate_cost(rows: list[CsvRow]) -> float:
    return len(rows) * EST_COST_PER_PLOT + sum(bool(r.notes) for r in rows) * EST_COST_PER_NOTE


def base_constraints(settings: dict) -> dict:
    return dict(location_id=settings["location_id"], place=settings.get("place", ""),
                start_date=date.fromisoformat(settings["start_date"]), start_mode="month",
                space_type=settings.get("space_type", "raised_bed"),
                budget_min=0, budget_max=settings.get("plot_budget") or None, audience="community",
                beds_ready=settings.get("beds_ready", True))


def plan_rows(group: dict, organizer_id: int, rows: list[CsvRow], progress=None) -> tuple[list[dict], llm.Budget]:
    """Plan every row. A dedicated budget caps the whole batch (loop + overspend protection)."""
    store.require_role(group["id"], organizer_id, "admin")  # organizer_id here = the user running the import
    owner_id = group["organizer_id"]  # imported plots belong to the organizer until a member claims one
    settings = group["settings"]
    batch_budget = llm.Budget(session_id=f"group{group['id']}",
                              token_cap=max(20_000, len(rows) * 12_000), call_cap=len(rows) * 5 + 2)
    shared = set(settings.get("shared_builds", []))
    results = []
    for n, row in enumerate(rows, start=1):
        if progress:
            progress(n, len(rows), row)
        out = {"plot": row.plot, "gardener": row.gardener, "ok": False, "note": "; ".join(row.warnings)}
        try:
            c = Constraints(**base_constraints(settings), skill_level=row.skill, goals=row.goals,
                            sun=row.sun, sun_basis="from the sign-up sheet",
                            width_ft=row.width_ft, length_ft=row.length_ft)
            if row.notes:
                screen = screen_text(row.notes)
                if screen.refused:
                    out["note"] += "; notes ignored (off-limits topic)"
                else:
                    # No follow-up questions in a batch: pass follow_ups_used = max.
                    res = run_intake(c, [("user", screen.text)], config.MAX_CHAT_FOLLOWUPS, batch_budget)
                    c = res.constraints
                    if res.injection_attempt or screen.injection_flag:
                        out["note"] += "; notes looked like instructions to the AI and were ignored"
            rec = recommend(c, batch_budget)
            addons = [b for b, _ in rec.build_recs if b not in shared]
            label = f"Plot {row.plot}" + (f" – {row.gardener}" if row.gardener else "")
            store.save_garden(owner_id, label, rec_to_json(rec), [p.plant_id for p in rec.picks],
                              addons, group_id=group["id"], plot_label=row.plot)
            out["ok"] = True
            out["plants"] = ", ".join(plants()[p.plant_id].name for p in rec.picks)
        except llm.BudgetExceeded as e:
            out["note"] += f"; stopped: {e}"
            results.append(out)
            break
        except (llm.LLMError, ValueError) as e:
            out["note"] += f"; failed: {str(e)[:120]}"
        results.append(out)
    return results, batch_budget


# ---------- roll-ups ----------
@dataclass
class PlotView:
    garden: dict
    plan: Plan
    claimed_by: str


def plot_views(group: dict) -> list[PlotView]:
    shared = set(group["settings"].get("shared_builds", []))
    out = []
    for g in store.group_plots(group["id"]):
        rec = rec_from_json(g["rec"])
        plan = assemble(rec, g["chosen"], [a for a in g["addons"] if a not in shared], owned=shared)
        out.append(PlotView(garden=g, plan=plan, claimed_by=g["assigned_to"]))
    return out


def work_days(group: dict, today: date | None = None, months: int = 12) -> list[date]:
    """First Saturday of each growing-season month (from ~a month before last frost to first frost)."""
    today = today or date.today()
    loc = locations()[group["settings"]["location_id"]]
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        first = date(y, m, 1)
        sat = first + timedelta(days=(5 - first.weekday()) % 7)
        season_start = loc.last_frost_on(y) - timedelta(days=30)
        if season_start <= sat <= loc.first_frost_on(y) and sat >= today - timedelta(days=7):
            out.append(sat)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def shared_build_plans(group: dict):
    s = group["settings"]
    c = Constraints(**base_constraints(s), skill_level="experienced", goals=["salad"],
                    width_ft=10, length_ft=10)
    return [compute_build(b, c, [], plants()) for b in s.get("shared_builds", [])]


@dataclass
class Rollup:
    combined: list[dict]                 # pooled plant/seed lines
    shared_builds: list                  # BuildPlan list, bought once
    per_plot: list[dict]                 # plot, own_cost, shared_share, total
    separate_total: float                # if every plot bought its own seeds + shared builds
    pooled_total: float


def rollup(group: dict, views: list[PlotView]) -> Rollup:
    lines: dict[str, dict] = {}
    for v in views:
        for m in v.plan.plant_costs:
            d = lines.setdefault(m.item, {"item": m.item, "unit_price": m.unit_price, "qty": 0,
                                          "plots": 0, "links": m.store_links})
            d["qty"] += m.qty
            d["plots"] += 1
    combined = []
    for d in lines.values():
        pooled_qty = math.ceil(d["plots"] / PLOTS_PER_SEED_PACKET) if "seed packet" in d["item"] else d["qty"]
        combined.append(d | {"pooled_qty": pooled_qty, "pooled_cost": round(pooled_qty * d["unit_price"], 2),
                             "separate_cost": round(d["qty"] * d["unit_price"], 2)})
    combined.sort(key=lambda d: -d["pooled_cost"])
    shared = shared_build_plans(group)
    shared_total = sum(b.total_usd for b in shared)
    n = max(1, len(views))
    pooled_plants = sum(d["pooled_cost"] for d in combined)
    separate_plants = sum(d["separate_cost"] for d in combined)
    per_plot = []
    for v in views:
        builds = v.plan.build_total
        plant_share = v.plan.plant_total * (pooled_plants / separate_plants if separate_plants else 1)
        per_plot.append({"plot": v.garden["plot_label"] or v.garden["name"], "name": v.garden["name"],
                         "own_builds": round(builds, 2), "plants": round(plant_share, 2),
                         "shared_share": round(shared_total / n, 2),
                         "total": round(builds + plant_share + shared_total / n, 2)})
    own_builds = sum(v.plan.build_total for v in views)
    return Rollup(combined=combined, shared_builds=shared, per_plot=per_plot,
                  separate_total=round(own_builds + separate_plants + shared_total * n, 2),
                  pooled_total=round(own_builds + pooled_plants + shared_total, 2))


# ---------- garden-wide stats (My dashboard) ----------
@dataclass
class GroupStats:
    total_lb: float
    donated_lb: float
    harvests: int
    plots: int
    plots_due: int              # plots with at least one crop whose harvest window has started
    plots_reached: int          # ...of those, plots with a logged or ticked harvest
    workdays_done: int
    workdays_past: int
    by_month: list[dict]        # [{"Month": "2026-07", "lb": 3.5}]
    per_plot: list[dict] | None  # admins/organizer only; None for members


def group_stats(group: dict, user_id: int, today: date | None = None, harvest_filter=None,
                in_range=None) -> GroupStats:
    """Totals for everyone in the group; per-plot detail only for admins (checked here, not just in the UI)."""
    from .pipeline import task_key

    today = today or date.today()
    role = store.role_in(group["id"], user_id)
    if role is None:
        raise PermissionError("Not a member of this garden.")
    is_admin = role in ("admin", "organizer")
    total = donated = 0.0
    n_logs = due = reached = 0
    months: dict[str, float] = defaultdict(float)
    per_plot = []
    for v in plot_views(group):
        g = v.garden
        all_logs = store.list_harvests(g["id"])
        logs = [h for h in all_logs if harvest_filter(h)] if harvest_filter else all_logs
        done = store.get_checks(g["id"])
        lb = sum(h["est_lb"] for h in logs)
        don = sum(h["est_lb"] for h in logs if h["donated"])
        total, donated, n_logs = total + lb, donated + don, n_logs + len(logs)
        for h in logs:
            months[h["picked_on"][:7]] += h["est_lb"]
        is_due = any(s.harvest_start <= today and (in_range is None or in_range(s.harvest_start))
                     for s in v.plan.schedules)
        got = bool(all_logs) or any(t.kind == "harvest" and task_key(t) in done for t in v.plan.tasks)
        due += is_due
        reached += is_due and got
        if is_admin:
            n_done = sum(task_key(t) in done for t in v.plan.tasks)
            per_plot.append({"Plot": g["name"], "Gardener": v.claimed_by or "unclaimed",
                             "Approx. lb": f"{lb:,.1f}", "Donated lb": f"{don:,.1f}",
                             "Reached harvest": "✅ yes" if got else ("❌ not yet" if is_due else "— not due"),
                             "Tasks done (%)": round(100 * n_done / max(1, len(v.plan.tasks)))})
    state = store.group_task_state(group["id"])
    past_days = [d for d in work_days(group, today - timedelta(days=365), months=13) if d < today]
    wd_done = sum(bool(state.get(f"workday|{d.isoformat()}", {}).get("done_at")) for d in past_days)
    return GroupStats(total_lb=round(total, 2), donated_lb=round(donated, 2), harvests=n_logs,
                      plots=len(per_plot) if is_admin else len(store.group_plots(group["id"])),
                      plots_due=due, plots_reached=reached, workdays_done=wd_done,
                      workdays_past=len(past_days),
                      by_month=[{"Month": m, "lb": round(lb, 2)} for m, lb in sorted(months.items())],
                      per_plot=per_plot if is_admin else None)
