# Live prompt comparison — 2026-11-02

The [earlier pilot](live-prompt-pilot-2026-11-02.md) produced no comparison: the provider answered
one request after 60.7 s, 13 rows timed out, and `p5` never started. The provider recovered the same
evening, so the question that pilot left open — does the `p5` bundle move perception against `p4`? —
was run twice per variant over the same live scope. Both `p5` runs land at Item F1 0.41 against
0.36–0.37 for `p4`, and coverage does not move. That is two runs per variant on one afternoon with
one served model: an observation, not a controlled experiment, and not a significance test.

## Method

Four sequential live runs, two per prompt variant, against the unmodified harness. No fixture was
written; the artifacts are four scorecards and four summaries under `/tmp/pilot2/`.

| | |
|---|---|
| Date | 2026-11-02, runs finishing 20:45Z, 20:50Z, 20:57Z and 21:02Z (local clock UTC+3) |
| Command | `python eval/harness.py --configs V3 --live --prompt-variant p4 --out /tmp/pilot2/scorecard-p4.md --summary-json /tmp/pilot2/summary-p4.json`; repeated with `p5`, `p4b` and `p5b` |
| Scope | no `--limit`: the 75 live-eligible rows of 77; `jp_0001` and `jp_0002` refused by licence in every run |
| Provider | requested `gemini-flash-lite-latest`; one served version, `gemini-3.5-flash-lite`, in every run |
| Budget | shipped 30 s per row (`effective_budget_seconds: 30.0`); 90 s request timeout |
| Failures | none: 75/75 rows scored in all four runs, `row_errors: []` |

`p4` and `p5` are the variants introduced in [#467](https://github.com/zexy2/mealog/pull/467); the
`p4` text is digest-frozen by test. `p5` is
a bundle of five changes: composite decomposition; visible fats, oils, dressings, sauces, garnishes
and drinks as items; the garnish rule narrowed to inedible garnish; two added `portion_hint`
examples; and a schema-fields reminder. The fifth is a side effect of the test, not part of the
perception hypothesis. The flag applies only with `--live`; the offline replay is unchanged.

## Results

| Variant | Run | Item F1 | Coverage | FP rate | Committed | Asked | Abstained |
|---|---|---:|---:|---:|---:|---:|---:|
| p4 | 1 | 0.37 | 12% | 39.0% | 9 | 66 | 156 |
| p4 | 2 | 0.36 | 12% | 36.8% | 9 | 66 | 161 |
| p5 | 1 | 0.41 | 13% | 41.8% | 10 | 65 | 156 |
| p5 | 2 | 0.41 | 12% | 39.1% | 9 | 66 | 158 |

Per-cuisine Item F1, run 1 and run 2 for each variant:

| Cuisine | n | p4 | p5 |
|---|---:|---|---|
| western | 12 | 0.74 / 0.75 | 0.73 / 0.75 |
| other_mixed | 8 | 0.26 / 0.23 | 0.29 / 0.29 |
| mediterranean | 9 | 0.12 / 0.12 | 0.15 / 0.15 |
| east_asian | 14 | 0.26 / 0.27 | 0.39 / 0.34 |
| south_asian | 16 | 0.18 / 0.18 | 0.26 / 0.28 |
| latin_american | 16 | 0.46 / 0.46 | 0.48 / 0.50 |

`calorie_eligible` is 2 rows in every run; `calorie_scored` is 1, 2, 2 and 2; MAPE is 25.4%, 12.7%,
12.7% and 12.7%. A MAPE over one or two rows is not interpretable and should not be quoted as prompt
quality; the columns expose the denominator.

## What changed and what did not

Coverage is flat: 12% in three runs and 13% in one. The `p5` bundle did not make the adjudicator
answer more meals, so the perception ceiling did not shift; the gain is inside rows already
committing something. The committed/asked/abstained columns say the same: 9, 9, 10 and 9 committed.

Item F1 moved, and the movement is concentrated. `east_asian` went from 0.26/0.27 to 0.39/0.34 and
`south_asian` from 0.18/0.18 to 0.26/0.28. `western`, `mediterranean` and `latin_american` are flat.
`other_mixed` reads 0.29 in both `p5` runs against 0.23 and 0.26 for `p4`, a three-to-six point move
in an eight-row bucket that is not treated as a finding.

The false-positive rate is slightly higher for `p5`: 39.1–41.8% against 36.8–39.0%. The F1 gain is
therefore not free — a larger share of what `p5` commits is not in truth.

Against the published offline V3 result (Item F1 0.38, FP rate 40.5%, 77 rows), live `p4` at
0.36–0.37 reproduces the offline F1 within 0.02, and live `p5` is 0.03 above it. The two are close on
this one afternoon. That does not validate the offline baseline, which is a different prompt on
recorded fixtures.

Four clean runs at the shipped 30 s budget also demonstrate the [#466](https://github.com/zexy2/mealog/issues/466)
fix end to end: zero `local_deadline` rows, one observed model version, and a scorecard header that
names the served model and the effective budget. The same day's earlier run recorded 13 timeouts and
produced no scorecard to name one. That contrast is about the measurement path, not about `p4` or `p5`.

## Run-to-run variation

The same prompt does not return the same scorecard. `p4` spans 0.36–0.37 on Item F1 and 36.8–39.0 on
false positives; `p5` holds 0.41 on Item F1 but spans 39.1–41.8 on false positives. The two F1 ranges
do not overlap, but two runs per variant on one afternoon cannot separate a prompt effect from
provider nondeterminism, and the FP spread shows these are samples of one model's behaviour, not
fixed prompt properties. That is why this document does not call the difference proven.

## What this does not show

- No proof that `p5` is better in general, and no significance claim at n=2.
- No attribution to one of the five bundled changes; the mechanism supports splitting them and that
  has not been done.
- No measurement of the live perception ceiling. The 2026-11-02 runs have aggregate metrics only,
  with no per-row prediction artifact, so they cannot say which items `p5` newly perceived.
- No calorie conclusion: one or two scored rows.
- No statement about a model other than `gemini-3.5-flash-lite` on this day.

## What a clean attribution needs

Two changes, and only the first is a prompt experiment. Split the bundle into single-change variants
and run each against `p4` over the same scope and run count; `--prompt-variant` already supports
naming them, so this is prompt text plus runs, not new machinery. The second is a harness change, and
it now exists: as of [#472](https://github.com/zexy2/mealog/issues/472) the harness can record
per-row predictions with `--predictions`, so a variant can be credited with the truth items it
perceived, not just an aggregate F1. No attribution run has been done yet, and the artifact alone
does not attribute anything; it is the instrument the prompt experiment still needs.

## Provenance

Four runs on 2026-11-02 through `eval/harness.py --prompt-variant`, on the unmodified harness.
Scoring, prompt text, pacing, budget and fixture handling were not altered for these runs. No
fixture was written, and no published offline number changed. The results are live observations in
the sense of [D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline), not a
revision of the baseline.
