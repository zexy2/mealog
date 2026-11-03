# Visible-ingredient ceiling — 2026-11-03

The 0.64 perfect-resolver ceiling in [identity-diagnosis.md](identity-diagnosis.md)
is not one phenomenon. `us.olive_oil` is 65 of 331 truth items and 61 of the 177
never-perceived items (34.5% of that gap); excluding it lifts the ceiling to
0.721, about a quarter of the distance to 1.0, but 116 items are still never
perceived. Removing every item under 10 g as well leaves 52 never-perceived
items and a ceiling of 0.834, and most of the rest is plated food, much of it
large and visible: rice, chickpeas, pork, chicken. Item F1 stays 0.38 and the
published ceiling stays 0.64.

## Method

Read-only replay on a clean checkout of `main` at `1a4470b` (branch
`docs/visibility-ceiling-481`), using only the committed manifest, fixtures and
catalogue: no live call, no network, no change to `eval/identity_diagnosis.py`,
the manifest, fixtures or published numbers. It reproduces the report exactly:

```bash
python eval/identity_diagnosis.py --json /tmp/identity.json
```

331 truth items, 91 resolved, 39 gating, 24 ranking, 177 never perceived,
ceiling `2*154/(2*154+177) = 0.635`, TP/FP agreement 91/62.

A throwaway `/tmp` script (not committed) imports the committed `harness`,
`normalize`, `retrieval`, `resolve` and `make_vision("fixture")` used by
`diagnose()`. It runs the same 77 in-scope rows (`en_US`, `ja_JP`; `tr`
excluded) and records one outcome per truth item in the diagnosis's order:
resolved; else never perceived if no candidate list contains it; else gating if
top-1; else ranking. Masses come from `truth.items[].grams`; each filter
recomputes `R` and `N` and applies `2R/(2R+N)`. Two zero-gram sentinels
(`jp.rice_steamed`, `jp.tonkatsu`) are retained.

## Roles

The manifest has no role field. Roles are **inferred from the food id**; mass is
context, not the role — the only heuristic here.

| Role | Rule used | Truth items | Never perceived | Median never g |
|---|---|---:|---:|---:|
| Cooking medium/oil | a fat or oil added to the dish, not served as a portion | 65 | 61 | 3.88 |
| Dressing/sauce | pourable condiment; no in-scope truth id is one | 0 | 0 | — |
| Garnish/herb | herb or leaf used only as garnish; no in-scope truth id is one | 0 | 0 | — |
| Plated component | a named food served on the plate, including composites | 266 | 116 | 7.12 |
| Other | neither of the above; no in-scope truth id qualifies | 0 | 0 | — |
| **Total** | | **331** | **177** | |

`us.olive_oil` is the only added fat in the shipped catalogue and the only food
in the cooking-medium row. Raw leaves stay plated components even at small
mass: a 3.2 g `us.arugula_raw` item would look like a garnish by grams alone,
but reclassifying it because the number is small is the move this document
refuses. The row means added fat, not a verified cooking method.

## Where the gap is concentrated

`us.olive_oil` appears once on 65 of the 77 scoped rows: 65 of 331 truth items
(19.6%) and 61 of 177 never-perceived items (34.5%). Its mass runs 0.25–24.0 g,
median 3.88 g; 34 of the 61 are below 5 g and 19 below 2 g. The top five
never-perceived foods are 115 of 177 items (65.0%):

| Food | Never perceived | Median source g | Share of never |
|---|---:|---:|---:|
| `us.olive_oil` | 61 | 3.88 | 34.5% |
| `us.rice_white_cooked` | 20 | 10.18 | 11.3% |
| `us.kale_cooked` | 16 | 3.23 | 9.0% |
| `us.tomatoes_cooked` | 10 | 6.69 | 5.6% |
| `us.chickpeas_cooked` | 8 | 15.04 | 4.5% |

Mass does not separate invisible from missed: 76 of 177 never items (42.9%)
have recorded mass below 5 g and 29 below 2 g, but the never list also includes
`us.pork_roasted` (75.1 g), `us.tofu_firm` (72.5 g), `us.chicken_breast_grilled`
(48.5 g) and `us.yogurt_greek_plain` (42.6 g), which a photograph can show.

## Sensitivity

Each row excludes every truth item matching the definition, reachable and
never-perceived alike, then recomputes the ceiling; "change" is against the
baseline. **These are sensitivity cuts, not a new definition of truth**: no
manifest item is removed and `identity-diagnosis.md` does not move.

| Definition | Truth items | Reachable | Never perceived | Ceiling | Change |
|---|---:|---:|---:|---:|---:|
| Baseline, all items | 331 | 154 | 177 | 0.635 | — |
| Exclude `us.olive_oil` | 266 | 150 | 116 | 0.721 | +0.086 |
| Exclude cooking oils/mediums (`us.olive_oil`) | 266 | 150 | 116 | 0.721 | +0.086 |
| Exclude items < 2 g | 299 | 151 | 148 | 0.671 | +0.036 |
| Exclude items < 5 g | 241 | 140 | 101 | 0.735 | +0.100 |
| Exclude items < 10 g | 195 | 132 | 63 | 0.807 | +0.172 |
| Exclude oil and items < 10 g | 183 | 131 | 52 | 0.834 | +0.199 |

The < 2 g cut moves least because it removes 29 never items but only 3
reachable ones; < 10 g removes 114 never but also 22 reachable. The ceiling
rises because removed misses outnumber hits, not because the model improved.

**What survives every exclusion.** With the oil and every item under 10 g
removed, 183 truth items and 131 reachable remain, 52 never, ceiling 0.834.
Those 52 are substantial plated food: rice 12, chickpeas 6, pork 5, apple 4,
chicken 4, tomatoes 3, kale 3, yogurt 3, mushrooms 3, tofu 2, beef 2. The 0.64
was under-decomposed, not wrong: one third is invisible fat; the other two
thirds are a real gap on plated food, not a label artefact.

## Recommendation

**Do not publish a second headline denominator, and do not call any
denominator "image-inferable" from this data.** The only exclusion defensible
from the committed label is added fat, and it leaves 116 never-perceived items;
mass cuts that approximate visibility also delete 22 reachable items, so the
denominator would be tuned by the result. The honest change is editorial: state
the oil decomposition beside the existing ceiling while Item F1 and 0.64 remain
the published numbers. If a secondary view is wanted later, the defensible one
is "excluding added fats" (0.721), generated from committed fixtures, labelled
secondary with its rule and count, and never presented as model accuracy.

**Risk.** Excluding hard items is the easiest way to flatter a model. The
< 10 g row raises the ceiling by 0.172 and removes 22 truth items the system
resolves; no model or gate changed. Any second denominator must be named and
sit beside the primary; one that appears only in a headline describes the
denominator.

## What would change the conclusion

- **Role annotations.** Cooking aid versus dressing would split the category;
  it would still be invisible.
- **Visible-oil images.** Sheen or a pooled drizzle is visible; a detector
  would move the 61 items back into the denominator.
- **A different label policy.** Excluding added fats from truth would change
  truth, not the model, and need a D25-style republish.
- **Portion truth.** Presence-only oil truth removes the mass question, not the
  visibility one.
- **Better perception.** The 52 survivors are what a better model can move; if
  they fall, the rest is a label problem.

## Related

[identity-diagnosis.md](identity-diagnosis.md) holds the frozen counts;
[evaluation.md](evaluation.md#where-the-identity-errors-come-from) places the
ceiling in the published evaluation; [D25](decisions.md#d25--golden-truth-is-re-derived-from-the-catalogue-not-remembered)
says truth comes from the catalogue, which this document does not edit.

72 of 77 scoped rows carry a non-empty `unmapped_source_ingredients` list (885
entries, including salt, garlic, vinegar and parsley). Those are not used to
change truth; they point the same way as the oil finding, because mapping more
of the recipe would add more non-visible items.
