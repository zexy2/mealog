"""The evaluation adapter's fallback ladder mirrors the served adapter's.

The Python adapter is used by the offline/live evaluation harness, while the
Node adapter is what the product serves. They are separate files, so only a
test can keep the fallback id from drifting: the 2026-11-02 run reached the
Python fallback and got a 404 because the two had already diverged (#475).

The fake transport never touches the network; these tests prove which model id
the ladder requests, not that the provider serves it.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Self
from urllib.error import HTTPError
from urllib.parse import unquote

import pytest

from mealog.adapters import vision_gemini
from mealog.adapters.vision_gemini import (
    RUNG_FAILURE,
    RUNG_SECONDARY_MODEL,
    RUNG_TEXT_ONLY,
    GeminiVision,
)
from mealog.pipeline.ports import VisionInput

SERVER_ROOT = Path(__file__).resolve().parents[1]
TYPESCRIPT_ADAPTER = SERVER_ROOT / "src/adapters/vision.gemini.ts"

# The served adapter is TypeScript, so the parity guard parses its literal. The
# pattern is deliberately narrow: a miss is reported as a parse failure rather
# than treated as agreement.
_TS_CONSTANT = r"\b{name}\s*=\s*'([^']*)'"
_MODEL_IN_URL = re.compile(r"/models/([^/:]+):generateContent")


def typescript_constant(name: str) -> str:
    source = TYPESCRIPT_ADAPTER.read_text(encoding="utf-8")
    match = re.search(_TS_CONSTANT.format(name=name), source)
    if match is None:
        pytest.fail(
            f"could not parse {name} from the served adapter {TYPESCRIPT_ADAPTER}; "
            "the parity guard cannot compare the two ladders"
        )
    return match.group(1)


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
    def __init__(self, outcomes: list[dict | BaseException]):
        self.outcomes = outcomes
        self.requests = []

    def __call__(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


def provider_response(surface_form: str = "rice") -> dict:
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
                                            "surface_form": surface_form,
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


def provider_error(status: int) -> HTTPError:
    return HTTPError(
        "https://fake.invalid/generateContent",
        status,
        "provider failure",
        {},
        io.BytesIO(b'{"error":"provider failure"}'),
    )


def build_vision(transport: FakeTransport, **kwargs) -> GeminiVision:
    kwargs.setdefault("request_interval", 0)
    return GeminiVision(
        "test-key",
        opener=transport,
        sleep_fn=lambda _delay: None,
        jitter_fn=lambda _cap: 0.0,
        **kwargs,
    )


def requested_models(transport: FakeTransport) -> list[str]:
    models = []
    for request, _timeout in transport.requests:
        match = _MODEL_IN_URL.search(request.full_url)
        assert match is not None, f"no model id in {request.full_url}"
        models.append(unquote(match.group(1)))
    return models


def test_secondary_model_matches_the_served_adapter() -> None:
    """The two adapters describe one ladder, so their fallback id must agree."""
    assert vision_gemini.SECONDARY_MODEL == typescript_constant("SECONDARY_MODEL")


def test_primary_defaults_are_allowed_to_differ() -> None:
    """Parse both primary defaults without requiring them to be equal.

    The adapters intentionally have different *primary* defaults: the served
    backend uses ``gemini-3.6-flash`` while the evaluation adapter keeps
    ``gemini-flash-lite-latest`` for the recorded fixtures. Only the fallback
    is a shared contract, so an equality assertion here would encode a
    divergence as a defect.
    """
    node_default = typescript_constant("DEFAULT_MODEL")

    assert node_default
    assert vision_gemini.DEFAULT_MODEL
    # No equality assertion: the two primary defaults are independent choices.


def test_fallback_sends_the_second_request_to_the_shared_id() -> None:
    """A primary failure must actually use SECONDARY_MODEL, not just declare it."""
    transport = FakeTransport([provider_error(503), provider_response()])
    vision = build_vision(transport, max_attempts=1)

    vision.perceive(VisionInput(text="rice"))

    assert requested_models(transport) == [
        vision.model,
        vision_gemini.SECONDARY_MODEL,
    ]
    assert vision.rung == RUNG_SECONDARY_MODEL
    assert vision.degraded is True


def test_no_secondary_rung_when_it_would_repeat_the_configured_model() -> None:
    """The ladder never falls back to the id it is already using."""
    shared_id = vision_gemini.SECONDARY_MODEL
    transport = FakeTransport([provider_error(503), provider_response()])
    vision = build_vision(
        transport,
        model_id=shared_id,
        secondary_model=shared_id,
        max_attempts=1,
    )

    with pytest.raises(RuntimeError, match="terminal_status=503"):
        vision.perceive(VisionInput(text="rice"))

    # The second outcome is never consumed: a self-fallback rung would have
    # answered with it instead of exhausting the ladder.
    assert requested_models(transport) == [shared_id]
    assert vision.rung == RUNG_FAILURE


def test_text_only_rung_uses_the_shared_id_without_the_image() -> None:
    """Both image rungs fail, and the text rung names the same fallback id."""
    transport = FakeTransport(
        [provider_error(503), provider_error(503), provider_response("description")]
    )
    vision = build_vision(transport, max_attempts=1)
    input_ref = VisionInput(
        image_bytes=b"fake-image",
        image_media_type="image/jpeg",
        text="rice",
        sample_id="sample-1",
    )

    items = vision.perceive(input_ref)

    assert [item.surface_form for item in items] == ["description"]
    models = requested_models(transport)
    assert models == [
        vision.model,
        vision_gemini.SECONDARY_MODEL,
        vision_gemini.SECONDARY_MODEL,
    ]
    assert vision.rung == RUNG_TEXT_ONLY
    assert vision.last_model == vision_gemini.SECONDARY_MODEL

    third_payload = json.loads(transport.requests[2][0].data)
    third_parts = third_payload["contents"][0]["parts"]
    assert not any("inlineData" in part for part in third_parts)
    assert {part.get("text") for part in third_parts} >= {"rice"}
