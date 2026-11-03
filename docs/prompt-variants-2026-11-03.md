# Single-change prompt variants — 2026-11-03

The `p5` prompt is a bundle of five changes, and the 2026-11-03 attribution run cannot say
which of them moved Item F1. This document defines five opt-in variants, `p5a`–`p5e`, each of
which is `p4` plus exactly one of those changes. It records the design and the command to run
one variant. **No live run of these variants has happened yet**, so there is no result here,
only a way to get one.

See [live-prompt-attribution-2026-11-03.md](live-prompt-attribution-2026-11-03.md) for why the
split is needed: between `p4` and `p5`, both new perception and new commitment moved, and the
bundled prompt cannot attribute either movement to a specific rule.

## The five changes

1. **Composite decomposition.** `p4` asks for one item per distinct primary prepared dish.
   `p5a` instead asks the model to decompose composite surfaces into their visible components
   and return one item per component. This can add items that `p4` treated as one dish.
2. **Visible fats, oils, dressings, sauces, garnishes, and drinks.** `p5b` adds a rule that
   these are their own items when visible or clearly implied, with a small portion. This can
   change both what is perceived and what is committed.
3. **Garnish rule.** `p4` excludes "garnish, decorative leaves"; `p5c` narrows that to
   "inedible decorative leaves". This can add edible garnish as an item without touching the
   decomposition rule.
4. **`portion_hint` examples.** `p5d` extends the qualitative examples with `small` and
   `a drizzle`. It changes vocabulary, not what counts as an item.
5. **Schema-fields reminder.** `p5e` inserts a sentence requiring every item to carry all six
   response fields. This can change completeness/commitment without adding a perception rule.

Each change is isolated because they act on different failure modes. Changes `a` and `b` can
add items; `c` can stop suppressing an item; `d` changes only the wording of an existing
field; `e` is a contract reminder. Running them together, as `p5`, confounds those effects.

| Variant | Change isolated |
|---|---|
| `p5a` | composite decomposition |
| `p5b` | visible fats, oils, dressings, sauces, garnishes and drinks as items |
| `p5c` | garnish rule narrowed to inedible garnish |
| `p5d` | `portion_hint` examples extended with `small` and `a drizzle` |
| `p5e` | schema-fields reminder |

`p5b` still carries `p4`'s "Do not report garnish, decorative leaves …" sentence, so the
garnish half of change `b` is partly suppressed inside `p5b`: it adds garnishes as visible
items while the old exclusion still tells the model not to report them. Treat `p5b` as a lower
bound for change `b`, and read `p5c` as the variant that isolates the exclusion itself. The
full `p5` bundle removes this contradiction, because it narrows the exclusion to inedible
garnish as well.

## How the variants are built

`server/src/mealog/adapters/vision_gemini.py` keeps `p4` (`SYSTEM_PROMPT`) and the shipping
experiment bundle `p5` (`_P5_SYSTEM_PROMPT`) byte-for-byte unchanged. The five changes are
declared as named `(old, new)` replacements on the `p4` text in `P5_EDITS`, and each variant is
constructed as:

```python
"p5a": SYSTEM_PROMPT.replace(old_a, new_a)
```

No variant is a copied prompt literal. A reviewer can read one edit and see the whole
difference; a future change to `p4` cannot silently leave five stale copies behind.

`p4` remains `PROMPT_VERSION` and the default. `p5` remains the union of all five edits. The
registry order is `("p4", "p5", "p5a", "p5b", "p5c", "p5d", "p5e")`, and an unknown name lists
all seven.

The offline test suite proves the decomposition rather than asserting it:

- applying all five edits to `SYSTEM_PROMPT` in order reproduces `_P5_SYSTEM_PROMPT` exactly;
- each `p5a`–`p5e` equals `SYSTEM_PROMPT.replace` for exactly its own edit;
- each variant differs from both `p4` and `p5`, contains its own change marker and none of the
  other four;
- the `p4` SHA-256 and length are unchanged, so the shipping prompt did not move;
- the JSON response schema is identical for every variant, and no variant drops a field name
  that `p4` already mentions. Only `p5` and `p5e` name all six fields explicitly, because the
  schema-fields reminder is what introduces `cooking_method` and `confidence` as field names.

## Running one variant live

```bash
python eval/harness.py --configs V3 --live --prompt-variant p5a --predictions /tmp/preds-p5a.jsonl
```

Add `--out` and `--summary-json` if the scorecard and summary are wanted next to the prediction
artifact. Use the same command shape for `p5b`–`p5e`, changing the variant name and the output
path each time.

**No live run of `p5a`–`p5e` has happened yet.** No prediction artifact, scorecard or summary
for these variants exists. This document is a design and a command, not a result. Any number
quoted for a variant would have to come from a run that has not been made.

## What a run would and would not show

A single live run cannot attribute a change. Live output is nondeterministic, and the
same-prompt pairs in the attribution document already move 7–9 items into `resolved` and lose
6 (see [D24](decisions.md#d24--a-live-measurement-is-an-observation-never-the-baseline)).
Attribution needs the same `p4` baseline, the same 75-row scope, the same model alias and the
same number of runs per variant as the comparison it is joined to. A variant that moves in the
same direction as its same-prompt noise is not evidence for that change; one that moves outside
it is a candidate, not a proof.

The useful outcomes are therefore:

- one change reproduces most of the `p5` move, which names the mechanism;
- no single change reproduces it, which says the effect is an interaction or noise at this
  sample size;
- several changes move in opposite directions, which explains why the bundle's net gain is
  smaller than its parts.

None of these can be claimed until the runs are made. The artifacts are not committed, and a
live measurement is an observation, never the baseline.

## Scope and verification

The change is limited to the adapter prompt registry, its variant test file, this document and
the regenerated `docs/submission/STATUS.md`. Scoring, response schema, adapter behaviour,
fixtures and the `p4`/`p5` bytes are untouched. Offline verification is the full `pytest`
suite, the variant test file, `ruff check`, `scripts/status.py --check` and the link check. No
provider was called and no network request was made while producing this document.
