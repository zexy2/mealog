# Evaluation methodology

> **Headline result.** The system knows what it measured and refuses to guess
> beyond it. On the published 77-sample replay it answers 7 samples without
> deferring and asks on 70; all seven answers are review proposals, none is
> auto-accepted. The gate is deliberately conservative, and the weakest cuisine
> bucket is reported rather than averaged away. Read the numbers below as a
> measurement of limits, not as a product accuracy claim.

This document describes the measurement system that is implemented by
`eval/metrics.py` and rendered by `eval/harness.py`. `make eval` replays the
recorded fixtures offline; the live-provider path is separate as required by
[D4](decisions.md#d4--offline-reproducible-evaluation-via-recorded-fixtures).

## Golden set

Each line in `eval/golden/manifest.jsonl` is one sample. It carries a cuisine
bucket, a conservative overall tier, truth items as `food_id` plus the
harness-compatible numeric `grams` field, and `truth_axes` with separate
identity and portion tiers. Every food ID and mass field carries a provenance
string in the form `dataset=...; record_id=...; field=...`.

The committed manifest contains **n=80** samples, with 80 matching recorded
provider fixtures. The **published replay covers 77**: three rows are Turkish,
and the Turkish catalogue may not be redistributed, so a clean clone cannot
load them. They are excluded by an explicit rule rather than skipped by
accident; `--include-restricted` adds them on a machine that installed the pack
with `make pack`. See [Evidence scope](#evidence-scope-and-the-checked-readme-contract).

The manifest's 80 rows are distributed across six cuisine buckets: western 12,
mediterranean 12, east_asian 16, other_mixed 8, south_asian 16, and
latin_american 16. After the scope rule, mediterranean is 9. The conservative
overall tiers are tier_1 74, tier_2 1, and tier_3 5 in the manifest; the
published replay has tier_3 2.

The conservative overall tier does not hide axis differences:

| Axis/source | Tier | Meaning |
|---|---|---|
| Nutrition5k identity + mass | Tier 1 | Official per-ingredient class/name and scale-weighed grams. |
| Open Food Facts identity | Tier 1 | Product identity and per-100g label fields. |
| Open Food Facts portion | Tier 2 | Printed serving applied as an assumption; eaten mass is not observed. |
| TurkishFoods-15 / UEC-Food 256 identity | Tier 1 | Official class label. |
| TurkishFoods-15 / UEC-Food 256 portion | Tier 3 | Dataset supplies no mass. No plausible gram value is claimed. |
| Two-rater text consensus | Tier 3 | Identity and portion are consensus labels, not instrument measurements. |

For identity-only rows, `grams: 0` is a non-scoring sentinel required by the
current offline harness. It is not source truth and does not mean an empty
portion. `grams_provenance` explicitly records `mass_g (not provided; 0 is
evaluator sentinel)`. Their identity sets are still scored; zero-truth rows
are excluded from calorie APE/MAPE by the existing zero-truth rule. Traps have
empty truth and are scored on identity rather than calorie error.

Nutrition5k rows can also contain `unmapped_source_ingredients`. A non-empty
list means the mapped `truth.items` are only a partial view of the meal: the
mapped calorie sum is retained for inspection but is not complete meal truth.
Such rows are `calorie_eligible = false` and are excluded from calorie APE,
MAPE, and within-20% calculations. They remain in identity, Item F1, coverage,
FP-rate, and error-tag calculations. Incompleteness is never represented by
changing calories to zero.

An error against a Tier 3 label is weaker evidence than the same error against
a Tier 1 label. Tiers are never silently combined: the harness reports the
same evaluation by the conservative overall tier as well as by cuisine, while
the manifest preserves the per-axis distinction for review.

## Evidence scope and the checked README contract

Published numbers are defined as **what a clean clone reproduces**, not as the
best measurement the maintainer can obtain. The distinction became necessary
when the README published a run made with the licence-restricted Turkish
catalogue installed: the same command on a fresh checkout produced different
numbers (9% coverage instead of 12%, Item F1 0.38 instead of 0.39), and
`eval/retrieval_eval.py` crashed because the pack was absent. A claim the
repository's own tree cannot support is worse than an unflattering number.

`eval/locale_scope.py` owns the rule. A locale whose `pack.yaml` declares
`license: restricted-noncommercial` is excluded from every published
denominator; `--include-restricted` adds it back for a local measurement. Both
`eval/harness.py` and `eval/retrieval_eval.py` take their scope from that one
module, so the two cannot disagree about which markets are in the published set,
and `eval/decompose_real_error.py` uses it too, so the diagnostic the docs
point at also runs on a clean clone.

For the current tree the exclusion is:

| Evidence | Published | Excluded by licence |
|---|---:|---:|
| Golden rows (`eval/golden/manifest.jsonl`) | 77 | 3 |
| Retrieval variants (`eval/golden/query_variants.jsonl`) | 38 | 107 |

Both evaluations can write the README-facing numbers with `--summary-json`.
`scripts/check_readme_claims.py` (also `make claims`) parses the README's
`## Evidence snapshot`, runs both evaluations with the published scope, and
fails with the exact replacement text when they disagree. It additionally
rejects an internally inconsistent summary (`commit + ask > rows`,
`scored > eligible`), so a typo cannot pass by matching another typo. CI runs
the same check next to the eval regression guard, which means the README's
least flattering numbers are now the repository's most tightly checked claim.

`--include-restricted` exists for maintainers who installed the pack with
`make pack`; `make eval-restricted` writes those scorecards. Those numbers are
a local measurement, not the published snapshot, because a reader cannot
reproduce them from the repository alone.

## Headline and per-sample metrics

The headline is the **worst cuisine bucket's MAPE**, followed by the
worst-to-best **spread**. It is not the mean: averaging can hide the market or
cuisine where the system fails, which is the failure this evaluation is meant
to expose. This follows [D3](decisions.md#d3--headline-metric-is-the-worst-cuisine-and-accuracy-is-read-with-coverage).

`spread` is the worst cuisine MAPE divided by the best cuisine MAPE. The
scorecard also prints overall MAPE as secondary context, but it is not the
headline.

Calorie MAPE is computed over **covered, calorie-eligible samples only**. A
sample is covered when it neither abstains nor asks the user for clarification.
Covered is not the same as auto-saved: a count read from a photo caps item
confidence at 0.60 (`VISION_COUNT_CONFIDENCE`) against the 0.75
`AUTO_ACCEPT` threshold, so every vision-derived row in this replay routes to
`review`. In the current run that is 7 rows proposed and 0 auto-accepted.
a sample is calorie-eligible only when its truth is complete and its total
calories are positive. Coverage is reported next to MAPE because they describe
a risk–coverage trade: a system can lower its error by answering only the cases
it is willing to answer.
Treating a deferred meal as a zero-calorie answer would punish correct
behaviour, so deferred samples are excluded from calorie MAPE rather than
scored as wrong zeroes. Samples with zero truth calories have no calorie APE;
the trap case is therefore represented by identity metrics. The scorecard's
`Calorie eligible` count is the complete-positive-truth pool before coverage,
and `Calorie scored` is the covered subset that contributes APE/MAPE.

The implemented `Bucket` metrics are:

| Metric | Meaning |
|---|---|
| `precision`, `recall`, `f1` | Set-based identity precision, recall, and F1 over `food_id` |
| `coverage` | Covered samples as a percentage of all samples in the bucket |
| `calorie_eligible` | Count of complete-truth samples with positive calories; partial and zero-truth rows are excluded |
| `calorie_scored` | Count of covered, calorie-eligible rows contributing an APE |
| `mape` | Mean absolute percentage calorie error over `calorie_scored` rows |
| `within_20pct` | `calorie_scored` rows whose calorie error is at most 20% |
| `hallucination_rate` | False positives divided by true positives plus false positives |
| `error_distribution` | Count of observed error tags, once per sample carrying each tag |

The generated scorecard labels `hallucination_rate` as `FP rate`. The precise
boundary is narrower than a blanket impossibility claim:
resolver cannot select a `food_id` outside its candidate set, and no model
emits a nutrition number. The vision stage can still report an item that was
not on the plate; that report may resolve to a real catalogue entry. That
perception failure is what the current V3 `E3` tag counts when it is observable
from the evaluated identity sets.

`aggregate()` produces these per-bucket metrics by cuisine and
`aggregate_by_tier()` applies every one of the same `Bucket` calculations by
ground-truth tier, so every per-bucket headline metric has a tier slice and the
definitions cannot silently diverge. The scorecard prints, for each cuisine
and tier, `n`, coverage, calorie eligibility/scored counts, Item F1, kcal
MAPE, `within_20pct`, and FP rate.

An empty calorie denominator is not a zero-error result. `Bucket.mape` and
`Bucket.within_20pct` retain numeric zero for regression/JSON compatibility,
but format as an em dash in scorecard cells when there are no positive-truth
APE values. A bucket with `coverage > 0%` can still have no calorie score when
its truth is identity-only; a bucket with `coverage = 0%` has no non-deferred
calorie predictions at all. Neither should be read as `0.0%` accuracy.
The regression guard compares only non-empty `calorie_scored` buckets. If a
bucket that had a positive baseline MAPE has no eligible calorie rows now, the
guard reports that as unsafe to compare rather than calling an empty denominator
an accuracy improvement.
In the current V3 table, an em dash means that the bucket has no covered,
positive-truth calorie rows, not a zero-error result. Only the western cuisine
bucket has positive calorie-scored rows; the tier table has one tier_1 and one
tier_2 row in that denominator.

## Current replay and V3 decomposition

The current offline replay on **n=77** produces these ablation rows. V3's
worst-cuisine (`western`) MAPE is **12.7%**, computed over **n=2** covered,
calorie-eligible samples. The V3 coverage is **9%** (**7/77** samples answered
without deferring, all routed to `review`), while **70/77** samples ask for
clarification. These are current
outputs of `python eval/harness.py`, not claims about unmeasured provider
behaviour.

| Config | Worst-cuisine MAPE | Mean MAPE | Spread | Coverage | Calorie eligible | Calorie scored | Item F1 | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 | 100.0% (western) | 100.0% | 1.00x | 100% | 2 | 2 | 0.00 | 100.0% |
| V1 | 12.7% (western) | 12.7% | 1.00x | 42% | 2 | 2 | 0.45 | 46.1% |
| V2 | 12.7% (western) | 12.7% | 1.00x | 42% | 2 | 2 | 0.45 | 46.1% |
| V3 | 12.7% (western) | 12.7% | 1.00x | 9% | 2 | 2 | 0.38 | 40.5% |

The current V3 cuisine slices are:

| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| western | 12 | 33% | 2 | 2 | 0.77 | 12.7% | 50.0% | 19.4% |
| east_asian | 16 | 6% | 0 | 0 | 0.31 | — | — | 56.7% |
| other_mixed | 8 | 0% | 0 | 0 | 0.29 | — | — | 41.7% |
| mediterranean | 9 | 0% | 0 | 0 | 0.12 | — | — | 70.0% |
| south_asian | 16 | 0% | 0 | 0 | 0.17 | — | — | 57.9% |
| latin_american | 16 | 12% | 0 | 0 | 0.46 | — | — | 32.6% |
| **overall** | **77** | **9%** | **2** | **2** | **0.38** | **12.7%** | **50.0%** | **40.5%** |

The same V3 calculations by conservative overall tier are:

| Ground-truth tier | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tier_1 | 74 | 8% | 1 | 1 | 0.37 | 25.4% | 0.0% | 40.3% |
| tier_2 | 1 | 100% | 1 | 1 | 1.00 | 0.0% | 100.0% | 0.0% |
| tier_3 | 2 | 0% | 0 | 0 | 0.40 | — | — | 66.7% |
| **overall** | **77** | **9%** | **2** | **2** | **0.38** | **12.7%** | **50.0%** | **40.5%** |

> **Methodological Context on False Positive (FP) Rate:** The 40.5% FP rate is
> measured across every sample in scope and counts rejected and abstained
> proposals, not only the non-deferred ones. It was 88.2% before D25: the
> golden truth still listed catalogue foods such as broccoli, pork and tofu as
> "unmapped", so correct predictions were scored as false positives. What
> remains is mostly genuinely out-of-catalogue ingredients (salt, garlic,
> sauces, cheese) and near-miss bindings, not the catalogue gap. And 70 of the
> 77 samples ended in a safe `ask`, so no ungrounded candidate reached the
> user's log. The rate is a property of the identity layer's proposals, not
> evidence that 40% of logged meals were wrong.

`python eval/decompose_real_error.py` also replays the committed fixtures
without provider calls. It takes the same published scope as the harness, so it
runs on a clean clone; `--include-restricted` adds the excluded locale. Its raw
mapped-total output has seven covered rows with positive mapped calories, but
five are partial-truth rows and therefore are not calorie-eligible. The harness
remains the authority for calorie metrics; only the two complete rows below
enter the scorecard denominator:

| Rank | Sample | APE | Share of summed APE |
|---:|---|---:|---:|
| 1 | n5k_0002 | 25.4% | 100.0% |
| 2 | pkg_0001 | 0.0% | 0.0% |

The five partial-truth rows that the decomposition helper maps while V3
answers them without deferring are `n5k_0003`, `n5k_0005`, `n5k_0010`, `n5k_0016`, and `n5k_0058`.
Their mapped calorie totals are diagnostic only;
they are not complete meal truth and must not enter MAPE or within-20%
metrics. The two exact-identity counterfactuals use the complete rows: perfect
identity with observed grams is **12.69% MAPE** (`n=2`), while perfect grams
with observed identity is **0.00% MAPE** (`n=2`). There is no covered identity
mismatch in this replay. Seventy-two in-scope manifest rows have partial truth
and are not calorie-eligible; five of those rows are covered in the current V3
run, but none enters the APE denominator. The decomposition script's detailed
table shows mapped truth for inspection, not complete meal calories for those
rows.

The complete table generated by `python eval/decompose_real_error.py` is
intentionally not pasted here: most of its rows are deferred or have partial
or zero-truth nutrition, so their mapped calorie sums are not complete meal
calories. The two-row distribution above is the honest calorie decomposition
supported by the current data; the helper's five partial-row APEs are not
evaluation metrics.

### Why V3 answered only 9% of meals

The current harness answers **7/77** samples without deferring and routes
**70/77** to `ask`, for **9% coverage** after integer percentage formatting.
All seven are `review`, not `auto_accept`. `E12=70` is generated by
the same replay. This is the current measurable statement: the safe gate trades
substantial coverage for fewer silent commits.

An older hand-written catalogue-versus-threshold decomposition was removed
because it described a 12-commit run and had no checked-in generator tying its
counts to the current replay. The present scorecard does not expose enough
information to assign the 70 deferrals to those causal buckets without a new,
reproducible report. No threshold or catalogue value is changed here.

## Where the identity errors come from

Item F1 is one number; the explanation has to be checkable.
`python eval/identity_diagnosis.py` replays the same fixtures with the same
retrieval and resolver, charges every truth item and every false positive to a
stage, and cross-checks its own totals against the scorecard. The generated
report is [identity-diagnosis.md](identity-diagnosis.md); `make check` fails if
the committed copy no longer matches the fixtures.

| Outcome | Truth items (n=331) |
|---|---:|
| Resolved (TP) | 91 (27.5%) |
| Ranked first, refused by the gate | 39 (11.8%) |
| In a top-5 list, not first | 24 (7.3%) |
| Never named by the model | 177 (53.5%) |

Two consequences follow, and both constrain what a fix can honestly claim:

- A perfect resolver over the foods the model did name would reach at most Item
  F1 **0.64**, because 177 truth items never entered a candidate list. Lowering
  the accept threshold, adding aliases or re-ranking cannot recover them; only
  better perception, or a newly recorded prompt, can.
- Most of those misses are small. `us.olive_oil` alone is 61 of the 177, at a
  median source mass of 3.9 g, and cooked kale is 16 at 3.2 g. The truth is a
  recipe, not a plate: part of the remaining error is not visible in any
  photograph and would not shrink under a perfect detector. That ceiling is
  stated rather than engineered around by deleting the rows.

One label category carries much of that gap: `us.olive_oil` is 65 of the 331
truth items and 61 of the 177 never perceived.
[visible-ingredient-ceiling-2026-11-03.md](visible-ingredient-ceiling-2026-11-03.md)
recomputes the ceiling under explicit exclusions — removing olive oil lifts it
to 0.72, and removing every item under 10 g as well lifts it to 0.83 but still
leaves 52 never-perceived items. Those are sensitivity cuts, not a new
denominator: the published 0.64 and Item F1 0.38 are unchanged.

Of the 62 false positives, 49 are foods the model named verbatim and 60 sit on
rows whose truth is incomplete; 13 are similarity-only bindings, the only class
a better ranker can fix.

## Error taxonomy

The taxonomy has twelve `ErrorCode` values, but the harness only derives codes
that are observable from the fields in an evaluated result:

- `E3` — an extra predicted `food_id`;
- `E4` — a truth `food_id` that was missed;
- `E7` — a matched food whose predicted mass differs from truth by more than 30%;
- `E12` — the harness asked for clarification instead of committing.

Identity-based tags apply only when identity is applicable, such as the
closed-set configurations. The remaining causes require human judgement. In
particular, when a mismatch could be `E1`, `E2`, `E9`, `E10`, or `E11`, the
harness represents it as `unclassified`; aggregate fields cannot establish the
cause. A guessed code is worse than no code. A sample with an observable
mismatch also keeps `unclassified` alongside any automatic tag rather than
pretending to know the human cause.

The error-distribution section lists all twelve codes plus `unclassified` and
reports sample counts and their share of tagged samples. It is a distribution
of tags, not a claim that a human reviewed and assigned every specific cause.

For the current V3 replay on **n=77**, the observable tag counts are `E3=43`,
`E4=72`, `E7=41`, `E12=70`, and `unclassified=74`; the other eight codes are
zero. Tags are not mutually exclusive, so these counts do not sum to the
sample count.

## Configurations and regression guard

The offline scorecard compares the four configurations implemented by the
harness:

| Config | What it adds |
|---|---|
| V0 | Single-prompt VLM reporting calories directly |
| V1 | Closed-set resolution and catalogue-computed nutrition |
| V2 | Locale text and unit normalization |
| V3 | Confidence gating and abstention |

Each ablation row reports worst-cuisine MAPE, secondary overall MAPE, spread,
coverage, Item F1, and FP rate. `python eval/harness.py --check-regression`
compares the selected configuration's per-cuisine MAPE with the stored
baseline and fails if any cuisine bucket gets worse.

## Live measurement

The scorecards above replay recorded fixtures. The harness can also call the
provider, and that path is deliberately separate from the baseline (D24).

```bash
python scripts/fetch_golden_images.py       # 35 MB, 77 image files into data/golden-images
python eval/harness.py --configs V3 --live --limit 10 \
  --out eval/reports/scorecard-live.md      # measurement only
make record                                 # the only writer of eval/fixtures
```

The directory holds 77 image files for 80 manifest rows: two are the
licence-restricted `tr` rows (`tr_0001`, `tr_0002`), and three rows have no
image bytes (`jp_0001`, `jp_0002`, and `tr_0003`). That is not the only reason
those rows are absent from a live run. Eligibility is decided first, from
`image_license` against a closed allowlist in `eval/golden_inputs.py`, so
`jp_0001` and `jp_0002` are refused by licence even if a cached copy is placed
in `data/golden-images/`.

`--live` uses the same manifest rows as the offline run: each row's image bytes
and media type are sent to the adapter, or its text when the row is the text
lane. `--manifest`, `--images-dir` and `--limit` bound the run; `--limit N`
applies after scope filtering and live-licence exclusion, in manifest order.

`--prompt-variant NAME` selects a named prompt for a live run; the shipping
variant is the default and is what an offline replay implies. The flag is
ignored offline because fixtures replay by `sample_id`, so passing it does not
change the offline scorecard. The live scorecard header and `--summary-json`
record the variant, so a live result names its prompt rather than the module
constant. The flag was used on 2026-11-02 to compare `p4` and `p5` over two
live runs each on the 75 live-eligible rows; the result is
[live-prompt-comparison-2026-11-02.md](live-prompt-comparison-2026-11-02.md).
Its headline is that Item F1 moved from 0.36–0.37 to 0.41 while coverage did
not move.

`--predictions PATH` writes a per-row JSONL artifact for a live run: identity
(`config`, `sample_id`, `locale`, `cuisine`, `tier`, `prompt_variant`), what the
model produced (each item's `query`, `food_id` or abstain sentinel, `abstained`,
`confidence`, and up to three `candidates` with `food_id` and `score`), the
scoring sets (`truth_ids`, `pred_ids`), and `row_error`. It is live-only; passing
it without `--live` exits 2 and writes nothing, because the offline path is
deterministic and the artifact records live perception. There is exactly one
line per attempted row, including a failed row, which carries empty `perceived`
and `pred_ids` and the exception message in `row_error`; a row removed before a
call (licence scope, or a catalogue pack that is not installed) was not
attempted and produces no line. An existing target is overwritten, missing
parents are created as with `--summary-json`, and the file contains no image
bytes, base64, absolute filesystem paths, or API key.

```bash
python eval/harness.py --configs V3 --live --prompt-variant p4 \
  --predictions /tmp/preds.jsonl
```

The real line the test double emitted, with the third candidate omitted:

```json
{"config":"V3","sample_id":"n5k_0001","locale":"en_US","cuisine":"western","tier":"tier_1","prompt_variant":"p4","perceived":[{"query":"grilled chicken","food_id":"us.chicken_breast_grilled","abstained":false,"confidence":1.0,"candidates":[{"food_id":"us.chicken_breast_grilled","score":1.0},{"food_id":"us.salmon_cooked","score":0.416}]}],"truth_ids":["us.chicken_breast_grilled"],"pred_ids":["us.chicken_breast_grilled"],"row_error":null}
```

`eval/compare_predictions.py` reads one or two of those artifacts and
classifies every truth item on a successfully scored row as **resolved** (in
`pred_ids`), **perceived** (in a candidate list but not answered) or **absent**
(in no candidate list), reporting counts overall, by cuisine and by tier, plus
the most common absent foods. With `--candidate` it joins two artifacts on
`(sample_id, food_id)` and reports the flow between classes and the net change
in each. The artifact keeps at most three candidates while the offline identity
diagnosis keeps five, so `absent` here is stricter and the two counts are not
interchangeable. A two-artifact flow is computed only over the sample ids both
artifacts scored successfully; rows missing from one side or failed there are
named with the counts they drop, so an intersection result is never presented
as a full-run comparison.

```bash
python eval/compare_predictions.py --baseline /tmp/preds-p4.jsonl \
  --candidate /tmp/preds-p5.jsonl
```

The tool was applied to a second quadruple live run on 2026-11-03; the result is
[live-prompt-attribution-2026-11-03.md](live-prompt-attribution-2026-11-03.md). Both new
perception and commitment of already-perceived items moved between `p4` and `p5`: 14 truth
items entered candidate lists and 6 left, while 16 gross gains in `resolved` were offset by 3
losses. The `p4b` run lost one row to `local_deadline`, so its comparison with `p5b` uses the
74-row, 326-item intersection; `absent` remains stricter than the offline diagnosis because
the artifact holds three candidates, not five.

### Live budget and failure attribution

The per-row wall-clock budget is resolved when the adapter is constructed. An
explicit `max_elapsed` argument wins; otherwise `GEMINI_MAX_ELAPSED_SECONDS`;
otherwise the shipped `MAX_ELAPSED_SECONDS = 30.0`. A blank environment value
means unset, matching `GEMINI_MODEL`. The resolved value must be a finite number
of seconds greater than zero; anything else raises `ValueError` instead of
being clamped. There is no hidden upper ceiling: the configured value is the
effective value, because a ceiling that silently reduces a request was the
defect this replaced ([#466](https://github.com/zexy2/mealog/issues/466)). The
adapter records it as `GeminiVision.max_elapsed`.

The budget bounds retries and fallbacks, not the first answer. A single request
may use the configured request timeout (`timeout`, 90 s by default) even when
that runs past `max_elapsed`, and a response inside its own timeout is accepted.
No retry or fallback rung starts after the deadline. The total bound is one
request timeout past the configured budget, not an unbounded wait.

Two terminal states are distinct:

- `terminal_status=local_deadline`, a `Gemini local deadline of <N>s reached
  …` message, and a `vision_local_deadline` event mean the adapter stopped
  because its own clock allowed no further retry or fallback. The event carries
  `attempts`, `elapsed_ms`, `rung`, and `max_elapsed`.
- `terminal_status=<HTTP status or unknown>` with the `Gemini provider
  exhausted …` message means the provider failed inside the configured
  attempts. The `vision_provider_exhausted` event also carries `max_elapsed`
  and `requested_model`.

If a rung failed and the next rung never started because the budget expired,
the terminal state is `local_deadline` and the message retains the provider
detail (`last provider failure: …`).

The harness prints `row <sample_id> failed: <error>` and records the id in
`row_errors`; the printed error is what distinguishes "our ceiling" from
"provider failure".

The adapter exposes the model identity it observed:

| Attribute | Meaning |
|---|---|
| `model_id` / `model` | requested model id, before any fallback |
| `last_model` | requested id of the rung that answered |
| `last_model_version` | provider `modelVersion`, or `None` when absent |
| `last_served_model` | `modelVersion` when present, otherwise the requested id |
| `max_elapsed` | effective per-row budget in seconds |

`vision_fallback` events also carry `served_model`, `model_version`, and
`max_elapsed`.

The fallback rung requests `gemini-flash-latest`, the same alias the served Node
adapter declares in `src/adapters/vision.gemini.ts`; the previous Python value,
`gemini-2.5-flash-lite`, was retired by the provider ("no longer available to
new users"), which is why the 2026-11-02 run saw 16 rows reach the fallback and
fail with a 404. The replacement was not verified live: the key was at HTTP 429
quota, and later probes returned 404 with empty bodies for every model id, so the
shared alias is the reason to expect it to work, not a measurement.

The live header names the requested alias and the served model. `--summary-json`
carries `provider_model_versions` and `provider_model_version`: one observed
version sets and lists it; several leave `provider_model_version` `null`, list
all of them, and mark the run not a single-model measurement, because an alias
can resolve differently across calls and one name would then describe no single
run; none leaves it `null` with an empty list and the header says `served version
not reported by the provider`. `provider_model` stays the requested alias and
`effective_budget_seconds` carries the resolved budget; offline output gains no
header lines or keys.

The first attempted use, which produced no comparison because the provider
timed out, is recorded in
[live-prompt-pilot-2026-11-02.md](live-prompt-pilot-2026-11-02.md).

A live scorecard differs from the committed one in three ways, and they are
printed rather than implied:

- the header names the provider model and `PROMPT_VERSION`;
- it says the run is a dated observation, not reproducible, and not comparable
  to the offline snapshot;
- `--summary-json` adds `mode`, `provider_model`, `prompt_version`,
  `rows_requested`, `row_errors`, `rows_excluded_live` and `live_exclusions`
  without changing the existing keys or the offline summary.

A failing row is reported as `row <sample_id> failed: <error>` and the run
continues; the process exits 1 at the end and prints how many config-rows were
scored. That behaviour is intentional: a live number with a smaller, silent
denominator would be worse than no number.

**Two hard limits.** The committed fixtures were recorded with prompt `p3`,
while the adapter now reports `p4`, so a live scorecard also moves the prompt
and cannot be read as a model-only comparison. And `jp_0001` / `jp_0002` come
from UEC-Food 256, whose terms permit non-commercial research only. The harness
refuses them by licence: `select_rows` drops them, `input_for_row` raises
`LiveIneligibleRow` before any bytes are read, and the live scorecard header and
`--summary-json` record `rows_excluded_live` with the sample ids and reasons.
Their archive source also returns HTTP 403, which is a second, independent
reason the bytes are absent. The live scope is therefore 75 of the 77 published
rows by rule, not a 75-row run with two failed downloads, and the two excluded
rows are stated rather than backfilled. The rule trusts the curated
`image_license` string; it does not fetch or verify the upstream terms.

A live run with no `--limit` over the published scope is 75 calls from the 77
in-scope rows, because two are refused by licence, at the adapter's
four-second pacing: roughly 6-8 minutes and a few cents. Nothing is written to
`eval/fixtures/`.

Two such runs exist, on 2026-11-02 at the commit that added this path:

- **Full published scope, 75 rows:** 74 scored, one provider timeout named in
  `row_errors`, 4/74 answered without deferring (5.4%), Item F1 0.15, FP rate 85.6%, 25.4%
  calorie error on 1 of 2 eligible rows. Six minutes and fourteen seconds.
- **Twelve-row stratified pilot:** 3/12 answered without deferring (25%), Item
  F1 0.10, FP rate 90.9%; a rerun of the same rows answered 4/12, which is why
  the pilot is reported as a range rather than a number.

Both are worse than the offline replay on coverage, and neither is comparable
to the snapshot above: the prompt is `p4` against `p3` fixtures, the model is
the evaluation adapter's `gemini-flash-lite-latest`, and provider output varies
between runs. The selection, the tables and the limits are in
[live-observation-2026-11-02.md](live-observation-2026-11-02.md).

## Current evidence boundary

The 80 recorded provider responses are real inputs from [#3](https://github.com/zexy2/mealog/issues/3),
and this manifest uses source-backed labels where the upstream datasets provide
them. The baseline in `eval/reports/baseline.json` is deliberately retained
unchanged here; this documentation refresh does not reset it. Current
scorecards replay the **77** rows a clean clone can load (the Turkish manifest
rows are outside the published scope) and expose complete-positive-truth
eligibility separately from coverage. Seventy-two of the 77 in-scope rows are
partial truth; five complete, positive-truth rows are calorie-eligible and two
of them are covered by V3, which is the MAPE denominator. Five partial rows are
covered as well but remain outside the calorie denominator.
Identity-only rows carry Tier 3 portion truth and do not support calorie
claims.
