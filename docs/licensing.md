# Licensing: code, data, and provenance

The software in this repository is MIT-licensed (see [`LICENSE`](../LICENSE)).
That licence deliberately does **not** extend to third-party nutrition data,
evaluation fixtures, screenshots, or trademarks. This document records the
source, attribution, and reuse boundaries for each data pack.

Read this before reusing the repository, and again before publishing a fork.
The default state of any data pack is "not mine to sublicense"; only the US
pack is public domain.

## Turkish locale pack: TürKomp

Files covered:

- `locale_packs/tr/foods.jsonl`
- project metadata that refers to those rows in `locale_packs/tr/`

Required attribution:

> TürKomp, Ulusal Gıda Kompozisyon Veri Tabanı, versiyon 1.0,
> <https://turkomp.tarimorman.gov.tr/>

Official conditions: [TürKomp data-use conditions](https://turkomp.tarimorman.gov.tr/useofdata).

The Turkish pack is marked `restricted-noncommercial`. The official conditions
allow conditioned noncommercial information sharing and require visible source
attribution for written use plus a clickable source link for internet use.
Commercial use in software or on a website requires a separate agreement with
the authorised institution. This repository does not grant that permission.

The installed catalogue holds 57 selected rows. Nutrient values identify
TürKomp as their source. Project `food_id` values, transliterated/display
labels, aliases, serving defaults, density annotations, retrieval metadata, and
confidence behavior are mealog additions; they are not represented as official
TürKomp fields. Consult the official source rather than treating this subset as
a complete or current copy of the database. None of these rows are in the
repository: what ships here is `pack.yaml`, `text_rules.yaml` and this notice.

## Japanese locale pack: unverified legacy data

Files covered:

- `locale_packs/ja_JP/foods.jsonl`
- project metadata that refers to those rows in `locale_packs/ja_JP/`

The pack originally declared [MEXT, Standard Tables of Food Composition in
Japan](https://www.mext.go.jp/a_menu/syokuhinseibun/index.htm) as its source.
Row-level review did not establish that provenance for the pack as a whole:
only 2 of 8 rows exactly matched the four checked nutrient fields in the 2015
tables, while the remaining rows did not exactly match the checked 2015, 2020,
or 2023 tables. The repository therefore does **not** present this pack as
verified MEXT data.

The pack remains marked `unverified` and is rejected in mealog commercial mode.
Its rows are retained only as legacy, non-production evaluation material until
each value has a traceable source edition and record identifier.

## US locale pack: USDA FoodData Central

Files covered:

- `locale_packs/en_US/foods.jsonl`
- project metadata that refers to those rows in `locale_packs/en_US/`

Source: [USDA FoodData Central](https://fdc.nal.usda.gov/).

The pack metadata records this source as `public-domain`. Project-specific IDs,
aliases, serving defaults, and retrieval metadata remain mealog additions.

## Evaluation fixtures

`eval/fixtures/` holds recorded provider responses. They are observations made
by Mealog during evaluation; they contain food descriptions only — no photos,
no personal identifiers, and no raw provider envelopes. They are included so the
offline scorecard can be reproduced without an API key. They are evidence of
integration, not an accuracy benchmark, and are not a data set for training.

**Images are never committed.** The golden manifest records a source URL,
licence and SHA-256 per row; `scripts/fetch_golden_images.py` writes the bytes to
the ignored `data/golden-images/`. A live measurement (`make eval-live`) uploads
those images to the configured vision provider, so the row licences have to
permit third-party processing. The harness derives live eligibility from the
manifest's `image_license` against a closed allowlist: CC BY 4.0, CC BY-SA, and
Apache-2.0. The match ignores the trailing source note, so a row is allowed by
licence *kind*; anything unrecognised, empty, or missing fails closed. Two rows
in the published scope do not qualify: `jp_0001` and `jp_0002` come from
UEC-Food 256, whose official terms allow non-commercial research only. They
also carry `"live_eligible": false`, which can subtract but never add. With
the restricted Turkish pack installed, a third row, `tr_0003` (the free-text
lane), is refused because no licence is recorded for it.

There are two independent refusals. `select_rows` drops live-ineligible rows
when it builds a live run, so `--limit` applies to eligible rows and the
scorecard header plus `--summary-json` report `rows_excluded_live` with the
sample ids and reasons. `input_for_row` then refuses the same row even when a
caller bypasses selection: it raises `LiveIneligibleRow`, naming the sample and
the licence, before it reads image bytes or builds a provider input. Live
coverage is therefore capped at 75 of the 77 published rows by a rule the code
enforces, not by the archive returning HTTP 403; the 403 is a second,
independent reason those bytes are absent. Their absence is reported, not
substituted with a re-encoded or re-sourced image.

The honest caveat is that the check trusts the curated `image_license` string
in the manifest. It does not fetch or verify the upstream terms, so adding a
source still means reading its licence and adding it to the allowlist
deliberately.

## The Turkish catalogue is installed, not committed

`locale_packs/tr/` ships its metadata (`pack.yaml`, `text_rules.yaml`) but not
its catalogue. The 57 TürKomp-derived rows are excluded from the MIT grant, and
committing them would hand the data to every cloner, so they are installed from
a licence-gated source:

```sh
python scripts/install_restricted_pack.py --source <directory|zip|https-url>
```

Before that install, `tr` is a defined but unloadable locale: the API answers
`503` and `en_US` / `ja_JP` are unaffected. After it, nothing changes for the
rest of the system — the loader reads the same files it always did.

`python scripts/check_licence_boundary.py` (`make licence`) fails if the
catalogue files ever reach the tracked tree, and is part of `make check` and CI.
Deleting the files is not enough on its own: a deleted blob stays reachable in
history, which is why the guard lives in the build rather than in a review
checklist.

## Reuse checklist

1. Want the code only? Use it under MIT; `locale_packs/tr/` ships metadata only.
2. Want the Turkish pack? Obtain the required agreement with the authorised
   institution first, then install the catalogue with
   `scripts/install_restricted_pack.py` — this repository's MIT licence does not
   provide it.
3. Want the Japanese pack? Treat it as unverified and do not ship it to users.
4. Want a new market? Add a pack with its own `pack.yaml` and `license` field;
   commercial mode refuses to load packs that are not clearly licensed.
