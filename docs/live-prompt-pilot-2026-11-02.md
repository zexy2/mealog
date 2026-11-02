# Live prompt-pilot observation — 2026-11-02

The goal was to test whether a prompt change moves perception: the [identity diagnosis](identity-diagnosis.md) attributes
177 of 331 truth items to "never perceived", meaning no candidate list contained them. A second prompt (`p5`) was added
to the live path to see whether decomposition and visible fats, oils, dressings and garnishes move that number.

No comparison was produced. The provider became unusably slow the same day, the run was stopped after twenty minutes,
and this document records the attempt and the measurement defect rather than a table that does not exist. As
[D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline) requires, a live result is an
observation, not the published baseline.

## Mechanism (shipped, default unchanged)

The adapter exposes named prompt variants through `PROMPTS` and `prompt_for_variant()`;
`PROMPT_VERSION` stays `p4`. The `p4` text is byte-identical to the pre-change tree
(`len=2551`, `sha256=5b49ee2c7cf0f38423d196da8d3041e128703ee6e093da13d6a4dc22522af7f7`),
and `server/tests/test_vision_prompt_variants.py` freezes that digest.
`eval/harness.py --prompt-variant NAME` applies only with `--live`; offline forces the
shipping variant because fixtures replay by `sample_id`. The live header and
`--summary-json` record the variant actually used, and an unknown name exits 2 before
any network call. The offline scorecard is byte-identical with and without the flag
(173 lines, empty diff), and all 83 files under `eval/fixtures/` (all are `*.json`) are unchanged.

## The candidate and its five deltas

`p5` is a bundle of five changes, not one change:

1. Composite surfaces are decomposed into visible components: `rice and meat` becomes two items, as does `chicken salad` when the parts are distinguishable.
2. Visible fats, oils, dressings, sauces, garnishes and drinks become their own items when visible or clearly implied (a glisten of oil, a dressing pool, a sauce ladle), with a small qualitative portion.
3. "Do not report garnish" is narrowed to "do not report inedible decorative leaves"; this is the enabling edit for item 2.
4. `small` and `a drizzle` are added to the `portion_hint` examples; the non-numeric rule is unchanged.
5. A new "return every item with all required schema fields" line names `surface_form`, `cooking_method`, `portion_hint`, `count`, `medium` and `confidence`.

Because the five changes shipped together, a win or a loss could not have been attributed
to one of them. Item 5 exists to make the schema-key test possible; it is not part of the
perception hypothesis.

## What the provider did

| Evidence | Result |
|---|---|
| Model alias | `gemini-flash-lite-latest` resolved to `gemini-3.5-flash-lite` |
| 6-token text request | HTTP 200 after **60.7 s**; `server-timing: gfet4t7; dur=60592`; tier `standard` |
| 8-token text request | 71.9 s time to first byte |
| `thinkingLevel` probes | 57.0 / 31.4 / 35.7 / 49.5 s (low / minimal / LOW / MINIMAL) |
| Explicit model probes | `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite`, `gemini-flash-latest` returned HTTP 404 with empty bodies |

The alias was the only model that answered, and `thinkingLevel` shows thinking was not the cause. These are one
afternoon's measurements on one machine: evidence about the provider that day, not a benchmark.

## The run

75 `en_US` rows were requested — the published scope minus the two licence-restricted
`ja_JP` rows, which were never sent. The run started at 2026-11-02T19:49:55Z and was
stopped at 2026-11-02T20:09:51Z.

`p4` logged 13 named row failures, all `Gemini request timed out`: 10 after one attempt,
2 after two, and 1 after three. No scorecard and no summary JSON exist; the process exited
143. `p5` never started. The harness logs only failures, so successful rows leave no
artifact: do not read the 13 failures as 62 successes or as proof that only 13 rows were
attempted, because without a summary the run has no denominator.

## Why it was stopped, and the budget finding

By wall clock, the 13 logged failures averaged roughly 90–100 s each. Finishing `p4` would
have taken about another 100 minutes to produce a scorecard of failures, then the same
again for `p5`.

The run was started with a wrapper that set `MAX_ELAPSED_SECONDS = 180.0` before importing
the harness. The effective budget stayed **30 s**: `max_elapsed: float = MAX_ELAPSED_SECONDS`
binds its default at function definition, so the constructor received 30, and
`min(MAX_ELAPSED_SECONDS, max(0.1, max_elapsed))` then compared 180 with 30. The failures
are shipped-path behaviour at the shipped 30 s budget, not a raised one.
[#466](https://github.com/zexy2/mealog/issues/466) covers the configurable budget, the
misattributed error, and the unrecorded provider model version.

## What this does not show

- No `p4`-versus-`p5` comparison.
- No evidence that `p5` is better or worse.
- No Item F1, coverage, false-positive rate or calorie MAPE for either prompt.
- No claim about the perception ceiling.

The prompt experiment remains open.

**What a clean re-run needs.** A responsive provider day; the #466 fix so the scorecard
names the model that actually answered and the budget it had; and a decision to split `p5`
into single-change variants or accept that the result is attributable to the bundle.
**Provenance.** The harness and adapter are the ones in this change (`--prompt-variant`
included); scoring, prompt text, pacing and fixture handling were not altered. The wrapper
described above only assigned the ineffective `MAX_ELAPSED_SECONDS` constant. No fixture was
written, and no published offline number changed.
