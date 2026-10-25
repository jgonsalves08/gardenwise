# Cost benchmark

Run October 25, 2026 with `gpt-6-luna` ($0.1/1M input, $0.01/1M cached, $0.5/1M output). 10 plans across 10 states.

| | Cold (cache bypassed) | Warm (cache working) |
|---|---|---|
| AI calls per plan | 2.3 | 2.3 |
| Input tokens per plan | 4,073 | 4,017 |
| …of which cached | 0 | 2,811 (70%) |
| Output tokens per plan | 542 | 551 |
| **Cost per plan** | **$0.00068** | **$0.00042** |
| Seconds per plan | 6.7 | 6.3 |
| Verifier passed on first try | 100% | 100% |
| Final plan passed verification | 100% | 100% |

Caching saved **37%** per plan. Quality is measured the same way in both modes (the code verifier).

Garden helper: **$0.00013 per message** on average (5 questions).

## Per user and at scale

Assumption: an active user makes 2 plans and asks the helper 15 questions a month; 1 in 4 plans adds a photo check (~$0.0002).

| Users | AI cost per month | AI cost per year |
|---|---|---|
| 1 | $0.0029 | $0.035 |
| 100 | $0.29 | $3.46 |
| 10,000 | $28.86 | $346.35 |

Community gardens: planning a 40-plot garden from a CSV is about 40 × $0.00042 ≈ **$0.017**.
