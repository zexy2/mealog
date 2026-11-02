# Turkish locale pack: metadata only

This directory ships the Turkish pack's **metadata**, not its data.

`foods.jsonl`, `aliases.jsonl` and `units.jsonl` are not in the repository. They
contain 57 selected rows derived from TürKomp, which permits conditioned
noncommercial sharing and requires a separate agreement for commercial use.
Committing them under the repository's MIT grant would offer them on terms the
source does not allow, so they are installed separately:

```sh
python scripts/install_restricted_pack.py --source <directory|zip|https-url>
```

The installer validates the three files and writes them here. They are ignored
by Git, and `python scripts/check_licence_boundary.py` fails if they ever reach
the tracked tree. Without them the Turkish locale is defined but not loadable:
the API answers `503` for `locale: "tr"` and everything else keeps working.
`en_US` and `ja_JP` ship in full.

Required attribution:

> TürKomp, Ulusal Gıda Kompozisyon Veri Tabanı, versiyon 1.0,
> <https://turkomp.tarimorman.gov.tr/>

Read the [official TürKomp data-use conditions](https://turkomp.tarimorman.gov.tr/useofdata)
before copying, redistributing, or using this pack.

The data rows identify TürKomp as their source. The following are mealog
metadata, not official TürKomp fields:

- `food_id`
- transliterated or display labels
- aliases and negative aliases
- serving defaults and density annotations
- retrieval, portion, and confidence behavior

This subset is not a complete or guaranteed-current copy of TürKomp. The source
database and its official conditions remain authoritative. See the repository-
level [licensing notice](../../docs/licensing.md) for the full boundary.
