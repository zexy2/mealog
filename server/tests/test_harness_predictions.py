"""The per-row prediction artifact is an opt-in live instrument.

These tests never call the network. The live adapter is replaced with a fake,
so the artifact can be checked for its schema, its denominator, its ordering,
and the promise that it carries no image bytes or credentials. The same fake
run with and without the flag must also produce the same scorecard and summary.
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

from mealog.domain.models import Candidate, PerceivedItem, ResolvedItem

IMAGE_BYTES = b"SECRET-IMAGE-BYTES-472"
API_KEY = "SECRET-API-KEY-472"


def golden_row(sample_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "locale": "en_US",
        "cuisine": "western",
        "tier": "tier_1",
        "input_type": "photo",
        "image_license": "CC BY 4.0 (test fixture)",
        "image_filename": "dish.png",
        "truth": {"items": [{"food_id": "us.eggs_scrambled", "grams": 100.0}]},
    }


def write_manifest(directory: Path, rows: list[dict]) -> Path:
    path = directory / "manifest.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def write_image(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "dish.png"
    path.write_bytes(IMAGE_BYTES)
    return path


class RecordingVision:
    """A provider double that records inputs and can fail named rows."""

    fail_ids: ClassVar[set[str]] = set()
    instances: ClassVar[list[RecordingVision]] = []

    def __init__(self, api_key: str, prompt_variant: str = "p4"):
        self.api_key = api_key
        self.prompt_variant = prompt_variant
        self.name = "gemini"
        self.seen = []
        self.last_served_model = "gemini-3.5-flash-lite"
        self.last_model_version = "gemini-3.5-flash-lite"
        self.observed_model_versions: list[str] = ["gemini-3.5-flash-lite"]
        self.max_elapsed = 30.0
        self.timeout = 90.0
        type(self).instances.append(self)

    def perceive(self, input_ref):
        self.seen.append(input_ref)
        if input_ref.sample_id in type(self).fail_ids:
            raise RuntimeError(f"provider failed for {input_ref.sample_id}")
        # "chicken" retrieves three candidates in the en_US pack, so the live
        # artifact exercises a non-empty candidate list.
        return [PerceivedItem(surface_form="chicken", confidence=0.9)]


@pytest.fixture(autouse=True)
def reset_fake():
    RecordingVision.fail_ids = set()
    RecordingVision.instances = []


def run_main(monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)
    monkeypatch.setattr(
        sys, "argv", ["harness.py", "--configs", "V3", *extra]
    )
    return harness.main()


def test_predictions_without_live_exits_two_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "preds.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        ["harness.py", "--configs", "V3", "--predictions", str(target)],
    )

    with pytest.raises(SystemExit) as caught:
        harness.main()

    assert caught.value.code == 2
    assert not target.exists()
    err = capsys.readouterr().err
    assert "offline" in err
    assert "deterministic" in err
    assert "live perception" in err


def test_live_run_writes_one_schema_row_per_manifest_row(
    tmp_path, monkeypatch, capsys
):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(tmp_path, [golden_row("row_1"), golden_row("row_2")])
    target = tmp_path / "preds.jsonl"

    code = run_main(
        monkeypatch,
        "--live",
        "--prompt-variant",
        "p5",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--predictions",
        str(target),
    )
    capsys.readouterr()

    assert code == 0
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [line["sample_id"] for line in lines] == ["row_1", "row_2"]

    identity = {
        "config", "sample_id", "locale", "cuisine", "tier", "prompt_variant",
        "perceived", "truth_ids", "pred_ids", "row_error",
    }
    for line in lines:
        assert set(line) == identity
        assert line["config"] == "V3"
        assert line["locale"] == "en_US"
        assert line["cuisine"] == "western"
        assert line["tier"] == "tier_1"
        assert line["prompt_variant"] == "p5"
        assert line["truth_ids"] == ["us.eggs_scrambled"]
        assert line["row_error"] is None
        assert line["perceived"]
        for item in line["perceived"]:
            assert set(item) == {
                "query", "food_id", "abstained", "confidence", "candidates",
            }
            assert len(item["candidates"]) <= 3
            for candidate in item["candidates"]:
                assert set(candidate) == {"food_id", "score"}

    assert RecordingVision.instances[-1].prompt_variant == "p5"

    # The cap is enforced by the writer, not by retrieval happening to return
    # three candidates: a five-candidate item keeps the first three in order.
    five = [
        Candidate(food_id=f"food_{index}", name=f"food {index}", score=1.0 - index / 10)
        for index in range(5)
    ]
    detail = harness._perceived_detail(
        [ResolvedItem(query="anything", candidates=five)]
    )[0]
    assert [c["food_id"] for c in detail["candidates"]] == [
        "food_0", "food_1", "food_2",
    ]


def test_failed_row_still_produces_a_line(tmp_path, monkeypatch, capsys):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(tmp_path, [golden_row("row_1"), golden_row("row_2")])
    target = tmp_path / "preds.jsonl"
    RecordingVision.fail_ids = {"row_2"}

    code = run_main(
        monkeypatch,
        "--live",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--predictions",
        str(target),
    )
    capsys.readouterr()

    assert code == 1
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert [line["sample_id"] for line in lines] == ["row_1", "row_2"]
    failed = lines[1]
    assert failed["perceived"] == []
    assert failed["pred_ids"] == []
    assert failed["truth_ids"] == ["us.eggs_scrambled"]
    assert failed["row_error"] == "provider failed for row_2"
    assert lines[0]["row_error"] is None


def test_artifact_carries_no_image_bytes_or_key(tmp_path, monkeypatch, capsys):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(tmp_path, [golden_row("row_1")])
    target = tmp_path / "preds.jsonl"
    monkeypatch.setenv("GEMINI_API_KEY", API_KEY)

    code = run_main(
        monkeypatch,
        "--live",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--predictions",
        str(target),
    )
    capsys.readouterr()

    assert code == 0
    assert RecordingVision.instances[-1].api_key == API_KEY
    text = target.read_text(encoding="utf-8")
    assert "SECRET-IMAGE-BYTES-472" not in text
    assert "SECRET-API-KEY-472" not in text
    assert "base64" not in text.lower()
    assert str(images) not in text


def test_artifact_does_not_move_scorecard_or_summary(
    tmp_path, monkeypatch, capsys
):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(tmp_path, [golden_row("row_1"), golden_row("row_2")])

    bare_card = tmp_path / "bare.md"
    bare_summary = tmp_path / "bare.json"
    assert run_main(
        monkeypatch,
        "--live",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--out",
        str(bare_card),
        "--summary-json",
        str(bare_summary),
    ) == 0
    capsys.readouterr()

    with_card = tmp_path / "with.md"
    with_summary = tmp_path / "with.json"
    target = tmp_path / "preds.jsonl"
    assert run_main(
        monkeypatch,
        "--live",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--out",
        str(with_card),
        "--summary-json",
        str(with_summary),
        "--predictions",
        str(target),
    ) == 0
    capsys.readouterr()

    assert target.exists()
    assert bare_card.read_text(encoding="utf-8") == with_card.read_text(encoding="utf-8")
    assert json.loads(bare_summary.read_text(encoding="utf-8")) == json.loads(
        with_summary.read_text(encoding="utf-8")
    )


def test_limit_bounds_the_artifact_not_the_scope(tmp_path, monkeypatch, capsys):
    images = tmp_path / "images"
    write_image(images)
    manifest = write_manifest(
        tmp_path,
        [golden_row(f"row_{index}") for index in range(1, 5)],
    )
    target = tmp_path / "preds.jsonl"

    code = run_main(
        monkeypatch,
        "--live",
        "--limit",
        "2",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--predictions",
        str(target),
    )
    capsys.readouterr()

    assert code == 0
    lines = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert [line["sample_id"] for line in lines] == ["row_1", "row_2"]


def test_failed_row_error_does_not_leak_a_filesystem_path(
    tmp_path, monkeypatch, capsys
):
    images = tmp_path / "missing-images"
    manifest = write_manifest(tmp_path, [golden_row("row_1")])
    target = tmp_path / "preds.jsonl"

    code = run_main(
        monkeypatch,
        "--live",
        "--manifest",
        str(manifest),
        "--images-dir",
        str(images),
        "--predictions",
        str(target),
    )
    capsys.readouterr()

    assert code == 1
    line = json.loads(target.read_text(encoding="utf-8"))
    assert line["perceived"] == []
    assert line["row_error"].startswith("missing <path>")
    assert str(images) not in line["row_error"]
