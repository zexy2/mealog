# Golden set — source and retrieval protocol

This set does not contain home-cooked meals, cooking sessions or new weighing.
Each manifest row records label provenance separately from image provenance and
states what each truth axis can support.

## Label contract

`truth.items[]` contains catalogue `food_id` values and the evaluator's numeric
`grams` field. Every food ID and mass field carries a provenance string with
dataset, record ID and source field. `truth_axes.identity` and
`truth_axes.portion` carry the authoritative tier and source for each axis.

For identity-only datasets, `grams: 0` is an explicit non-scoring sentinel
required by the current offline harness. It is not a mass claim. Its
`grams_provenance` says that the source did not provide mass and that the value
must not be read as a measured or assumed portion. Those rows contribute real
identity labels; they do not contribute calorie truth.

## Tiers

| Tier | Source | What it supports here |
|---|---|---|
| 1 | [Nutrition5k](https://github.com/google-research-datasets/Nutrition5k) overhead RGB and dish metadata | Identity plus scale-weighed component mass for catalogue-covered items. Dataset is CC BY 4.0. |
| 1 | [Open Food Facts](https://world.openfoodfacts.org/product/0011110107176) product label | Product identity and printed per-100g nutrition. Product images are CC BY-SA; the API does not state a version. |
| 2 | Open Food Facts serving label | Printed serving used as a portion assumption, not observed eaten mass. |
| 1 | [TurkishFoods-15](https://huggingface.co/datasets/yunusserhat/TurkishFoods-15) | Class-label identity only. The dataset card declares Apache-2.0; original image terms are not separately stated. |
| 1 | [UEC-Food 256](http://foodcam.mobi/dataset256.html) | Class-label identity only. Official terms allow non-commercial research only. |
| 3 | TurkishFoods-15, UEC-Food 256 and the text consensus row | No source mass; portion axis remains seeded/non-scoring and is not a nutrition claim. |
| 1 | [Wikimedia Commons empty plate](https://commons.wikimedia.org/wiki/File:Empty_plate_with_fork.jpg) | Empty-plate negative control. CC BY 4.0, attribution required. |

Nutrition5k selected plates contain ingredients outside this repository's
38-food en_US catalogue. The manifest records those source ingredients in
`unmapped_source_ingredients`, with their real source masses and provenance,
rather than silently dropping them. Only catalogue-covered components enter
`truth.items` and the closed-set evaluator. Nutrition5k does not publish a
cuisine field, so the six `cuisine` values on the new rows are evaluator
stratification labels; `cuisine_provenance` makes that inference explicit
instead of presenting it as dataset ground truth.

`pkg_0001` uses the product's exact identity and per-100g label fields, but the
printed 170g serving is an assumption about portion. TurkishFoods-15 and
UEC-Food 256 provide class labels without mass; their identity axis is Tier 1
and portion axis Tier 3. No plausible gram figure is substituted.

## Truth completeness

`unmapped_source_ingredients` is not a permanent verdict. The catalogue grows,
and an ingredient that was outside it at annotation time can be inside it
later. `scripts/remap_golden_ingredients.py` re-derives the mapping from the
shipped `en_US` pack by exact name/alias match only (D25): it never edits an
existing truth item, never reads predictions or fixtures, and leaves anything
without an exact match or recorded grams unmapped. In this revision it moved
202 entries into truth across 70 rows, which is why the published Item F1 moved
from 0.13 to 0.38 with no model change.

`server/tests/test_golden_manifest.py` fails if the tool finds anything left to
map, so the next catalogue addition cannot silently deflate the score.

## Fetching inputs

Images are intentionally absent from Git. Fetch them into the ignored local
directory with:

```bash
python scripts/fetch_golden_images.py
```

The script fetches every non-text sample, writes `data/golden-images/<sample_id>.*`,
and verifies `image_sha256` before atomically replacing each file. It supports
direct image URLs, the Hugging Face row API (which resolves a fresh signed image
URL at fetch time), and the official UEC ZIP through HTTP range requests. The
UEC archive is about 4.2 GB; the script downloads only its central directory and
the two selected members.

A dead source no longer aborts the rest of the fetch: the script reports every
failed row, writes the rows that did resolve, and exits non-zero. The two
`jp_*` rows currently fail because the UEC archive returns HTTP 403; see
[docs/licensing.md](../../docs/licensing.md#evaluation-fixtures) for why they are
also excluded from live provider calls.

If a source changes bytes, fetching fails with the expected and received
SHA-256. Do not update the hash mechanically: confirm the replacement source,
licence and sample identity in a human-reviewed PR first. `tr_0003` is the text
lane and therefore has no image fields.

## Sample map

- `n5k_0001`: official Nutrition5k dish `dish_1563216440`; chicken breast and white rice map, nine other source ingredients are retained as unmapped.
- `n5k_0002`: official Nutrition5k dish `dish_1562862493`; scrambled eggs only.
- `n5k_0003`–`n5k_0005`: western scrambled-egg plates, with all source components retained and scrambled eggs/oil mapped where present.
- `n5k_0006`–`n5k_0008`: Mediterranean plates; chicken breast, apple and olive oil mappings come from exact Nutrition5k ingredient names.
- `n5k_0009`–`n5k_0011`: East Asian ingredient-pattern plates with scale-weighed rice/oil labels; tofu, pork, vegetables and sauces remain unmapped when they lack an exact catalogue equivalent.
- `n5k_0012`–`n5k_0014`: South Asian ingredient-pattern plates with scale-weighed rice/oil labels; the bucket is explicitly an evaluator stratification, not a Nutrition5k class.
- `n5k_0015`–`n5k_0017`: Latin American ingredient-pattern plates with tortilla/chili/cilantro evidence and exact oil labels; non-catalogue ingredients remain unmapped.
- `n5k_0018`: other-mixed plate with scale-weighed white rice and olive oil.
- `n5k_0019`–`n5k_0024`: western scrambled-egg and Greek-yogurt plates; exact catalogue-covered masses are retained.
- `n5k_0025`–`n5k_0030`: Mediterranean chickpea, bulgur and herb patterns; exact catalogue-covered masses are retained.
- `n5k_0031`–`n5k_0041`: East Asian tofu, soy-sauce, bok-choy and rice-noodle patterns; non-catalogue ingredients remain unmapped.
- `n5k_0042`–`n5k_0054`: South Asian lentil and chickpea patterns; the bucket remains an explicit evaluator stratification, not a Nutrition5k class.
- `n5k_0055`–`n5k_0067`: Latin American tortilla, black-bean, corn, chile and cilantro patterns; non-catalogue ingredients remain unmapped.
- `n5k_0068`–`n5k_0073`: other-mixed plates selected without a dominant cuisine signal; the bucket is disclosed as evaluator stratification.
- `pkg_0001`: Open Food Facts product `0011110107176`, front label image.
- `tr_0001`, `tr_0002`: TurkishFoods-15 train rows 18 and 12; class labels are kuru fasulye and simit.
- `tr_0003`: text lane with two-rater consensus identity labels.
- `jp_0001`: UEC category 1 (`rice`).
- `jp_0002`: UEC category 174 (`pork cutlet`).
- `trap_0001`: openly licensed empty plate.

The 55 new Nutrition5k rows use the official overhead RGB URL, CC BY 4.0
licence, and a recorded SHA-256. Their Gemini observations are recorded with
`gemini-flash-lite-latest` at four-second pacing; the recorder skips matching
existing fixtures idempotently.

The committed fixtures were recorded at prompt `p3`. The adapter now reports
`p4`, so a live scorecard measures both a different prompt and a different
model; it is a dated observation, not a re-run of the offline snapshot (D24).
Only `scripts/record_golden_fixtures.py` (`make record`) writes
`eval/fixtures/`. Images and provider responses remain ignored
local artifacts. Do not reset `eval/reports/baseline.json`; adding real rows is
supposed to move coverage and error counts.
