"""Shared pytest fixtures.

The Turkish catalogue is `restricted-noncommercial` and is installed locally
(`python scripts/install_restricted_pack.py`) instead of being committed. Tests
that need those rows skip with a named reason when it is absent; everything that
does not need them must stay green on a clean clone.
"""
from __future__ import annotations

from pathlib import Path

import pytest

PACK_ROOT = Path(__file__).resolve().parents[2] / "locale_packs"


def pack_installed(locale: str) -> bool:
    directory = PACK_ROOT / locale
    return all(
        (directory / name).is_file()
        for name in ("foods.jsonl", "aliases.jsonl", "units.jsonl")
    )


def requires_pack(locale: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not pack_installed(locale),
        reason=(
            f"locale pack {locale!r} is licence-restricted and not installed; "
            "run `make pack` with TR_PACK_SOURCE set (docs/licensing.md)"
        ),
    )
