# Live prompt attribution — 2026-11-03

[#474](https://github.com/zexy2/mealog/issues/474) asked whether the `p5` Item F1 gain came
from perceiving more truth items, from committing items the model already perceived, or from
both. On this quadruple run the answer is both. Between `p4` and `p5`, 14 truth items newly
entered the model's candidate lists and 6 left; 8 of the new ones were answered immediately
and 6 stayed perceived but uncommitted, while a further 8 already-perceived items were
committed. The gross movement into `resolved` is 16 items, so new perception accounts for 8
and new commitment for 8. The second pairing reproduces the split: `p4b` to `p5b` gains 11
items from `absent` and 7 from `perceived`, 18 gross gains into `resolved` against 3 losses.
The direction is consistent across the two repeats. The magnitude is not separable from
run-to-run noise at n=2, and nothing here attributes the move to one of the five changes in
`p5`.

## Method

Four sequential live runs on 2026-11-03, 18:35–19:01Z (21:35–22:01 on the local UTC+3 clock),
over the same 75 live-eligible rows. `jp_0001` and `jp_0002` were refused by licence in every
run. Each run used the unmodified harness:

```bash
python eval/harness.py --configs V3 --live --prompt-variant p4 \
  --predictions "$ARTIFACTS/preds-p4.jsonl" --out "$ARTIFACTS/scorecard-p4.md" \
  --summary-json "$ARTIFACTS/summary-p4.json"
```

The four prediction artifacts, summaries and scorecards are in `/tmp/pilot4/` on the machine
that ran them; `$ARTIFACTS` stands for that directory below. They are **not committed**, and
the numbers in this document are a dated observation rather than a reproducible baseline.
The run code was launched at commit `3a08f74`.
[#478](https://github.com/zexy2/mealog/pull/478) merged during the runs and added only
`eval/compare_predictions.py`, its tests and `docs/evaluation.md`, so harness, adapter and
prompt code did not change between runs.

| Run | Variant | Rows scored | Item F1 | Coverage | FP rate | Committed | Asked | Abstained |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| p4 | p4 | 75 | 0.38 | 9.3% | 36.0% | 7 | 68 | 159 |
| p4b | p4 | 74 | 0.39 | 12.2% | 33.1% | 9 | 65 | 154 |
| p5 | p5 | 75 | 0.41 | 12.0% | 39.6% | 9 | 66 | 157 |
| p5b | p5 | 75 | 0.42 | 10.7% | 39.7% | 8 | 67 | 155 |

`p4b` lost one row: `n5k_0039` ended `terminal_status=local_deadline` after one attempt,
against the shipped 30 s per-row budget and 90 s request timeout. That leaves 74 scored rows
and 326 truth items instead of 329, so every flow involving `p4b` is an intersection over the
rows both sides scored, not a full-run comparison. Requested `gemini-flash-lite-latest`; all
four runs were served `gemini-3.5-flash-lite`. This is a second quadruple run, separate from
the four runs in [live-prompt-comparison-2026-11-02.md](live-prompt-comparison-2026-11-02.md).

## Classes

Each truth item on a scored row is classified once by `eval/compare_predictions.py`:
**resolved** (in `pred_ids`), **perceived** (in a candidate list but not answered) or
**absent** (in no candidate list). The artifact keeps at most three candidates per perceived
item; the offline identity diagnosis keeps five, so `absent` here is stricter and these
counts are not interchangeable with the diagnosis's "never perceived" counts.
Class totals are `p4` 89/61/179 (329), `p4b` 89/53/184 (326), `p5` 102/56/171 (329) and
`p5b` 105/55/169 (329). The aggregate move from `p4` to `p5` is `resolved` +13, `perceived`
−5, `absent` −8; from `p4b` to `p5b` it is +15, +2, −17. In both pairings most of the
movement is truth items leaving `absent`, with a smaller group arriving from `perceived`.

## Flows between classes

Full-run flow, `p4` → `p5` (75 rows, 329 truth items):

| p4 ↓ / p5 → | resolved | perceived | absent | Total |
|---|---:|---:|---:|---:|
| resolved | 86 | 1 | 2 | 89 |
| perceived | 8 | 49 | 4 | 61 |
| absent | 8 | 6 | 165 | 179 |
| **p5 total** | **102** | **56** | **171** | **329** |

Cross-check, `p4b` → `p5b` (74 rows, 326 items, intersection only): `resolved` 86/3/0,
`perceived` 7/40/6, `absent` 11/12/161. The candidate totals are 104/55/167, so the net is
+15 resolved, +2 perceived, −17 absent. A third pairing, `p4` → `p5b` (75 rows), gives 18
gross gains into `resolved` (8 from `absent`, 10 from `perceived`) against 2 losses, for a
net of +16. The two `p4` baselines and the later `p5` runs tell the same story: roughly half
the gross gain is new perception and roughly half is commitment of items already seen.

## From items to Item F1

Item F1 is micro-averaged over truth items, so these classes are its terms: `resolved` is
true positives, `absent` plus `perceived` is false negatives, and predicted ids outside truth
are false positives.

| Run | TP (`resolved`) | FP | FN | Micro F1 |
|---|---:|---:|---:|---:|
| p4 | 89 | 50 | 240 | 0.38 |
| p4b | 89 | 44 | 237 | 0.39 |
| p5 | 102 | 67 | 227 | 0.41 |
| p5b | 105 | 69 | 224 | 0.42 |

From `p4` to `p5`, TP rises by 13 and FN falls by 13, but FP rises by 17: the F1 gain is the
net of those, not a free increase in truth coverage. The same arithmetic reproduces every
published F1 to two decimals.

## Same-prompt noise

The same prompt does not return the same item classes. These pairs share a prompt and differ
only by run:

| Pair | Rows | Gross into resolved | Gross out of resolved | Net resolved | Net perceived | Net absent |
|---|---:|---:|---:|---:|---:|---:|
| p4 → p4b | 74 | 7 | 6 | +1 | −8 | +7 |
| p5 → p5b | 75 | 9 | 6 | +3 | −1 | −2 |

A same-prompt pair already moves 7–9 items into `resolved` and loses 6. The cross-prompt pairs
move 16–18 in and lose 2–3. If same-prompt churn is treated as a noise floor, roughly half the
cross-prompt gross gain is not prompt-specific. That is an informal bound, not an estimate: it
compares two runs per variant on one day and does not model the distribution of churn.

## Which foods moved

`p4` → `p5`, net resolved per food: `us.chickpeas_cooked` 0→4, `us.rice_white_cooked` 8→11
(+4 in, −1 out), `us.broccoli_cooked` 19→21, `us.chicken_breast_grilled` 1→2 (+2 in, −1
out), `us.kale_cooked` 2→3, `us.zucchini_cooked` 5→6 and `us.olive_oil` 0→1.
Newly entering candidate lists, `p4` → `p5`: `absent` → `resolved`, 8 items (`chickpeas` ×2,
`broccoli` ×2, `rice`, `zucchini`, `kale`, `chicken_breast`); `absent` → `perceived`, 6
(`chickpeas` ×2, `corn`, `olive_oil`, `chicken_breast`, `arugula`); `perceived` → `resolved`,
8 (`rice` ×3, `chickpeas` ×2, `pork_roasted`, `chicken_breast`, `olive_oil`). Losses were
small: `resolved` → `absent` 2 (`rice`, `pork_roasted`), `resolved` → `perceived` 1
(`chicken_breast`), `perceived` → `absent` 4 (`arugula` ×2, `olive_oil`, `pork_roasted`).
`p4b` → `p5b` reproduces the same food families: `absent` → `resolved` 11 (`chickpeas` 2,
`broccoli` 2, `rice` 2, `zucchini`, `kale`, `tomatoes`, `beef`, `mushrooms`), `absent` →
`perceived` 12 (`arugula` 6, `chickpeas` 2, `corn` 2, `olive_oil` 2), and `perceived` →
`resolved` 7. One food does not move: `us.olive_oil` is absent 62 times in `p4` and 62 times
in `p5`. The dominant blind spot is unchanged, so the ceiling is not lifted; the gains are a
redistribution at the margin, not a new ability to see oil.

## Per cuisine

| Cuisine | Item F1 (p4 / p4b / p5 / p5b) | Net resolved p4 → p5 | Same-prompt net (p4 → p4b / p5 → p5b) |
|---|---|---:|---|
| western | 0.75 / 0.77 / 0.74 / 0.73 | 0 | 0 / 0 |
| other_mixed | 0.26 / 0.27 / 0.33 / 0.29 | +2 | 0 / −1 |
| mediterranean | 0.16 / 0.17 / 0.20 / 0.13 | +1 | 0 / −2 |
| east_asian | 0.28 / 0.27 / 0.34 / 0.36 | +4 | 0 / 0 |
| south_asian | 0.16 / 0.20 / 0.25 / 0.31 | +5 | +2 / +4 |
| latin_american | 0.49 / 0.48 / 0.49 / 0.49 | +1 | −1 / +2 |

`east_asian` and `south_asian` rise in both cross-prompt pairings, with `western` and
`latin_american` roughly flat, reproducing the 2026-11-02 per-cuisine pattern. The
`south_asian` bucket is not clean: it also moves +2 and +4 in the same-prompt pairs.
`east_asian` is the only bucket that rises in both cross-prompt pairings and does not move in
either same-prompt pair. `mediterranean` and `other_mixed` move in opposite directions across
the two repeats, so their F1 movement is not a finding.

## False positives

Predicted ids not in truth number 50, 44, 67 and 69 in `p4`, `p4b`, `p5` and `p5b`. For each,
the food's core name appears in the query text of the perceived item that produced it — a
whole-token match after removing preparation suffixes such as `_cooked`, `_raw`, `_grilled`,
`_fried`, `_boiled`, `_baked`, `_roasted`, `_scrambled` and `_breaded` — in 39/50 (78%),
36/44 (82%), 54/67 (81%) and 58/69 (84%) of cases. The rule is crude: a query can name a
component while the overall identification is wrong, so "self-named" does not mean "correct".
The implication is that most extra false positives are items the model itself named: the
error is upstream of candidate scoring and threshold, not a ranker artefact. `p5` commits
many more items (`resolved` + false positives = 169 and 174, against 139 and 133) at a
slightly higher false-positive share; the F1 gain is not free.

## What this does not show

- No attribution to one of the five bundled `p5` changes. Both mechanisms moved, but the
  bundle was not split; single-change variants are still needed for that claim.
- No proof that `p5` is better in general, and no significance test. There are two runs per
  variant on this day, and one model, one scope.
- No reproducible baseline: the artifacts are uncommitted and re-running is live and
  nondeterministic ([D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline)).
- No interchangeable `absent` count. The artifact keeps three candidates, the offline
  diagnosis five.
- No calorie conclusion (two eligible rows, both scored) and no claim about a model other
  than `gemini-3.5-flash-lite`.

## Provenance

Four runs on 2026-11-03 through `eval/harness.py --live --prompt-variant`, using the
`--predictions` instrument added in [#472](https://github.com/zexy2/mealog/issues/472) and the
comparison tool added in [#478](https://github.com/zexy2/mealog/pull/478). Scoring, prompt
text, pacing, budget and fixture handling were not altered; no fixture was written and no
published offline number changed. The artifacts are not committed. Comparison:

```bash
python eval/compare_predictions.py --baseline "$ARTIFACTS/preds-p4.jsonl" \
  --candidate "$ARTIFACTS/preds-p5.jsonl"
```
The direction reproduces the 2026-11-02 comparison: across both days `p4` is 0.36–0.39 and
`p5` is 0.41–0.42. That is one model, one scope and no significance test, and it does not make
`p5` proven better.
