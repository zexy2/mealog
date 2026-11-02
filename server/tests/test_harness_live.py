"""The live evaluation path must send real provider inputs, hermetically.

These tests never call the network: the live adapter is replaced with a fake
that records the ``VisionInput`` it receives. The point is the contract between
the manifest and the provider boundary, plus failure isolation and the promise
that measuring never writes fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import harness
from golden_inputs import input_for_row

from mealog.adapters.vision_fixture import FixtureVision
from mealog.domain.models import PerceivedItem

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def golden_row(sample_id: str, *, filename: str | None = "dish.png") -> dict:
    row = {
        "sample_id": sample_id,
        "locale": "en_US",
        "cuisine": "western",
        "tier": "tier_1",
        "input_type": "photo" if filename else "text",
        "truth": {"items": [{"food_id": "us.eggs_scrambled", "grams": 100.0}]},
    }
    if filename is not None:
        row["image_filename"] = filename
    return row


def write_manifest(directory: Path, rows: list[dict]) -> Path:
    path = directory / "manifest.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def write_image(directory: Path, name: str = "dish.png") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(IMAGE_BYTES)
    return path


def fixture_snapshot() -> dict[Path, tuple[int, bytes]]:
    fixtures = ROOT / "eval" / "fixtures"
    return {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in fixtures.rglob("*.json")
    }


class RecordingVision:
    """A provider double that keeps the exact input and can fail named rows."""

    fail_ids: ClassVar[set[str]] = set()
    instances: ClassVar[list[RecordingVision]] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.seen = []
        self.name = "gemini"
        type(self).instances.append(self)

    def perceive(self, input_ref):
        self.seen.append(input_ref)
        if input_ref.sample_id in self.fail_ids:
            raise RuntimeError(f"provider failed for {input_ref.sample_id}")
        return [PerceivedItem(surface_form="scrambled eggs", confidence=0.9)]


@pytest.fixture(autouse=True)
def reset_failures():
    RecordingVision.fail_ids = set()
    RecordingVision.instances = []


def test_input_for_row_uses_image_bytes(tmp_path):
    images = tmp_path / "images"
    write_image(images)

    ref = input_for_row(golden_row("img_1"), images)

    assert ref.sample_id == "img_1"
    assert ref.image_bytes == IMAGE_BYTES
    assert ref.image_media_type == "image/png"
    assert ref.text is None


def test_input_for_row_prefers_row_text_then_mapping(tmp_path):
    explicit = golden_row("free_text", filename=None)
    explicit["input_text"] = "one apple"
    assert input_for_row(explicit, tmp_path).text == "one apple"

    mapped = golden_row("tr_0003", filename=None)
    assert input_for_row(mapped, tmp_path).text == "1 simit ve 1 ayran"


def test_input_for_row_missing_image_names_the_fetch_script(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_golden_images.py"):
        input_for_row(golden_row("gone"), tmp_path / "empty")


def test_live_evaluate_sends_bytes_and_never_writes_fixtures(tmp_path, monkeypatch):
    images = tmp_path / "images"
    write_image(images)
    text_row = golden_row("text_1", filename=None)
    text_row["input_text"] = "1 simit ve 1 ayran"
    manifest = write_manifest(tmp_path, [golden_row("img_1"), text_row])

    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)
    before = fixture_snapshot()

    results, errors = harness.evaluate(
        "V3", live=True, manifest_path=manifest, images_dir=images
    )

    assert errors == []
    assert [result.sample_id for result in results] == ["img_1", "text_1"]

    # The adapter double receives exactly what the live provider would.
    vision = RecordingVision.instances[-1]
    assert [ref.sample_id for ref in vision.seen] == ["img_1", "text_1"]
    assert vision.seen[0].image_bytes == IMAGE_BYTES
    assert vision.seen[0].image_media_type == "image/png"
    assert vision.seen[1].text == "1 simit ve 1 ayran"
    assert fixture_snapshot() == before


def test_missing_image_is_a_row_error_without_calling_the_provider(tmp_path, monkeypatch):
    manifest = write_manifest(tmp_path, [golden_row("missing")])
    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)

    results, errors = harness.evaluate(
        "V3", live=True, manifest_path=manifest, images_dir=tmp_path / "none"
    )

    assert results == []
    assert errors == ["missing"]
    assert RecordingVision.instances[-1].seen == []


def test_live_failure_isolated_and_main_exits_nonzero(tmp_path, monkeypatch, capsys):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(tmp_path, [golden_row("row_1"), golden_row("row_2")])
    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)

    RecordingVision.fail_ids = {"row_2"}
    results, errors = harness.evaluate(
        "V3", live=True, manifest_path=manifest, images_dir=images
    )

    assert [result.sample_id for result in results] == ["row_1"]
    assert errors == ["row_2"]
    assert "row row_2 failed: provider failed for row_2" in capsys.readouterr().err

    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--configs",
            "V3",
            "--live",
            "--manifest",
            str(manifest),
            "--images-dir",
            str(images),
            "--summary-json",
            str(summary_path),
        ],
    )

    code = harness.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "row row_2 failed" in captured.err
    assert "failed rows: row_2" in captured.err
    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["mode"] == "live"
    assert written["rows_requested"] == 2
    assert written["row_errors"] == ["row_2"]
    assert written["configs"]["V3"]["rows"] == 1


def test_offline_evaluate_replays_fixture_without_images(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "offline_1.json").write_text(
        json.dumps(
            {
                "sample_id": "offline_1",
                "provider": "gemini",
                "model_id": "gemini-flash-lite-latest",
                "prompt_version": "p3",
                "_synthetic": False,
                "items": [{"surface_form": "scrambled eggs", "confidence": 0.9}],
            }
        ),
        encoding="utf-8",
    )
    manifest = write_manifest(tmp_path, [golden_row("offline_1")])
    monkeypatch.setattr(
        harness, "make_vision", lambda provider: FixtureVision(fixtures)
    )

    results, errors = harness.evaluate(
        "V3",
        live=False,
        manifest_path=manifest,
        images_dir=tmp_path / "never-read",
    )

    assert errors == []
    assert [result.sample_id for result in results] == ["offline_1"]


def test_live_scorecard_never_calls_itself_offline_evidence():
    live = harness.scorecard({}, mode="live", provider_model="gemini-flash-lite-latest")
    offline = harness.scorecard({}, mode="offline")

    assert "offline evidence" not in live
    assert "a live observation" in live
    assert "gemini-flash-lite-latest" in live
    assert "not comparable to the offline snapshot" in live
    assert "offline evidence" in offline
