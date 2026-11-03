# Case study: accuracy-first meal logging

Mealog turns a photo or informal text into canonical foods, explicit portion
ranges, and catalogue-backed nutrition, and abstains or asks when the evidence
does not support an answer. This case study is written from the repository's
own evidence as of 2026-11-03. Every number is copied from the document that
owns it and linked at the point of use; claims the repository cannot verify are
not made.

The short version: on the published offline replay the system answers 7 of 77
rows without deferring, all seven go to review, and 70 ask. That is a coverage
decision, not an accuracy claim.

## 1. The problem

A meal photo contains pixels, not a food identity, a mass, or a nutrient value.
Turning it into a saved meal requires four decisions, each able to fail
silently if the product prefers a complete-looking answer:

- **Identity is closed-set.** Grounded nutrition needs a catalogue `food_id`.
  If retrieval and resolution cannot produce one, the result is `ABSTAIN`, not
  a generated food name ([README](../README.md#the-problem-it-solves)).
- **Nutrition is grounded.** Values come from catalogue rows and arithmetic over
  a resolved mass; the model does not emit a nutrient number ([D1](decisions.md)).
- **Uncertainty is visible.** A portion is grams plus a p10–p90 band, with
  source and provenance, not a hidden point estimate
  ([README](../README.md#the-problem-it-solves)).
- **The gate can ask.** Server-side routing chooses `auto_accept`, `review` or
  `ask`; a plausible nearest match is not accepted merely because it exists
  ([architecture](architecture.md#2-grounded-seven-stage-pipeline)).

The optional estimate lane exists only after the grounded lane returns
`ABSTAIN`. It is a separate product lane: model-generated ranges and
assumptions, labelled `llm_unverified_estimate`, requiring explicit user
acceptance, never routed to `auto_accept`, and excluded from grounded
evaluation ([D19](decisions.md#d19--unverified-llm-nutrition-is-a-separate-product-lane-never-grounded-truth),
[D20](decisions.md#d20--prepare-unresolved-item-estimates-as-one-bounded-batch)).

## 2. Architecture

```text
photo or text
    -> vision adapter (live provider, or recorded fixture)
       observations only: labels, count hints, capture medium
    -> normalize -> retrieve -> resolve -> portion -> nutrition -> gate
                                              |-> Day (auto_accept)
                                              |-> Review (review)
                                              |-> ask (ask/ABSTAIN)

ABSTAIN -> optional estimate lane -> explicit user acceptance (never auto_accept)
```

The served API is NestJS/TypeScript. The same framework-free pipeline modules
are driven by the Python evaluation harness through an eval CLI, so scoring and
served logic are compared on the same recorded fixtures
([D12](decisions.md#d12--nodejs--typescript-backend-nestjs-edge-python-eval-harness)).
Python is offline evaluation and reference tooling, not the delivered backend
([README](../README.md#architecture)).

| Stage | Kind | Output | Boundary |
|---|---|---|---|
| Perception | model adapter | Labels, count hints, medium | No canonical IDs, no nutrients |
| Normalize | deterministic | Normalized text and units | Locale behaviour comes from packs |
| Retrieve | deterministic | Ranked candidates | TF-IDF; negative aliases cap known confusions |
| Resolve | deterministic | Catalogue `food_id` or `ABSTAIN` | No generated food IDs |
| Portion | deterministic | Grams, p10–p90, source, provenance | Missing evidence widens the band or asks for a count |
| Nutrition | deterministic | Catalogue values × resolved mass | Only grounded nutrition producer |
| Gate | deterministic | `auto_accept`, `review`, `ask` | Routes on the weakest item, portion, count and medium signal |

The gate is server-authoritative: the mobile client does not infer acceptance
locally ([README](../README.md#the-problem-it-solves)). The current
`auto_accept` threshold is 0.75; `effectiveConfidence` takes the minimum of
identity, portion and count confidence, and a count read from a photo caps item
confidence at 0.60
([architecture](architecture.md#2-grounded-seven-stage-pipeline)). The estimate
lane accepts one to twenty items, times out after 20 seconds, and returns no
numeric fallback on provider or quota failure
([architecture](architecture.md#4-optional-unverified-estimate-lane)).

## 3. Evidence

The offline evidence is a replay of **80 recorded, non-synthetic provider
responses**
([STATUS](submission/STATUS.md#deliverables); [evaluation](evaluation.md#current-replay-and-v3-decomposition)).
The published scope is **77 rows**: three Turkish rows are excluded because
their catalogue is licence-restricted and a clean clone cannot load it
([evaluation](evaluation.md#evidence-scope-and-the-checked-readme-contract)).

| Measurement | Value | Owning evidence |
|---|---|---|
| Recorded provider responses | 80 | [STATUS](submission/STATUS.md), [evaluation](evaluation.md#current-evidence-boundary) |
| Golden samples / published rows | 80 / 77 | [evaluation](evaluation.md#golden-set) |
| V3 rows proposed for review / asked | 7/77 / 70/77 | [README](../README.md#evidence-snapshot) |
| V3 rows auto-accepted | 0/77 | [evaluation](evaluation.md#headline-and-per-sample-metrics) |
| V3 grounded coverage | 9% | [README](../README.md#evidence-snapshot) |
| V3 Item F1 / false-positive rate | 0.38 / 40.5% | [evaluation](evaluation.md#current-replay-and-v3-decomposition) |
| V3 calorie MAPE | 12.7% on 2/2 rows | [README](../README.md#evidence-snapshot) |
| Truth items never named by the model | 177/331 (53.5%) | [identity diagnosis](identity-diagnosis.md#where-the-truth-items-go) |
| Ceiling of a perfect resolver | Item F1 0.64 | [identity diagnosis](identity-diagnosis.md#where-the-truth-items-go) |

Two readings matter more than the headline. Retrieval is not the weak measured
layer: 38 variants, 30/30 positive Recall@1, MRR 1.000 and 0/8 absent-food
false accepts. The weak layer is perception and closed-set matching over
photographed food, which is why the gate abstains. And the 0.38 F1 is bounded
by what the model named: 177 of 331 truth items never entered a candidate list,
so even a perfect resolver over the named set would reach at most 0.64
([README](../README.md#evidence-snapshot); [identity diagnosis](identity-diagnosis.md#where-the-truth-items-go)).

The live evidence is separate and dated. Across the two live prompt
comparisons, `p4` scores Item F1 **0.36–0.39** and `p5` **0.41–0.42** (overall
0.36–0.42), with coverage staying in a 9–13% band across the two dated
comparisons
([2026-11-03](live-prompt-attribution-2026-11-03.md#per-cuisine);
[2026-11-02](live-prompt-comparison-2026-11-02.md#results)). Live coverage is
capped at **75 of the 77 published rows** by the licence allowlist: `jp_0001`
and `jp_0002` are refused before any image bytes are read
([licensing](licensing.md#evaluation-fixtures)).

The item-level attribution resolves a question the row-level metrics could not.
Between `p4` and `p5`, 14 truth items newly entered candidate lists and 6 left;
8 of the new items were answered immediately, 6 stayed perceived but
uncommitted, and 8 already-perceived items were committed. Gross movement into
`resolved` was 16 items, with a net of **+13 resolved** (`p4` 89 → `p5` 102).
Both new perception and new commitment contributed
([attribution](live-prompt-attribution-2026-11-03.md#flows-between-classes)).
The gain was not free: false positives rose from 50 to 67, and **78–84% of false
positives are foods the model itself named** (39/50, 36/44, 54/67, 58/69), so
most of the error is upstream of candidate scoring and the accept threshold
([attribution](live-prompt-attribution-2026-11-03.md#false-positives)).

## 4. Decisions that carry the argument

| Decision | What it establishes | What it costs or limits |
|---|---|---|
| **D23** — published snapshot is the clean-clone snapshot | The README numbers are the output of the two evaluations on a clean clone; `eval/locale_scope.py` owns scope and `scripts/check_readme_claims.py` fails CI on disagreement | The headline is worse; 3 golden rows and 107 retrieval variants are named but unmeasured ([D23](decisions.md#d23--the-published-snapshot-is-what-a-clean-clone-reproduces), [scope](evaluation.md#evidence-scope-and-the-checked-readme-contract)) |
| **D24** — a live measurement is an observation, not the baseline | `make eval-live` writes a dated scorecard and never touches `eval/fixtures/`; only `make record` writes fixtures; failed rows are named, not dropped | A live number is not reproducible and cannot be compared with the offline snapshot ([D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline)) |
| **D25** — golden truth is re-derived, not remembered | Exact equality against a food id, name or existing alias; no fuzzy match, no model judgement, no reading fixtures or predictions; a test asserts nothing is left to remap | F1 moved 0.13 → 0.38 with no model change; a future catalogue addition needs human remapping ([D25](decisions.md#d25--golden-truth-is-re-derived-from-the-catalogue-not-remembered)) |
| **Live licence allowlist** | Closed set: CC BY 4.0, CC BY-SA, Apache-2.0; fails closed; `select_rows` and `input_for_row` both refuse, the latter before reading bytes | Trusts the curated `image_license` string; upstream terms are not fetched ([licensing](licensing.md#evaluation-fixtures)) |
| **30 s budget** | Explicit argument, then `GEMINI_MAX_ELAPSED_SECONDS`, then 30 s; invalid values raise; no hidden ceiling; bounds retries and fallbacks, not the first answer | A single request may use the 90 s timeout, so the total bound is one timeout past the budget ([evaluation](evaluation.md#live-budget-and-failure-attribution)) |

**Fallback parity between TypeScript and Python.** The evaluation adapter's
fallback rung requests the same model alias the served Node adapter declares.
The previous Python value had been retired by the provider, which is why the
2026-11-02 run saw 16 rows reach the fallback and fail with a 404. The
replacement was not verified live, because the key was at quota; the shared
alias is the reason to expect it to work, not a measurement
([evaluation](evaluation.md#live-budget-and-failure-attribution)). More broadly,
the TypeScript port is gated on parity: the scoring code does not change, so the
same recorded fixtures must produce the same scorecard with the pipeline as the
only variable ([D12](decisions.md#d12--nodejs--typescript-backend-nestjs-edge-python-eval-harness)).

**The prediction artifact and comparison tool.** `--predictions` writes one
JSONL line per attempted live row, with perceived items, up to three candidates,
truth and predicted ID sets, and the row error. It is live-only and contains no
image bytes, base64, absolute paths or API key. `eval/compare_predictions.py`
classifies each truth item as resolved, perceived or absent and reports flows
between two artifacts ([evaluation](evaluation.md#live-measurement)). This
instrument turned the `p4`/`p5` question from a scalar comparison into an
item-level one.

## 5. Failure and limits

| Limit | Evidence |
|---|---|
| **The seven review proposals are not adjudicated.** Capped at 0.60 item confidence against the 0.75 threshold, so none is auto-accepted; that prevents a silent commit but does not prove the proposed item correct. The 40.5% FP rate includes unsupported proposals on deferred rows and is not a silent-commit rate | [README](../README.md#evidence-snapshot) |
| **Olive oil is one third of the never-perceived gap, not the whole gap.** `us.olive_oil` is 65 of 331 truth items and 61 of the 177 never-named items (34.5%) at a median 3.9 g; cooked kale is 16 at 3.2 g. Excluding added fat lifts the measured ceiling 0.635→0.721 and still leaves 116 never-perceived, so about one third of the gap is added fat and two thirds survives every exclusion. Live, olive oil is absent 62 times in both `p4` and `p5`; no second headline denominator is published | [visible-ingredient ceiling](visible-ingredient-ceiling-2026-11-03.md), [identity diagnosis](identity-diagnosis.md#never-perceived-by-food) |
| **n=2 live runs per variant per day.** Two runs per variant on one afternoon, one served model, one scope; no significance test. Same-prompt pairs move 7–9 items into `resolved` and lose 6, so some cross-prompt movement is indistinguishable from churn | [comparison](live-prompt-comparison-2026-11-02.md#run-to-run-variation), [attribution](live-prompt-attribution-2026-11-03.md#same-prompt-noise) |
| **No attribution to one of the five `p5` changes.** The bundle was composite decomposition, visible fats/oils/dressings/sauces/garnishes/drinks as items, a narrowed garnish rule, two added `portion_hint` examples and a schema reminder. It is now split into `p5a`–`p5e`, one change each, with tests and a documented run command; **no live run of the variants has happened yet**, so the attribution remains open | [prompt variants](prompt-variants-2026-11-03.md), [comparison](live-prompt-comparison-2026-11-02.md#what-this-does-not-show) |
| **Fixtures do not measure the served default.** Recorded with `gemini-flash-lite-latest` and prompt `p3`; served Node default is `gemini-3.6-flash` and the adapter reports `p4`. Live runs requested `gemini-flash-lite-latest` and were served `gemini-3.5-flash-lite` | [README](../README.md#remaining-limitations) |
| **No device execution, Loom playback, or email delivery in the repository.** Status marks mobile partial, Loom not started, email outside the repository; it does not certify external state. No public deployment URL either | [STATUS](submission/STATUS.md#is-this-ready-to-submit), [README](../README.md#remaining-limitations) |
| **No fine-tuning.** A plan exists; no training run, checkpoint or promotion path, and correction telemetry is a process-local prototype | [STATUS](submission/STATUS.md#deliverables), [architecture](architecture.md#6-correction-telemetry-and-future-learning) |

## 6. What I would do next

1. **Run the single-change variants against the same `p4` baseline, scope and
   run count.** `p5a`–`p5e` exist with tests and a documented command, but no
   live run has happened yet; the instrument is `--prompt-variant`,
   `--predictions` and `eval/compare_predictions.py`. The olive-oil analysis
   rules out a second headline metric rather than deferring that question.
2. **Hand-adjudicate the seven review proposals** against their source images
   and truth, and publish whether each proposal was right. The current gate
   prevents silent commits; this would measure whether the deferred proposals
   are useful.
3. **Close the external evidence gaps**: a current physical-device run, a Loom
   share URL, and confirmation of email composition and receipt. The status file
   already names all three as operator-confirmed rather than repository-proven.

## 7. Where the evidence lives

| Question | Document |
|---|---|
| What is measured, and how the metrics are defined | [docs/evaluation.md](evaluation.md) |
| Per-item attribution of offline errors | [docs/identity-diagnosis.md](identity-diagnosis.md) |
| Why the published numbers are the clean-clone numbers | [D23](decisions.md#d23--the-published-snapshot-is-what-a-clean-clone-reproduces) |
| Why a live run is not the baseline | [D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline) |
| Why the F1 changed from an annotation fix | [D25](decisions.md#d25--golden-truth-is-re-derived-from-the-catalogue-not-remembered) |
| Live `p4`/`p5` comparison, 2026-11-02 | [docs/live-prompt-comparison-2026-11-02.md](live-prompt-comparison-2026-11-02.md) |
| Live item-level attribution, 2026-11-03 | [docs/live-prompt-attribution-2026-11-03.md](live-prompt-attribution-2026-11-03.md) |
| Single-change prompt variants, design and run command | [docs/prompt-variants-2026-11-03.md](prompt-variants-2026-11-03.md) |
| Olive-oil decomposition and ceiling sensitivity | [docs/visible-ingredient-ceiling-2026-11-03.md](visible-ingredient-ceiling-2026-11-03.md) |
| Data licences and the live allowlist | [docs/licensing.md](licensing.md) |
| Generated deliverable status and verification boundary | [docs/submission/STATUS.md](submission/STATUS.md) |
| Security scope and enforced build controls | [SECURITY.md](../SECURITY.md) |
| System boundaries above the pipeline | [docs/architecture.md](architecture.md) |
| Regression baseline values | [eval/reports/baseline.json](../eval/reports/baseline.json) |
