"""Turn golden-manifest rows into provider inputs.

The offline harness replays recorded fixtures by ``sample_id``; the live path
must send the actual image bytes (or explicit text). Both the live harness and
the fixture recorder read the same manifest, so the mapping lives here instead
of being duplicated in either caller.
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from mealog.pipeline.ports import VisionInput

#: Rows whose evidence is free text rather than a photograph. A row may carry
#: ``input_text`` itself; this map is the compatibility path for older rows.
TEXT_INPUTS = {"tr_0003": "1 simit ve 1 ayran"}


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
    committed compatibility map.
    """
    sample_id = row["sample_id"]
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
