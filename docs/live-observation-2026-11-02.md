# Live pilot observation — 2026-11-02

A single dated live-provider run over twelve golden rows. It is published
because it is the first time the live path produced a scorecard at all, and
because its numbers are worse than the offline replay. It is **not** a new
published accuracy claim: the README snapshot stays the offline, reproducible
result (D4, D23), and D24 keeps a live measurement an observation.

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

## Result (V3)

| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within ±20% | FP rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| western | 2 | 100% | 1 | 1 | 0.50 | 25.4% | 0.0% | 60.0% |
| mediterranean | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| east_asian | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| south_asian | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| latin_american | 2 | 50% | 0 | 0 | 0.00 | — | — | 100.0% |
| other_mixed | 2 | 0% | 0 | 0 | 0.00 | — | — | 100.0% |
| **overall** | **12** | **25%** | **1** | **1** | **0.10** | **25.4%** | **0.0%** | **90.9%** |

3 of 12 rows committed, 9 asked. One row had complete positive truth and was
scored for calories: 25.4% error, outside the ±20% band. The false-positive
rate is 90.9%, matching the shape of the offline result (88.2%): the gate
abstains, but the candidates it considers are mostly wrong.

## Why this is an observation, not a measurement of the model

- **It moved between runs.** A first run of the same twelve rows on the same
  code committed 4 rows (33% coverage); this run committed 3 (25%). The
  identity layer is not stable at n=12, and a single run is not a sample.
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

The manifest subset used here is two rows per cuisine, in manifest order. A
different subset is a different observation and must not be compared with this
table.
