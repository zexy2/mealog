# Live pilot observation — 2026-11-02

Two dated live-provider runs on the same day and the same commit: a
twelve-row stratified pilot, then every `en_US` row in the published scope. The
second is the first live scorecard that covers the whole published market. Both
are published because they are worse than the offline replay and because the
pilot moved between reruns.

They are **not** a new published accuracy claim: the README snapshot stays the
offline, reproducible result (D4, D23), and D24 keeps a live measurement an
observation.

## What was run

| | |
|---|---|
| Date | 2026-11-02 |
| Commit | `f94ac17` (the live path as merged in #449) |
| Command | `python eval/harness.py --configs V3 --live --manifest /tmp/pilot/manifest.jsonl --out /tmp/pilot/scorecard-live.md --summary-json /tmp/pilot/summary.json` |
| Provider model | `gemini-flash-lite-latest` (the adapter default; not the `gemini-3.6-flash` backend default) |
| Prompt version | `p4`; the committed offline fixtures are `p3` |
| Rows | 12 `en_US` rows: two per cuisine, including the `trap_0001` empty-plate negative control |
| Inputs | 12 images fetched by `scripts/fetch_golden_images.py`, each verified against the manifest SHA-256 |
| Failures | none (`row_errors: []`) |
| Calls | 12, at the adapter's four-second pacing; roughly one minute and about a cent |

The twelve rows are a subset of the 75 published `en_US` rows, chosen two per
cuisine bucket. `ja_JP` is absent because the two UEC images are both
non-commercial-research only and currently unreachable (HTTP 403); see
[licensing](licensing.md#evaluation-fixtures).

## Pilot result (V3, 12 rows)

| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within ±20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| western | 2 | 100% | 1 | 1 | 0.50 | 25.4% | 0.0% | 60.0% |
| mediterranean | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| east_asian | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| south_asian | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| latin_american | 2 | 50% | 0 | 0 | 0.00 | — | — | 100.0% |
| other_mixed | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| **overall** | **12** | **25%** | **1** | **1** | **0.10** | **25.4%** | **0.0%** | **90.9%** |

3 of 12 rows were answered without deferring, 9 asked. One row had complete
positive truth and was scored for calories: 25.4% error, outside the ±20% band.
The false-positive rate is 90.9%, against the offline replay's 88.2% at the
time (40.5% after the truth-completeness correction in D25): the gate abstains,
but a large share of the candidates it considers is not in truth.

## Full published scope (V3, 75 rows)

Same day, same commit, same model and prompt. The manifest was every `en_US`
row — the 75 rows that have a fetched, SHA-verified image. `ja_JP` is absent
for the licence reason above, so this is 75 of the 77 published rows, not a
reduced scope chosen for convenience.

| | |
|---|---|
| Command | `python eval/harness.py --configs V3 --live --manifest /tmp/pilot-full/manifest.jsonl --out … --summary-json …` |
| Rows requested | 75 |
| Scored | 74; `n5k_0056` timed out and is named in `row_errors` |
| Wall clock | 6 min 14 s (four-second pacing) |
| Exit code | 1 — the named failure, not a silent denominator |

| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within ±20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| western | 12 | 25% | 2 | 1 | 0.43 | 25.4% | 0.0% | 66.7% |
| latin_american | 15 | 7% | 0 | 0 | 0.10 | — | — | 92.3% |
| south_asian | 16 | 0% | 0 | 0 | 0.11 | — | — | 86.7% |
| east_asian | 14 | 0% | 0 | 0 | 0.04 | — | — | 95.8% |
| mediterranean | 9 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| other_mixed | 8 | 0% | 0 | 0 | 0.08 | — | — | 90.9% |
| **overall** | **74** | **5%** | **2** | **1** | **0.15** | **25.4%** | **0.0%** | **85.6%** |

Four of 74 rows were answered without deferring (5.4%), 70 asked. Against the
offline snapshot (9% coverage, Item F1 0.38, FP 40.5%) the live run answers
**less often** and scores a much lower F1 (0.15 vs 0.38). The comparison is not
sound: the prompt differs (`p3` fixtures vs `p4` adapter), the live model is not
the backend default, and D25 corrected the offline truth after these runs —
against the earlier truth the offline F1 was 0.13 and its FP rate 88.2%, which
is why the live numbers sat close to it.

Two rows had complete positive truth; only one was scored, so the calorie MAPE
is again a single-row number. `pkg_0001` (tier 2) was calorie-eligible and not
scored, which is why the tier table shows a perfect F1 for one row and no
calorie error for it.

What the full run establishes beyond the pilot: the live path scales to the
published scope, a provider timeout is isolated and reported instead of
shrinking the denominator silently, and the abstention-heavy shape of the
offline result is real rather than an artefact of fixture replay.

## Why this is an observation, not a measurement of the model

- **It moved between runs.** A first run of the same twelve rows on the same
  code answered 4 rows (33% coverage); the second answered 3 (25%). The
  identity layer is not stable at n=12, and a single run is not a sample. The
  75-row run and the 12-row run are also different subsets and cannot be
  compared to each other.
- **Prompt and model both differ from the offline snapshot.** The committed
  fixtures are prompt `p3`; the adapter is `p4`. A difference here cannot be
  attributed to the model alone.
- **Twelve rows cannot carry an accuracy claim.** One calorie-scored row is
  exactly the denominator problem the offline snapshot already flags (2/77).
- **The provider is not the delivered backend's default.** The mobile/backend
  live model is `gemini-3.6-flash`; this run used the evaluation adapter's
  `gemini-flash-lite-latest`.

What it does establish: the live path sends real images, survives without
recording, reports per-row failure state, and produces the same *shape* of
result as the offline replay. That was not true before #449.

## Reproducing

```bash
python scripts/fetch_golden_images.py          # ~35 MB into data/golden-images
python eval/harness.py --configs V3 --live --limit 12 \
  --out eval/reports/scorecard-live.md         # measurement only; never writes fixtures
```

The 12-row manifest is two rows per cuisine, in manifest order; the 75-row run
used every `en_US` row. A different subset is a different observation and must
not be compared with these tables. A live run over the full 77 published rows
is not possible: the two `ja_JP` images are licence-restricted and unreachable.
