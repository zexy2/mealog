# Installing the Turkish pack for local verification

The Turkish catalogue is not committed (TürKomp is `restricted-noncommercial`).
To run the Turkish half of the suite:

```sh
export TR_PACK_SOURCE=/path/to/folder-with-three-jsonl-files
make pack                # or: python scripts/install_restricted_pack.py --source "$TR_PACK_SOURCE"
cd server && npm test    # the fixture picks up locale_packs/tr automatically
```

`npm test` copies `locale_packs/` into a temporary fixture at start-up, so the
tracked tree is never modified. Tests that need the full Turkish catalogue
skip with a named reason when it is absent, and every gate that does not need
Turkish data (`make check`, CI) passes on a clean clone.
