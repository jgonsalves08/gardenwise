# Gardenwise vs. a plain prompt

Same model (`gpt-6-luna`), same 10 gardener profiles across 10 states, scored by the same code checks (zone, sun, skill, space, planting date vs. last frost, harvest vs. first frost, pet and lead warnings).

| | Plain prompt | Gardenwise |
|---|---|---|
| Plants that passed every check | 33/46 (72%) | 35/35 (100%) |
| Plans with zero problems | 0/10 | 10/10 |
| Pet-toxicity warning when needed | 10/10 | 10/10 |
| Lead-in-soil warning for in-ground food | 2/10 | 10/10 |
| AI cost per plan | $0.00032 | $0.00038 |

Most common plain-prompt problems: too hard for skill level (9), needs more sun (2), plant not identifiable (2).

Caveat: the checks are Gardenwise's own rules applied to both systems; plants the plain prompt named that aren't in our database can't be verified and count as problems.
