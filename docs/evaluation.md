# Evaluation methodology

> **Headline result.** The system knows what it measured and refuses to guess
> beyond it. On the published 77-sample replay it commits on 7 samples and defers
> on 70; the gate is deliberately conservative, and the weakest cuisine bucket is
> reported rather than averaged away. Read the numbers below as a measurement
> of limits, not as a product accuracy claim.

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
numbers (9% coverage instead of 12%, Item F1 0.13 instead of 0.15), and
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
sample is covered when it neither abstains nor asks the user for clarification;
a sample is calorie-eligible only when its truth is complete and its total
calories are positive. Coverage is reported next to MAPE because they describe
a risk–coverage trade: a system can lower its error by answering only the cases
it is willing to commit to.
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
its truth is identity-only; a bucket with `coverage = 0%` has no committed
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
calorie-eligible samples. The V3 coverage is **9%** (**7/77** committed
samples), while **70/77** samples ask for clarification. These are current
outputs of `python eval/harness.py`, not claims about unmeasured provider
behaviour.

| Config | Worst-cuisine MAPE | Mean MAPE | Spread | Coverage | Calorie eligible | Calorie scored | Item F1 | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 | 100.0% (western) | 100.0% | 1.00x | 100% | 2 | 2 | 0.00 | 100.0% |
| V1 | 12.7% (western) | 12.7% | 1.00x | 42% | 2 | 2 | 0.12 | 90.5% |
| V2 | 12.7% (western) | 12.7% | 1.00x | 42% | 2 | 2 | 0.12 | 90.5% |
| V3 | 12.7% (western) | 12.7% | 1.00x | 9% | 2 | 2 | 0.13 | 88.2% |

The current V3 cuisine slices are:

| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| western | 12 | 33% | 2 | 2 | 0.43 | 12.7% | 50.0% | 66.7% |
| east_asian | 16 | 6% | 0 | 0 | 0.10 | — | — | 90.0% |
| other_mixed | 8 | 0% | 0 | 0 | 0.08 | — | — | 91.7% |
| mediterranean | 9 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| south_asian | 16 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| latin_american | 16 | 12% | 0 | 0 | 0.06 | — | — | 95.7% |
| **overall** | **77** | **9%** | **2** | **2** | **0.13** | **12.7%** | **50.0%** | **88.2%** |

The same V3 calculations by conservative overall tier are:

| Ground-truth tier | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tier_1 | 74 | 8% | 1 | 1 | 0.12 | 25.4% | 0.0% | 89.3% |
| tier_2 | 1 | 100% | 1 | 1 | 1.00 | 0.0% | 100.0% | 0.0% |
| tier_3 | 2 | 0% | 0 | 0 | 0.40 | — | — | 66.7% |
| **overall** | **77** | **9%** | **2** | **2** | **0.13** | **12.7%** | **50.0%** | **88.2%** |

> **Methodological Context on False Positive (FP) Rate:** The 88.2% FP rate is
> measured across every sample in scope and counts rejected and abstained
> proposals, not only committed ones. Most counted false positives are unmapped
> recipe ingredients (olive oil, seasoning) in multi-dish reference recipes: the
> perception layer observed them correctly, but the canonical single-dish
> catalogue does not map them. And 70 of the 77 samples ended in a safe `ask`, so
> no ungrounded candidate reached the user's log. The rate is a property of the
> identity layer's proposals, not evidence that 88% of logged meals were wrong.

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
commits are `n5k_0003`, `n5k_0005`, `n5k_0010`, `n5k_0016`, and `n5k_0058`.
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

The current harness commits **7/77** samples and routes **70/77** to `ask`, for
**9% coverage** after integer percentage formatting. `E12=70` is generated by
the same replay. This is the current measurable statement: the safe gate trades
substantial coverage for fewer silent commits.

An older hand-written catalogue-versus-threshold decomposition was removed
because it described a 12-commit run and had no checked-in generator tying its
counts to the current replay. The present scorecard does not expose enough
information to assign the 70 deferrals to those causal buckets without a new,
reproducible report. No threshold or catalogue value is changed here.

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

For the current V3 replay on **n=77**, the observable tag counts are `E3=61`,
`E4=69`, `E7=10`, `E12=70`, and `unclassified=74`; the other eight codes are
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
python scripts/fetch_golden_images.py       # ~30 MB into data/golden-images
python eval/harness.py --configs V3 --live --limit 10 \
  --out eval/reports/scorecard-live.md      # measurement only
make record                                 # the only writer of eval/fixtures
```

`--live` uses the same manifest rows as the offline run: each row's image bytes
and media type are sent to the adapter, or its text when the row is the text
lane. `--manifest`, `--images-dir` and `--limit` bound the run; `--limit N`
applies after scope filtering, in manifest order.

A live scorecard differs from the committed one in three ways, and they are
printed rather than implied:

- the header names the provider model and `PROMPT_VERSION`;
- it says the run is a dated observation, not reproducible, and not comparable
  to the offline snapshot;
- `--summary-json` adds `mode`, `provider_model`, `prompt_version`,
  `rows_requested` and `row_errors` without changing the existing keys.

A failing row is reported as `row <sample_id> failed: <error>` and the run
continues; the process exits 1 at the end and prints how many config-rows were
scored. That behaviour is intentional: a live number with a smaller, silent
denominator would be worse than no number.

**Two hard limits.** The committed fixtures were recorded with prompt `p3`,
while the adapter now reports `p4`, so a live scorecard also moves the prompt
and cannot be read as a model-only comparison. And `jp_0001` / `jp_0002` come
from UEC-Food 256, whose terms permit non-commercial research only; their
archive source returns HTTP 403, and the images must not be uploaded to a
third-party API. Live coverage is therefore at most 75 of the 77 published
rows, and the two missing rows are stated rather than backfilled.

A live run with no `--limit` over the published scope is 77 calls at the
adapter's four-second pacing: roughly 6-9 minutes and a few cents. Nothing is
written to `eval/fixtures/`.

Two such runs exist, on 2026-11-02 at the commit that added this path:

- **Full published scope, 75 rows:** 74 scored, one provider timeout named in
  `row_errors`, 4/74 committed (5.4%), Item F1 0.15, FP rate 85.6%, 25.4%
  calorie error on 1 of 2 eligible rows. Six minutes and fourteen seconds.
- **Twelve-row stratified pilot:** 3/12 committed (25%), Item F1 0.10, FP rate
  90.9%; a rerun of the same rows committed 4/12, which is why the pilot is
  reported as a range rather than a number.

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
partial truth and two complete, positive-truth rows are calorie-eligible; five
partial rows are covered by V3 but remain outside the calorie denominator.
Identity-only rows carry Tier 3 portion truth and do not support calorie
claims.
