"""Which locales the published evidence snapshot covers, and why.

The rule exists because of a reproducibility failure, not for tidiness. The
README used to publish numbers measured with the licence-restricted Turkish
catalogue installed. On a clean clone the same command produced different
numbers (9% coverage instead of 12%, Item F1 0.13 instead of 0.15) and the
retrieval evaluation crashed on the missing pack. A reader could not reproduce
the claim the repository was making about itself.

So the published snapshot is defined as *the evidence a clean clone can
reproduce*: every locale whose catalogue may be redistributed. A
`restricted-noncommercial` pack is excluded by default and added only when the
caller asks for it, because then the numbers are no longer what a reader gets.

Both `eval/harness.py` and `eval/retrieval_eval.py` take their scope from here,
so the two cannot disagree about which markets are in the published set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SERVER_SRC = REPO / "server" / "src"
if str(SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(SERVER_SRC))

from mealog.locales.loader import LicenseTerm  # noqa: E402

#: The one licence term that forces a catalogue out of the repository. The rows
#: may be installed locally (`make pack`), but the published snapshot must not
#: depend on that, or it stops describing a clean checkout.
NON_REDISTRIBUTABLE = LicenseTerm.RESTRICTED_NONCOMMERCIAL


def pack_root() -> Path:
    return REPO / "locale_packs"


def locale_license(locale: str, root: Path | None = None) -> str | None:
    """The raw `license` value from `pack.yaml`, or None when it is not declared.

    Kept as the raw string rather than the enum on purpose: an unrecognised
    value must not be silently coerced into "included" by a filter whose only
    job is to decide what may be published.
    """
    manifest = (root or pack_root()) / locale / "pack.yaml"
    if not manifest.is_file():
        return None
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    value = data.get("license")
    return str(value).strip() if isinstance(value, str) else None


def evidence_scope(
    locales: list[str] | set[str],
    include_restricted: bool = False,
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Split locales into (published, excluded).

    A locale with no readable licence declaration is **included**: the loader
    fails loudly for a pack it cannot read, and silently dropping a market
    because its metadata is broken would turn a configuration error into a
    quietly smaller denominator.
    """
    included: list[str] = []
    excluded: list[str] = []
    for locale in sorted(set(locales)):
        if not include_restricted and locale_license(locale, root) == NON_REDISTRIBUTABLE.value:
            excluded.append(locale)
        else:
            included.append(locale)
    return included, excluded


def exclusion_note(included: list[str], excluded: list[str]) -> str:
    """One line that names the scope, so a reader never has to infer it."""
    scope = ", ".join(included) if included else "(none)"
    note = f"Evidence scope: {scope}"
    if excluded:
        note += (
            f" | excluded: {', '.join(excluded)}"
            " (licence-restricted catalogue; install with `make pack` and pass"
            " --include-restricted to measure it locally — those numbers are not"
            " published because a clean clone cannot reproduce them)"
        )
    return note
