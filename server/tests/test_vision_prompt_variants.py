"""Named prompt variants are opt-in and never move the default prompt.

The byte-identity test compares the shipping prompt against a SHA-256 captured
from the tree *before* ``p5`` existed. A copied 2.5 kB literal would work too,
but it lives next to the prompt it is meant to freeze and is easy to "fix"
together with an accidental edit; the independent digest cannot be updated
without deliberately lying about what the baseline was.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import ClassVar, Self

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import harness

from mealog.adapters.vision_gemini import (
    PROMPT_VARIANTS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    GeminiVision,
    UnknownPromptVariant,
    prompt_for_variant,
)
from mealog.domain.models import PerceivedItem
from mealog.pipeline.ports import VisionInput

#: Captured from the unmodified p4 prompt before the variant registry existed.
P4_SHA256 = "5b49ee2c7cf0f38423d196da8d3041e128703ee6e093da13d6a4dc22522af7f7"
P4_LENGTH = 2551

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeTransport:
    def __init__(self, payload: dict):
        self.payload = payload
        self.requests = []

    def __call__(self, request, *, timeout: float):
        self.requests.append(request)
        return FakeResponse(self.payload)


def provider_response() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "items": [
                                        {
                                            "surface_form": "scrambled eggs",
                                            "cooking_method": None,
                                            "portion_hint": None,
                                            "medium": "real_plate",
                                            "confidence": 0.9,
                                        }
                                    ]
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }


def test_default_variant_is_the_shipping_prompt_byte_for_byte() -> None:
    assert PROMPT_VERSION == "p4"
    assert prompt_for_variant("p4") == SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT) == P4_LENGTH
    assert hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest() == P4_SHA256

    transport = FakeTransport(provider_response())
    vision = GeminiVision(
        "key",
        opener=transport,
        request_interval=0,
        secondary_model=None,
    )

    assert vision.prompt_variant == "p4"
    assert vision.system_prompt == SYSTEM_PROMPT
    vision.perceive(VisionInput(text="scrambled eggs"))

    payload = json.loads(transport.requests[0].data)
    assert payload["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT


def test_p5_differs_and_still_mentions_every_required_schema_key() -> None:
    p5 = prompt_for_variant("p5")
    required = RESPONSE_SCHEMA["properties"]["items"]["items"]["required"]

    assert p5 != SYSTEM_PROMPT
    assert set(required) == {
        "surface_form",
        "cooking_method",
        "portion_hint",
        "count",
        "medium",
        "confidence",
    }
    for key in required:
        assert f"`{key}`" in p5, f"p5 does not mention required key {key}"


def test_unknown_variant_names_the_available_variants() -> None:
    with pytest.raises(UnknownPromptVariant, match="available variants: p4, p5"):
        prompt_for_variant("p9")

    with pytest.raises(UnknownPromptVariant, match="available variants: p4, p5"):
        GeminiVision("key", prompt_variant="p9")

    assert PROMPT_VARIANTS == ("p4", "p5")


class RecordingVision:
    """Provider double: records the selected variant, never touches the network."""

    prompt_variants: ClassVar[list[str]] = []

    def __init__(self, api_key: str, prompt_variant: str = PROMPT_VERSION):
        self.api_key = api_key
        self.prompt_variant = prompt_variant
        self.name = "gemini"
        type(self).prompt_variants.append(prompt_variant)

    def perceive(self, input_ref):
        return [PerceivedItem(surface_form="scrambled eggs", confidence=0.9)]


class OfflineVision:
    name = "fixture"

    def perceive(self, input_ref):
        return [PerceivedItem(surface_form="scrambled eggs", confidence=0.9)]


def golden_row(sample_id: str = "row_1") -> dict:
    return {
        "sample_id": sample_id,
        "locale": "en_US",
        "cuisine": "western",
        "tier": "tier_1",
        "input_type": "photo",
        "image_filename": "dish.png",
        "truth": {"items": [{"food_id": "us.eggs_scrambled", "grams": 100.0}]},
    }


def write_manifest(directory: Path) -> Path:
    path = directory / "manifest.jsonl"
    path.write_text(json.dumps(golden_row()) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def reset_variants():
    RecordingVision.prompt_variants = []


def test_live_harness_sends_and_records_the_selected_variant(
    tmp_path, monkeypatch, capsys
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    (images / "dish.png").write_bytes(IMAGE_BYTES)
    manifest = write_manifest(tmp_path)
    out = tmp_path / "scorecard.md"
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--configs",
            "V3",
            "--live",
            "--prompt-variant",
            "p5",
            "--manifest",
            str(manifest),
            "--images-dir",
            str(images),
            "--out",
            str(out),
            "--summary-json",
            str(summary_path),
        ],
    )

    assert harness.main() == 0
    capsys.readouterr()

    assert RecordingVision.prompt_variants == ["p5"]
    report = out.read_text(encoding="utf-8")
    assert "prompt `p5`" in report
    written = json.loads(summary_path.read_text(encoding="utf-8"))
    assert written["prompt_variant"] == "p5"
    assert written["prompt_version"] == "p5"


def test_offline_flag_is_ignored_and_output_stays_byte_identical(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest = write_manifest(tmp_path)
    monkeypatch.setattr(harness, "make_vision", lambda _provider: OfflineVision())
    without_flag = tmp_path / "without.md"
    with_flag = tmp_path / "with.md"
    without_summary = tmp_path / "without.json"
    with_summary = tmp_path / "with.json"

    for out, summary_path, extra in (
        (without_flag, without_summary, []),
        (with_flag, with_summary, ["--prompt-variant", "p5"]),
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "harness.py",
                "--configs",
                "V3",
                "--manifest",
                str(manifest),
                "--images-dir",
                str(tmp_path / "never-read"),
                "--out",
                str(out),
                "--summary-json",
                str(summary_path),
                *extra,
            ],
        )
        assert harness.main() == 0
        capsys.readouterr()

    assert with_flag.read_bytes() == without_flag.read_bytes()
    assert with_summary.read_bytes() == without_summary.read_bytes()
    assert json.loads(with_summary.read_text(encoding="utf-8"))["prompt_variant"] == "p4"


def test_unknown_variant_is_rejected_before_any_provider_call(
    tmp_path, monkeypatch, capsys
) -> None:
    out = tmp_path / "never.md"
    monkeypatch.setattr(harness, "GeminiVision", RecordingVision)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "harness.py",
            "--configs",
            "V3",
            "--live",
            "--prompt-variant",
            "p9",
            "--out",
            str(out),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        harness.main()

    assert raised.value.code == 2
    stderr = capsys.readouterr().err
    assert "p4" in stderr and "p5" in stderr
    assert RecordingVision.prompt_variants == []
    assert not out.exists()
