# Reasoning effort: low vs. medium

Run October 25, 2026 with `gpt-6-luna`. The same 10 gardener profiles, 2 runs each per setting (20 plans per setting), order alternated so neither setting gets a warmer cache. Every agent (intake, selector, build advisor) uses the setting under test.

| | Low (what Gardenwise uses) | Medium |
|---|---|---|
| **Cost per plan** | **$0.00045** | **$0.00056** |
| Output tokens per plan (incl. reasoning) | 536 | 752 |
| Seconds per plan | 0.9 | 3.8 |
| Verifier passed on first try | 100% | 100% |
| Final plan passed verification | 100% | 100% |
| Plants passing the independent checks | 70/70 | 72/72 |
| Plans covering every goal asked for | 100% | 100% |

Medium effort cost **1.2×** as much and took **4.2×** as long per plan. The two settings chose overlapping plant sets (average Jaccard overlap 77%).

Independent checks are the ones in `scripts/compare_baseline.py` (zone, sun, skill, space, planting vs. last frost, harvest vs. first frost).

Seconds are wall-clock time through the Portkey gateway in this run only; gateway latency varied from about 0.2 s to 6 s per call over the day, so compare the two columns with each other, not with other benchmarks.
