"""Reasoning-effort A/B test: does running the AI agents at "low" reasoning effort hurt plan quality?

Run from the repo folder:   python scripts/effort_ab.py  [--repeats 2]
Writes results/effort_runs.csv (one row per plan) and results/effort_summary.md (for the report).

Gardenwise runs every agent at reasoning effort "low" to save tokens and time. This script plans the
same 10 gardener profiles at "low" and at "medium", alternating the order so neither side gets a
warmer prompt cache, and scores both with the same code: the verifier's first-try pass rate, the
final pass rate, the baseline script's independent plant checks, and whether the plan covers every
goal the gardener asked for.
"""

from __future__ import annotations

import csv
import os
import statistics as stats
import sys
import time
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_baseline import score  # noqa: E402
from cost_benchmark import PROFILES, constraints  # noqa: E402
from garden import config, llm  # noqa: E402
from garden.agents.intake import run_intake  # noqa: E402
from garden.data import plants  # noqa: E402
from garden.pipeline import assemble, recommend  # noqa: E402

EFFORTS = ("low", "medium")


def one_plan(name: str, kw: dict, note: str, effort: str) -> dict:
    os.environ["REASONING_EFFORT"] = effort
    b = llm.Budget(session_id=f"effort-{effort}-{uuid.uuid4().hex[:6]}", token_cap=200_000, call_cap=50)
    t0 = time.perf_counter()
    c = constraints(kw)
    if note:
        c = run_intake(c, [("user", note)], config.MAX_CHAT_FOLLOWUPS, b).constraints
    rec = recommend(c, b)
    secs = time.perf_counter() - t0
    plan = assemble(rec, [p.plant_id for p in rec.picks], [])
    s = score(c, [(plants()[x.plant_id], x.plant_out, x.harvest_start) for x in plan.schedules])
    goals = {g for p in plan.plants for g in p.goals}
    return {"effort": effort, "profile": name, "calls": len(b.calls),
            "input_tokens": sum(x.input_tokens for x in b.calls),
            "cached_tokens": sum(x.cached_tokens for x in b.calls),
            "output_tokens": sum(x.output_tokens for x in b.calls),
            "cost_usd": round(b.cost_usd, 6), "seconds": round(secs, 2),
            "verifier_first_try": bool(rec.report and rec.report.attempts == 1),
            "verifier_ok": bool(rec.report and (rec.report.ok or rec.report.repaired)),
            "plants": s["plants"], "plants_ok": s["plants_ok"],
            "goals_covered": all(g in goals for g in c.goals),
            "picks": " ".join(sorted(p.plant_id for p in rec.picks))}


def main() -> None:
    repeats = int(sys.argv[sys.argv.index("--repeats") + 1]) if "--repeats" in sys.argv else 2
    rows = []
    for e in EFFORTS:                      # prime the cache for both settings
        one_plan(*PROFILES[0], e)
    for r in range(repeats):
        for i, (name, kw, note) in enumerate(PROFILES):
            order = EFFORTS if (i + r) % 2 == 0 else EFFORTS[::-1]
            for e in order:
                rows.append({"repeat": r + 1} | one_plan(name, kw, note, e))
                x = rows[-1]
                print(f"  [{e:6}] {name}: ${x['cost_usd']:.5f} · {x['seconds']:.1f}s · "
                      f"first try {'✓' if x['verifier_first_try'] else '✗'} · {x['plants_ok']}/{x['plants']} ok")
    os.environ.pop("REASONING_EFFORT", None)

    out = config.RESULTS_DIR
    out.mkdir(exist_ok=True)
    with (out / "effort_runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def agg(effort):
        r = [x for x in rows if x["effort"] == effort]
        n = len(r)
        return {"n": n, "cost": stats.mean(x["cost_usd"] for x in r), "secs": stats.mean(x["seconds"] for x in r),
                "out": stats.mean(x["output_tokens"] for x in r),
                "first": sum(x["verifier_first_try"] for x in r) / n, "ok": sum(x["verifier_ok"] for x in r) / n,
                "pl": sum(x["plants"] for x in r), "pl_ok": sum(x["plants_ok"] for x in r),
                "goals": sum(x["goals_covered"] for x in r) / n}
    lo, md_ = agg("low"), agg("medium")

    # How often did the two settings pick the same plants for the same profile and repeat?
    pairs = {}
    for x in rows:
        pairs.setdefault((x["repeat"], x["profile"]), {})[x["effort"]] = set(x["picks"].split())
    overlap = stats.mean(len(p["low"] & p["medium"]) / max(1, len(p["low"] | p["medium"])) for p in pairs.values())

    md = ["# Reasoning effort: low vs. medium", "",
          f"Run {date.today():%B %d, %Y} with `{config.MODEL_NAME}`. The same 10 gardener profiles, "
          f"{repeats} runs each per setting ({lo['n']} plans per setting), order alternated so neither setting "
          "gets a warmer cache. Every agent (intake, selector, build advisor) uses the setting under test.", "",
          "| | Low (what Gardenwise uses) | Medium |", "|---|---|---|",
          f"| **Cost per plan** | **${lo['cost']:.5f}** | **${md_['cost']:.5f}** |",
          f"| Output tokens per plan (incl. reasoning) | {lo['out']:,.0f} | {md_['out']:,.0f} |",
          f"| Seconds per plan | {lo['secs']:.1f} | {md_['secs']:.1f} |",
          f"| Verifier passed on first try | {lo['first']:.0%} | {md_['first']:.0%} |",
          f"| Final plan passed verification | {lo['ok']:.0%} | {md_['ok']:.0%} |",
          f"| Plants passing the independent checks | {lo['pl_ok']}/{lo['pl']} | {md_['pl_ok']}/{md_['pl']} |",
          f"| Plans covering every goal asked for | {lo['goals']:.0%} | {md_['goals']:.0%} |", "",
          f"Medium effort cost **{md_['cost'] / lo['cost']:.1f}×** as much and took "
          f"**{md_['secs'] / lo['secs']:.1f}×** as long per plan. The two settings chose overlapping plant sets "
          f"(average Jaccard overlap {overlap:.0%}).", "",
          "Independent checks are the ones in `scripts/compare_baseline.py` (zone, sun, skill, space, "
          "planting vs. last frost, harvest vs. first frost).",
          "", "Seconds are wall-clock time through the Portkey gateway in this run only; gateway latency varied from about 0.2 s to 6 s per call over the day, so compare the two columns with each other, not with other benchmarks."]
    (out / "effort_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
