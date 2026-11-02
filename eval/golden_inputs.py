"""Turn golden-manifest rows into provider inputs.

The offline harness replays recorded fixtures by ``sample_id``; the live path
must send the actual image bytes (or explicit text). Both the live harness and
the fixture recorder read the same manifest, so the mapping lives here instead
of being duplicated in either caller.

Live eligibility is part of the same mapping. A manifest row may be scored
offline and still not be sent to a third-party processor, so ``input_for_row``
refuses before it reads a file. The policy is here rather than in
``locale_scope.py`` because the locale scope is about which catalogues a clean
clone can redistribute, while this rule is about what may leave the machine
once a row has been selected.
"""
from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mealog.pipeline.ports import VisionInput

#: Rows whose evidence is free text rather than a photograph. A row may carry
#: ``input_text`` itself; this map is the compatibility path for older rows.
TEXT_INPUTS = {"tr_0003": "1 simit ve 1 ayran"}


#: Licence kinds that permit sending the image to a third-party processor.
#: The manifest appends a source note in parentheses, so the match rule compares
#: the kind before the first ``(`` case-insensitively, as a whole-word prefix:
#: ``CC BY-SA 4.0`` matches ``CC BY-SA`` while ``CC BY-NC`` does not match
#: ``CC BY 4.0``. An unlisted, empty, or missing licence fails closed.
LIVE_LICENCES = {
    # CC BY 4.0: attribution-only; redistribution and third-party processing are
    # permitted, and the manifest records the source for attribution.
    "cc by 4.0": "CC BY 4.0",
    # CC BY-SA: attribution and share-alike; the unmodified image may be sent
    # to a processor, and the source stays recorded for attribution.
    "cc by-sa": "CC BY-SA",
    # Apache-2.0: permissive, including commercial use and redistribution.
    "apache-2.0": "Apache-2.0",
}


class LiveIneligibleRow(Exception):
    """A row may be scored offline but must not be sent to a provider.

    Raised by :func:`input_for_row` before it builds an input or reads image
    bytes. ``select_rows`` also filters these rows, but a caller that bypasses
    that filter must hit this wall rather than a network call.
    """

    def __init__(self, sample_id: str, image_license: Any, reason: str) -> None:
        self.sample_id = sample_id
        self.image_license = image_license
        self.reason = reason
        super().__init__(
            f"{sample_id} is not live-eligible because image_license "
            f"{image_license!r}: {reason}"
        )


@dataclass(frozen=True)
class LiveExclusion:
    """One row removed from a live run, with the evidence needed to explain it."""

    sample_id: str
    image_license: str | None
    reason: str


def licence_kind(image_license: Any) -> str | None:
    """The licence identifier before the manifest's source note."""
    if not isinstance(image_license, str):
        return None
    kind = image_license.split("(", 1)[0].strip().lower()
    return kind or None


def live_licence(image_license: Any) -> str | None:
    """The allowlisted licence kind, or None when the term is not recognised."""
    kind = licence_kind(image_license)
    if kind is None:
        return None
    for allowed, canonical in LIVE_LICENCES.items():
        if kind == allowed or kind.startswith(allowed + " "):
            return canonical
    return None


def live_ineligible_reason(row: dict[str, Any]) -> str | None:
    """Why a row cannot be sent to a provider, or None when it may be.

    The per-row override subtracts only. ``live_eligible: true`` does not make
    a non-commercial licence sendable; it simply does not change the licence
    decision.
    """
    image_license = row.get("image_license")
    if live_licence(image_license) is not None:
        licence_reason = None
    elif not isinstance(image_license, str) or not image_license.strip():
        licence_reason = "no image_license recorded; the input's licence is unknown"
    else:
        licence_reason = (
            f"image_license {image_license!r} is not in the live allowlist"
        )
    if row.get("live_eligible") is False:
        # Keep the licence reason when there is one: the override is the pin,
        # but the licence is the fact a reader needs to see.
        if licence_reason is not None:
            return f"live_eligible=false override; {licence_reason}"
        return "live_eligible=false override"
    return licence_reason


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL golden manifest in file order.

    A missing or duplicated ``sample_id`` is a repository error: silently
    dropping or overwriting a row would make the scorecard's denominator a lie.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        sample_id = row.get("sample_id") if isinstance(row, dict) else None
        if not isinstance(sample_id, str) or not sample_id:
            raise ValueError(f"manifest line {line_number} has no sample_id")
        if sample_id in seen:
            raise ValueError(f"duplicate sample_id in manifest: {sample_id}")
        seen.add(sample_id)
        rows.append(row)
    return rows


def input_for_row(row: dict[str, Any], images_dir: Path) -> VisionInput:
    """Build the exact provider input a live model would receive for ``row``.

    Image rows use the manifest's filename (never the sample ID) and the file's
    real bytes. Text rows prefer ``row["input_text"]`` and fall back to the
    committed compatibility map. A row whose licence does not permit
    third-party processing raises :class:`LiveIneligibleRow` before any file is
    read, even when the caller reached this function directly.
    """
    sample_id = row["sample_id"]
    reason = live_ineligible_reason(row)
    if reason is not None:
        raise LiveIneligibleRow(sample_id, row.get("image_license"), reason)

    if row.get("input_type") == "text":
        text = row.get("input_text")
        if not isinstance(text, str) or not text.strip():
            text = TEXT_INPUTS.get(sample_id)
        if not text:
            raise ValueError(f"no input text configured for {sample_id}")
        return VisionInput(text=text, sample_id=sample_id)

    filename = row.get("image_filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError(f"{sample_id} has no safe image_filename")
    image_path = images_dir / filename
    if not image_path.is_file():
        raise FileNotFoundError(
            f"missing {image_path}; run scripts/fetch_golden_images.py first"
        )
    image_bytes = image_path.read_bytes()
    media_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    return VisionInput(
        image_bytes=image_bytes,
        image_media_type=media_type,
        sample_id=sample_id,
    )
