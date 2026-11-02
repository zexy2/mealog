#!/usr/bin/env python3
"""Move exactly-mappable golden ingredients from unmapped to truth.items.

The en_US catalogue has grown since some golden rows were first annotated.
An ingredient listed in ``unmapped_source_ingredients`` is therefore not
always outside the catalogue: it may now match a food ``id``, ``name`` or an
existing alias exactly.

This tool is deliberately conservative.  It normalises only case and
whitespace and accepts a match only when the whole ingredient name equals the
whole catalogue key.  It never looks at model predictions or fixtures, never
invents synonyms, and never changes an existing ``truth.items`` entry.  An
ingredient without source grams stays unmapped because inventing a mass would
change the measurement.

Dry-run by default::

    python scripts/remap_golden_ingredients.py
    python scripts/remap_golden_ingredients.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "eval" / "golden" / "manifest.jsonl"
PACK = REPO / "locale_packs" / "en_US"

FIELD_RE = re.compile(r"field=([^;+]+)\+([^;]+)\s*$")


def normalise(name: str) -> str:
    """Case-fold and collapse whitespace; nothing else is normalised."""
    return " ".join(name.split()).casefold()


def load_catalogue(pack: Path = PACK) -> dict[str, str]:
    """Return ``normalised name -> food_id`` for ids, names and aliases."""
    lookup: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {}

    def add(key: str, food_id: str) -> None:
        key = normalise(key)
        if not key:
            return
        previous = lookup.get(key)
        if previous is not None and previous != food_id:
            conflicts.setdefault(key, {previous}).add(food_id)
            return
        lookup[key] = food_id

    foods_path = pack / "foods.jsonl"
    for line in foods_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        food = json.loads(line)
        food_id = food["food_id"]
        add(food_id, food_id)
        add(food["name"], food_id)

    aliases_path = pack / "aliases.jsonl"
    for line in aliases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        for alias in entry.get("alias", []):
            add(alias, entry["food_id"])

    if conflicts:
        rendered = "; ".join(f"{key!r} -> {sorted(ids)}" for key, ids in sorted(conflicts.items()))
        raise SystemExit(f"ambiguous catalogue keys: {rendered}")
    return lookup


def split_provenance(provenance: str) -> tuple[str, str] | None:
    """Split ``field=X_name+X_grams`` into name and grams provenance."""
    match = FIELD_RE.search(provenance)
    if match is None:
        return None
    prefix = provenance[: match.start()]
    return f"{prefix}field={match.group(1)}", f"{prefix}field={match.group(2)}"


def find_matches(rows: list[dict], lookup: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Return proposed mappings and any inconsistencies that block applying."""
    proposals: list[dict] = []
    problems: list[str] = []
    for row in rows:
        sample_id = row["sample_id"]
        existing = {item["food_id"] for item in row["truth"]["items"]}
        added: set[str] = set()
        for ingredient in row.get("unmapped_source_ingredients", []):
            food_id = lookup.get(normalise(ingredient["name"]))
            if food_id is None:
                continue
            grams = ingredient.get("grams")
            if grams is None:
                proposals.append({
                    "sample_id": sample_id,
                    "ingredient": ingredient["name"],
                    "grams": None,
                    "food_id": food_id,
                    "action": "left_unmapped_no_grams",
                })
                continue
            if food_id in existing or food_id in added:
                problems.append(
                    f"{sample_id}: {ingredient['name']!r} maps to {food_id!r}, "
                    "which is already a truth item (duplicate)"
                )
                continue
            provenance = split_provenance(ingredient.get("provenance", ""))
            if provenance is None:
                problems.append(
                    f"{sample_id}: {ingredient['name']!r} has provenance without a "
                    "separable name+grams field"
                )
                continue
            food_id_provenance, grams_provenance = provenance
            proposals.append({
                "sample_id": sample_id,
                "ingredient": ingredient["name"],
                "grams": grams,
                "food_id": food_id,
                "food_id_provenance": food_id_provenance,
                "grams_provenance": grams_provenance,
                "action": "map",
            })
            added.add(food_id)
    return proposals, problems


def apply_proposals(rows: list[dict], proposals: list[dict]) -> list[dict]:
    """Mutate rows in place: append truth items and drop mapped ingredients."""
    by_sample: dict[str, list[dict]] = {}
    for proposal in proposals:
        if proposal["action"] == "map":
            by_sample.setdefault(proposal["sample_id"], []).append(proposal)

    for row in rows:
        mappings = by_sample.get(row["sample_id"])
        if not mappings:
            continue
        matched_names = {mapping["ingredient"] for mapping in mappings}
        for mapping in mappings:
            row["truth"]["items"].append({
                "food_id": mapping["food_id"],
                "food_id_provenance": mapping["food_id_provenance"],
                "grams": mapping["grams"],
                "grams_provenance": mapping["grams_provenance"],
            })
        row["unmapped_source_ingredients"] = [
            ingredient
            for ingredient in row["unmapped_source_ingredients"]
            if ingredient["name"] not in matched_names
        ]
    return rows


def write_manifest(
    path: Path, rows: list[dict], original: list[str], changed: set[str]
) -> None:
    """Atomically rewrite only the rows that changed, keeping others verbatim."""
    updated: list[str] = []
    for index, row in enumerate(rows):
        if row["sample_id"] in changed:
            updated.append(json.dumps(row, ensure_ascii=False))
        else:
            updated.append(original[index])

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write("\n".join(updated) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="rewrite the manifest (default is a dry run)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST,
        help=f"manifest to inspect (default: {MANIFEST.relative_to(REPO)})",
    )
    parser.add_argument(
        "--pack",
        type=Path,
        default=PACK,
        help=f"locale pack directory (default: {PACK.relative_to(REPO)})",
    )
    args = parser.parse_args(argv)

    raw_lines = args.manifest.read_text(encoding="utf-8").splitlines()
    if not raw_lines or any(not line.strip() for line in raw_lines):
        print(f"error: {args.manifest} is empty or has blank lines", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in raw_lines]

    lookup = load_catalogue(args.pack)
    proposals, problems = find_matches(rows, lookup)
    mappings = [proposal for proposal in proposals if proposal["action"] == "map"]

    if mappings:
        print(f"{'sample_id':<12} {'ingredient':<24} {'grams':>10}  matched_food_id")
        for proposal in mappings:
            print(
                f"{proposal['sample_id']:<12} {proposal['ingredient']:<24} "
                f"{proposal['grams']:>10.6f}  {proposal['food_id']}"
            )
    else:
        print("no exact catalogue matches found")

    for proposal in proposals:
        if proposal["action"] == "left_unmapped_no_grams":
            print(
                f"left unmapped (no grams): {proposal['sample_id']} "
                f"{proposal['ingredient']!r} would match {proposal['food_id']}",
                file=sys.stderr,
            )

    print(f"\nmatched ingredients: {len(mappings)}")
    print(f"rows affected: {len({proposal['sample_id'] for proposal in mappings})}")

    if problems:
        for problem in problems:
            print(f"inconsistent: {problem}", file=sys.stderr)
        print("refusing to change the manifest", file=sys.stderr)
        return 1

    if not mappings:
        return 0

    if args.apply:
        apply_proposals(rows, proposals)
        changed = {proposal["sample_id"] for proposal in mappings}
        write_manifest(args.manifest, rows, raw_lines, changed)
        print(f"applied to {args.manifest}")
    else:
        print("dry run: pass --apply to rewrite the manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
