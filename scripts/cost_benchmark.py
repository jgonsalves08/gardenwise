"""Cost benchmark: 10 garden plans run "cold" (prompt cache bypassed) vs "warm" (cache working).

Run from the repo folder:   python scripts/cost_benchmark.py
Writes results/cost_runs.csv (one row per plan) and results/cost_summary.md (for the report).

Cold runs prepend a unique marker to every agent's instructions, so the provider can't reuse a
cached prefix. Warm runs use the normal prompts after one priming plan. Quality is checked the
same way for both: did the code verifier pass the AI's picks on the first try?
"""

from __future__ import annotations

import csv
import statistics as stats
import sys
import time
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from garden import config, llm  # noqa: E402
from garden.agents.helper import run_helper  # noqa: E402
from garden.agents.intake import run_intake  # noqa: E402
from garden.pipeline import recommend  # noqa: E402
from garden.schemas import Constraints  # noqa: E402

S = date(2027, 3, 1)
PROFILES = [  # (name, constraints, optional chat note) — spread across the US and user types
    ("Beginner salad bed, New Haven CT", dict(location_id="new_haven_ct", goals=["salad"], space_type="raised_bed"), ""),
    ("Salsa household of 4, Atlanta GA", dict(location_id="atlanta_ga", goals=["salsa", "kids"], space_type="in_ground",
                                            width_ft=10, length_ft=10, audience="household", adults=2, kids=2,
                                            skill_level="intermediate"), ""),
    ("Balcony herbs, Chicago IL", dict(location_id="chicago_il", goals=["pesto_herbs"], space_type="containers",
                                     num_containers=5, sun="part"), "I have a cat that chews plants."),
    ("School garden gr. 3-5, Minneapolis MN", dict(location_id="minneapolis_mn", goals=["salad", "kids"],
                                                  space_type="raised_bed", width_ft=8, length_ft=8, audience="school",
                                                  grade_band="3-5", school_start=date(2026, 9, 2),
                                                  school_end=date(2027, 6, 11)), ""),
    ("Pollinator strip, Denver CO", dict(location_id="denver_co", goals=["pollinator", "cut_flowers"],
                                       space_type="in_ground", width_ft=5, length_ft=12), ""),
    ("Pickling bed, Seattle WA", dict(location_id="seattle_wa", goals=["pickling"], space_type="raised_bed",
                                    skill_level="intermediate"), "We love dill pickles."),
    ("Three Sisters, Kansas City MO", dict(location_id="kansas_city_mo", goals=["three_sisters"],
                                         space_type="in_ground", width_ft=15, length_ft=20,
                                         skill_level="experienced"), ""),
    ("Shady yard greens, Portland OR", dict(location_id="portland_or", goals=["salad"], space_type="raised_bed",
                                          sun="shade"), ""),
    ("Herbal tea garden, Nashville TN", dict(location_id="nashville_tn", goals=["herbal_tea"],
                                           space_type="containers", num_containers=6), ""),
    ("Kids' garden, Salt Lake City UT", dict(location_id="salt_lake_city_ut", goals=["kids", "salad"],
                                           space_type="raised_bed", has_dogs=True), "My kids are 4 and 7."),
]
HELPER_QUESTIONS = ["When is my last frost in Boston?", "Which herbs grow in shade?",
                    "Can I grow tomatoes in a pot?", "What's a good first crop for kids?",
                    "Is basil safe for dogs?"]


def constraints(kw: dict) -> Constraints:
    base = dict(skill_level="beginner", start_mode="best_time", start_date=S, sun="full", budget_min=50,
                budget_max=400)
    return Constraints(**(base | kw))


def one_plan(name: str, kw: dict, note: str) -> dict:
    b = llm.Budget(session_id=f"bench-{uuid.uuid4().hex[:6]}", token_cap=200_000, call_cap=50)
    t0 = time.perf_counter()
    c = constraints(kw)
    if note:
        c = run_intake(c, [("user", note)], config.MAX_CHAT_FOLLOWUPS, b).constraints
    rec = recommend(c, b)
    return {"profile": name, "calls": len(b.calls),
            "input_tokens": sum(x.input_tokens for x in b.calls),
            "cached_tokens": sum(x.cached_tokens for x in b.calls),
            "output_tokens": sum(x.output_tokens for x in b.calls),
            "cost_usd": round(b.cost_usd, 6), "seconds": round(time.perf_counter() - t0, 2),
            "verifier_first_try": bool(rec.report and rec.report.attempts == 1),
            "verifier_ok": bool(rec.report and (rec.report.ok or rec.report.repaired)), "picks": len(rec.picks)}


def helper_costs() -> list[float]:
    b = llm.Budget(session_id="bench-helper", token_cap=200_000, call_cap=50)
    out = []
    for q in HELPER_QUESTIONS:
        n = len(b.calls)
        run_helper([], q, None, b)
        out.append(sum(x.cost_usd for x in b.calls[n:]))
    return out


def main() -> None:
    rows = []
    print("Cold runs (cache bypassed)…")
    for name, kw, note in PROFILES:
        llm.INSTRUCTION_PREFIX = f"[benchmark run {uuid.uuid4().hex}]\n"
        rows.append({"mode": "cold"} | one_plan(name, kw, note))
        print(f"  {name}: ${rows[-1]['cost_usd']:.5f}")
    llm.INSTRUCTION_PREFIX = ""
    one_plan(*PROFILES[0])   # prime the cache
    print("Warm runs (cache working)…")
    for name, kw, note in PROFILES:
        rows.append({"mode": "warm"} | one_plan(name, kw, note))
        print(f"  {name}: ${rows[-1]['cost_usd']:.5f}")
    helper = helper_costs()

    out = config.RESULTS_DIR
    out.mkdir(exist_ok=True)
    with (out / "cost_runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def agg(mode):
        r = [x for x in rows if x["mode"] == mode]
        return {k: stats.mean(x[k] for x in r) for k in ("calls", "input_tokens", "cached_tokens",
                                                          "output_tokens", "cost_usd", "seconds")} | {
            "first_try": sum(x["verifier_first_try"] for x in r) / len(r),
            "ok": sum(x["verifier_ok"] for x in r) / len(r)}
    cold, warm = agg("cold"), agg("warm")
    h = stats.mean(helper)
    # Usage assumptions for scaling (stated in the report): an active user makes 2 plans and asks the
    # helper 15 questions per month; 1 in 4 plans includes a photo check (~$0.0002).
    per_user = 2 * warm["cost_usd"] + 15 * h + 0.5 * 0.0002
    md = ["# Cost benchmark", "", f"Run {date.today():%B %d, %Y} with `{config.MODEL_NAME}` "
          f"(${config.PRICES['gpt-6-luna']['input']}/1M input, ${config.PRICES['gpt-6-luna']['cached_input']}/1M "
          f"cached, ${config.PRICES['gpt-6-luna']['output']}/1M output). 10 plans across 10 states.", "",
          "| | Cold (cache bypassed) | Warm (cache working) |", "|---|---|---|",
          f"| AI calls per plan | {cold['calls']:.1f} | {warm['calls']:.1f} |",
          f"| Input tokens per plan | {cold['input_tokens']:,.0f} | {warm['input_tokens']:,.0f} |",
          f"| …of which cached | {cold['cached_tokens']:,.0f} | {warm['cached_tokens']:,.0f} "
          f"({warm['cached_tokens'] / max(1, warm['input_tokens']):.0%}) |",
          f"| Output tokens per plan | {cold['output_tokens']:,.0f} | {warm['output_tokens']:,.0f} |",
          f"| **Cost per plan** | **${cold['cost_usd']:.5f}** | **${warm['cost_usd']:.5f}** |",
          f"| Seconds per plan | {cold['seconds']:.1f} | {warm['seconds']:.1f} |",
          f"| Verifier passed on first try | {cold['first_try']:.0%} | {warm['first_try']:.0%} |",
          f"| Final plan passed verification | {cold['ok']:.0%} | {warm['ok']:.0%} |", "",
          f"Caching saved **{1 - warm['cost_usd'] / cold['cost_usd']:.0%}** per plan. "
          "Quality is measured the same way in both modes (the code verifier).", "",
          f"Garden helper: **${h:.5f} per message** on average ({len(helper)} questions).", "",
          "## Per user and at scale", "",
          "Assumption: an active user makes 2 plans and asks the helper 15 questions a month; "
          "1 in 4 plans adds a photo check (~$0.0002).", "",
          "| Users | AI cost per month | AI cost per year |", "|---|---|---|",
          f"| 1 | ${per_user:.4f} | ${per_user * 12:.3f} |",
          f"| 100 | ${per_user * 100:.2f} | ${per_user * 1200:.2f} |",
          f"| 10,000 | ${per_user * 10_000:,.2f} | ${per_user * 120_000:,.2f} |", "",
          "Community gardens: planning a 40-plot garden from a CSV is about "
          f"40 × ${warm['cost_usd']:.5f} ≈ **${40 * warm['cost_usd']:.3f}**."]
    (out / "cost_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
