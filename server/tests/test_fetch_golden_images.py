"""One dead golden-image source must not abort the rest of the fetch."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "mealog_fetch_golden_images", SCRIPTS / "fetch_golden_images.py"
)
assert SPEC is not None and SPEC.loader is not None
fetch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch
SPEC.loader.exec_module(fetch)

DATA = b"image-bytes"


def row(sample_id: str, **overrides: object) -> dict:
    base = {
        "sample_id": sample_id,
        "input_type": "image",
        "image_source_url": f"https://example.invalid/{sample_id}.png",
        "image_license": "CC BY 4.0",
        "image_sha256": hashlib.sha256(DATA).hexdigest(),
        "image_filename": f"{sample_id}.png",
    }
    base.update(overrides)
    return base


def write_manifest(tmp_path: Path, rows: list[dict]) -> Path:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8"
    )
    return manifest


def test_a_failed_row_does_not_stop_later_rows(tmp_path, monkeypatch, capsys):
    manifest = write_manifest(
        tmp_path,
        [row("bad"), row("good"), row("text", input_type="text")],
    )

    def fake_fetch(entry, _cache):
        if entry["sample_id"] == "bad":
            raise OSError("HTTP 403")
        return DATA

    monkeypatch.setattr(fetch, "_fetch_entry", fake_fetch)
    fetched, failures = fetch.fetch_manifest(manifest, tmp_path / "images")

    assert fetched == 1
    assert failures == ["bad: HTTP 403"]
    assert (tmp_path / "images" / "good.png").read_bytes() == DATA
    assert "failed bad: HTTP 403" in capsys.readouterr().err


def test_main_reports_a_partial_fetch_as_failure(tmp_path, monkeypatch):
    manifest = write_manifest(tmp_path, [row("bad"), row("good")])

    def fake_fetch(entry, _cache):
        if entry["sample_id"] == "bad":
            raise OSError("HTTP 403")
        return DATA

    monkeypatch.setattr(fetch, "_fetch_entry", fake_fetch)
    code = fetch.main(["--manifest", str(manifest), "--output-dir", str(tmp_path / "images")])

    assert code == 1
    assert (tmp_path / "images" / "good.png").is_file()


def test_main_is_zero_when_every_input_resolves(tmp_path, monkeypatch):
    manifest = write_manifest(tmp_path, [row("good")])
    monkeypatch.setattr(fetch, "_fetch_entry", lambda _entry, _cache: DATA)

    code = fetch.main(["--manifest", str(manifest), "--output-dir", str(tmp_path / "images")])

    assert code == 0
