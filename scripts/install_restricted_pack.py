#!/usr/bin/env python3
"""Install a licence-restricted locale pack that is not distributed with the repository.

The Turkish pack is derived from TürKomp, whose data-use conditions permit
conditioned noncommercial sharing and require a separate agreement for
commercial use. Shipping those rows inside a repository under an MIT grant
would say two contradictory things at once, so the repository keeps the pack's
metadata and text rules and leaves the catalogue to an explicit install step.

    python scripts/install_restricted_pack.py --source path/to/tr-catalogue
    python scripts/install_restricted_pack.py --source https://... --expect-sha256 <hash>

The source may be a directory holding `foods.jsonl`, `aliases.jsonl` and
`units.jsonl`, or a `.zip` file with the same layout at its root or in a single
top-level directory. Nothing is written unless every file is present, parses as
JSONL, and — when hashes are given — matches them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "locale_packs/tr"
CATALOGUE = ("foods.jsonl", "aliases.jsonl", "units.jsonl")


def _download(source: str, staging: Path) -> Path:
    request = urllib.request.Request(source, headers={"User-Agent": "mealog-pack-install/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    archive = staging / "pack.zip"
    archive.write_bytes(payload)
    return archive


def _extract(archive: Path, staging: Path) -> Path:
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(staging / "unzipped")
    return staging / "unzipped"


def _locate_catalogue(root: Path) -> Path:
    """Return the directory that directly contains the three catalogue files."""
    if all((root / name).is_file() for name in CATALOGUE):
        return root
    candidates = [path for path in root.iterdir() if path.is_dir()] if root.is_dir() else []
    matches = [path for path in candidates if all((path / name).is_file() for name in CATALOGUE)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(
            f"no catalogue found under {root}: expected {', '.join(CATALOGUE)} "
            "at the root or inside exactly one top-level directory"
        )
    raise SystemExit(f"ambiguous catalogue under {root}: {len(matches)} candidates")


def _validate(directory: Path) -> None:
    for name in CATALOGUE:
        path = directory / name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path.name}:{number} is not valid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"{path.name}:{number} must be a JSON object")

    foods = [json.loads(line) for line in (directory / "foods.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not foods:
        raise SystemExit("foods.jsonl is empty")
    missing = [row.get("food_id", "<no food_id>") for row in foods if "per_100g" not in row]
    if missing:
        raise SystemExit(
            "foods.jsonl rows are missing per_100g: " + ", ".join(map(str, missing[:5]))
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _install(directory: Path, expected: dict[str, str]) -> None:
    mismatches = [
        f"{name}: expected {expected[name]}, got {_sha256(directory / name)}"
        for name in CATALOGUE
        if name in expected and _sha256(directory / name) != expected[name]
    ]
    if mismatches:
        raise SystemExit("catalogue does not match the expected hashes:\n  " + "\n  ".join(mismatches))

    TARGET.mkdir(parents=True, exist_ok=True)
    for name in CATALOGUE:
        destination = TARGET / name
        if destination.exists():
            continue
        shutil.copyfile(directory / name, destination)
        print(f"installed {destination.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="directory, .zip file, or https URL")
    parser.add_argument(
        "--expect-sha256",
        action="append",
        default=[],
        metavar="FILE=HASH",
        help="pin a file to an expected SHA-256 (repeatable)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite catalogue files that are already installed",
    )
    args = parser.parse_args(argv)

    expected: dict[str, str] = {}
    for entry in args.expect_sha256:
        name, _, digest = entry.partition("=")
        if name not in CATALOGUE or not digest:
            raise SystemExit(f"--expect-sha256 wants one of {CATALOGUE} as FILE=HASH, got {entry!r}")
        expected[name] = digest.lower()

    already = [name for name in CATALOGUE if (TARGET / name).exists()]
    if already and not args.force:
        print(
            "catalogue already installed: " + ", ".join(already) + "\n"
            "Delete those files or pass --force to replace them.",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory() as staging_name:
        staging = Path(staging_name)
        if args.source.startswith(("http://", "https://")):
            source = _download(args.source, staging)
        else:
            source = Path(args.source).expanduser().resolve()
            if not source.exists():
                raise SystemExit(f"source not found: {source}")

        if source.is_dir():
            directory = _locate_catalogue(source)
        elif zipfile.is_zipfile(source):
            directory = _locate_catalogue(_extract(source, staging))
        else:
            raise SystemExit(f"unsupported source: {source} (expected a directory or .zip)")

        _validate(directory)
        if args.force:
            for name in CATALOGUE:
                (TARGET / name).unlink(missing_ok=True)
        _install(directory, expected)

    print(
        "\nThe Turkish pack is restricted-noncommercial. Keep the files local and "
        "do not commit them; `python scripts/check_licence_boundary.py` fails if they "
        "reach the tracked tree."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
