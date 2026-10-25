"""Gardenwise vs. a plain one-prompt plan from the same model, scored by the same code checks.

Run from the repo folder:   python scripts/compare_baseline.py
Writes results/baseline_runs.csv and results/baseline_summary.md.

The baseline is what someone gets by asking the model directly ("make me a garden plan for…"),
with no plant database, no frost data and no verifier. Both are scored by the same rules:
  - plant is a real, identifiable plant in our database (so its facts can be checked)
  - grows in the location's USDA zone; suits the sun, skill level and space type
  - planting date is not before the last frost for frost-tender crops
  - frost-tender crops are ready before the first fall frost
  - pets: toxic plants are flagged when the household has pets
  - lead: a soil-test warning is given when food is grown in ground soil
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cost_benchmark import PROFILES, constraints  # noqa: E402
from garden import config, llm  # noqa: E402
from garden.data import locations, plants  # noqa: E402
from garden.pipeline import assemble, recommend  # noqa: E402
from garden.schemas import SKILL_RANK, GOAL_LABELS  # noqa: E402
from garden.space import suits_space  # noqa: E402

BASELINE_PROMPT = "You are a helpful gardening assistant. Make a practical garden plan for this person."


class BPlant(BaseModel):
    name: str
    plant_outdoors_date: str = Field(description="YYYY-MM-DD")
    first_harvest_date: str = Field(description="YYYY-MM-DD")


class BPlan(BaseModel):
    plants: list[BPlant]
    estimated_cost_usd: float
    warnings: list[str]


def describe(c) -> str:
    loc = locations()[c.location_id]
    who = {"me": "an individual", "household": f"a household of {c.adults} adults and {c.kids} kids",
           "school": f"a school garden for grades {c.grade_band} (school year {c.school_start} to {c.school_end})",
           "community": "a community garden plot"}[c.audience]
    space = (f"{c.num_containers} containers" if c.space_type in ("containers", "windowsill")
             else f"a {c.width_ft:g} x {c.length_ft:g} ft {c.space_type.replace('_', ' ')}")
    pets = [p for p, h in (("cats", c.has_cats), ("dogs", c.has_dogs)) if h]
    return (f"Location: {loc.name}, {loc.state}. Garden for {who}. Skill: {c.skill_level}. Goals: "
            f"{', '.join(GOAL_LABELS[g] for g in c.goals)}. Space: {space}. Sun: {c.sun}. "
            f"Pets: {', '.join(pets) or 'none'}. Budget: up to ${c.budget_max}. Starting {c.start_date:%B %Y}. "
            "List 3–6 plants with planting-out and first-harvest dates, an estimated total cost, and any warnings.")


def match(name: str):
    n = re.sub(r"[^a-z ]", " ", name.lower())
    best = None
    for p in plants().values():
        key = re.sub(r"\(.*?\)", "", p.name.lower()).strip()
        words = [w for w in re.findall(r"[a-z]+", key) if len(w) > 2]
        if key in n or (words and all(w in n for w in words)):
            if best is None or len(key) > len(re.sub(r"\(.*?\)", "", best.name.lower())):
                best = p
    return best


def score(c, items) -> dict:
    """items: [(plant or None, plant_out date or None, harvest date or None)], warnings text."""
    loc = locations()[c.location_id]
    rows, problems = [], []
    for p, out, harv in items:
        if p is None:
            problems.append("plant not identifiable")
            rows.append(False)
            continue
        ok = True
        if not (p.zone_min <= loc.zone_num <= p.zone_max):
            problems.append(f"{p.name}: wrong zone"); ok = False
        if c.sun not in ("unknown",) and c.sun not in p.sun:
            problems.append(f"{p.name}: needs more sun"); ok = False
        if SKILL_RANK[p.difficulty] > SKILL_RANK[c.skill_level]:
            problems.append(f"{p.name}: too hard for skill level"); ok = False
        if not suits_space(p, c):
            problems.append(f"{p.name}: doesn't suit the space"); ok = False
        if out and p.frost_tender and out < loc.last_frost_on(out.year):
            problems.append(f"{p.name}: planted before last frost ({out:%b %d})"); ok = False
        if harv and p.frost_tender and harv > loc.first_frost_on(harv.year):
            problems.append(f"{p.name}: harvest after first frost"); ok = False
        rows.append(ok)
    return {"plants": len(items), "plants_ok": sum(rows), "problems": problems}


def parse_date(s: str):
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def main() -> None:
    out_rows = []
    for name, kw, _note in PROFILES:
        c = constraints(kw)
        pets = [k for k, h in (("cats", c.has_cats), ("dogs", c.has_dogs)) if h]
        ground_food = c.space_type in ("in_ground", "raised_bed")
        # --- baseline: one plain prompt
        b = llm.Budget(session_id="baseline", token_cap=100_000, call_cap=10)
        bp = llm.call_structured(agent="baseline", instructions=BASELINE_PROMPT, user_input=describe(c),
                                 schema=BPlan, budget=b)
        bitems = [(match(x.name), parse_date(x.plant_outdoors_date), parse_date(x.first_harvest_date))
                  for x in bp.plants]
        bs = score(c, bitems)
        warn = " ".join(bp.warnings).lower()
        b_pet_ok = not pets or not any(p and any(getattr(p.pet_toxic, k) for k in pets) for p, _, _ in bitems) \
            or any(w in warn for w in ("toxic", "pet", "cat", "dog"))
        b_lead_ok = not ground_food or "lead" in warn
        # --- Gardenwise
        g = llm.Budget(session_id="gardenwise", token_cap=100_000, call_cap=20)
        rec = recommend(c, g)
        plan = assemble(rec, [p.plant_id for p in rec.picks], [])
        gitems = [(plants()[s.plant_id], s.plant_out, s.harvest_start) for s in plan.schedules]
        gs = score(c, gitems)
        gw = " ".join(plan.warnings).lower()
        g_pet_ok = not pets or not any(any(getattr(p.pet_toxic, k) for k in pets) for p, _, _ in gitems) or "toxic" in gw
        g_lead_ok = not ground_food or "lead" in gw
        for who, s, pet_ok, lead_ok, cost in (("Plain prompt", bs, b_pet_ok, b_lead_ok, b.cost_usd),
                                              ("Gardenwise", gs, g_pet_ok, g_lead_ok, g.cost_usd)):
            out_rows.append({"profile": name, "system": who, "plants": s["plants"], "plants_ok": s["plants_ok"],
                             "pet_warning_ok": pet_ok, "lead_warning_ok": lead_ok, "ai_cost_usd": round(cost, 6),
                             "problems": "; ".join(s["problems"])})
        print(f"{name}: baseline {bs['plants_ok']}/{bs['plants']} ok · Gardenwise {gs['plants_ok']}/{gs['plants']} ok")

    res = config.RESULTS_DIR
    res.mkdir(exist_ok=True)
    with (res / "baseline_runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)

    def summ(system):
        r = [x for x in out_rows if x["system"] == system]
        n_pl = sum(x["plants"] for x in r)
        return {"plans": len(r), "plants": n_pl, "ok": sum(x["plants_ok"] for x in r),
                "clean_plans": sum(x["plants_ok"] == x["plants"] and x["pet_warning_ok"] and x["lead_warning_ok"]
                                   for x in r),
                "pet": sum(x["pet_warning_ok"] for x in r), "lead": sum(x["lead_warning_ok"] for x in r),
                "cost": sum(x["ai_cost_usd"] for x in r) / len(r)}
    b, g = summ("Plain prompt"), summ("Gardenwise")
    from collections import Counter
    kinds = Counter(re.sub(r"^[^:]+: ", "", p).split(" (")[0] for x in out_rows if x["system"] == "Plain prompt"
                    for p in x["problems"].split("; ") if p)
    md = ["# Gardenwise vs. a plain prompt", "",
          f"Same model (`{config.MODEL_NAME}`), same 10 gardener profiles across 10 states, scored by the same code "
          "checks (zone, sun, skill, space, planting date vs. last frost, harvest vs. first frost, pet and lead "
          "warnings).", "",
          "| | Plain prompt | Gardenwise |", "|---|---|---|",
          f"| Plants that passed every check | {b['ok']}/{b['plants']} ({b['ok'] / max(1, b['plants']):.0%}) | "
          f"{g['ok']}/{g['plants']} ({g['ok'] / max(1, g['plants']):.0%}) |",
          f"| Plans with zero problems | {b['clean_plans']}/10 | {g['clean_plans']}/10 |",
          f"| Pet-toxicity warning when needed | {b['pet']}/10 | {g['pet']}/10 |",
          f"| Lead-in-soil warning for in-ground food | {b['lead']}/10 | {g['lead']}/10 |",
          f"| AI cost per plan | ${b['cost']:.5f} | ${g['cost']:.5f} |", "",
          "Most common plain-prompt problems: " + (", ".join(f"{k} ({v})" for k, v in kinds.most_common(6)) or "none") + ".",
          "", "Caveat: the checks are Gardenwise's own rules applied to both systems; plants the plain prompt "
              "named that aren't in our database can't be verified and count as problems."]
    (res / "baseline_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
