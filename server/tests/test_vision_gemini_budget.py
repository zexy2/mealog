"""The per-row budget is real, bounded, recorded, and attributed honestly.

These tests are hermetic: a fake transport advances a fake clock and never
touches the network. The clock models what a socket timeout does, so a slow
response that exceeds the *request* timeout raises ``TimeoutError`` at the
timeout boundary rather than after its full duration.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Self
from urllib.error import HTTPError

import pytest

from mealog.adapters import vision_gemini
from mealog.adapters.vision_gemini import (
    MAX_ELAPSED_ENV_VAR,
    MAX_ELAPSED_SECONDS,
    GeminiVision,
)
from mealog.pipeline.ports import VisionInput


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
    """Outcomes are payloads, exceptions, or ``(duration, outcome)`` pairs."""

    def __init__(self, outcomes: list[object], clock: FakeClock):
        self.outcomes = list(outcomes)
        self.clock = clock
        self.requests: list[tuple[object, float]] = []

    def __call__(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        duration, result = outcome if isinstance(outcome, tuple) else (0.0, outcome)
        if duration > timeout:
            # A real socket waits its timeout, then reports the timeout.
            self.clock.advance(timeout)
            raise TimeoutError("read operation timed out")
        self.clock.advance(duration)
        if isinstance(result, BaseException):
            raise result
        return FakeResponse(result)


def provider_response(model_version: str | None = None) -> dict:
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "items": [
                                        {
                                            "surface_form": "rice",
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
    if model_version is not None:
        payload["modelVersion"] = model_version
    return payload


def provider_error(status: int) -> HTTPError:
    return HTTPError(
        "https://fake.invalid/generateContent",
        status,
        "provider failure",
        {},
        io.BytesIO(b'{"error":"provider failure"}'),
    )


def build_vision(transport: FakeTransport, clock: FakeClock, **kwargs) -> GeminiVision:
    kwargs.setdefault("request_interval", 0)
    kwargs.setdefault("sleep_fn", clock.advance)
    kwargs.setdefault("jitter_fn", lambda _cap: 0.0)
    return GeminiVision(
        "test-key",
        opener=transport,
        clock_fn=clock,
        **kwargs,
    )


def test_environment_variable_raises_the_effective_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is the test that fails on the pre-#466 adapter: it has no budget
    # environment variable and the default argument is already bound to 30.
    monkeypatch.setenv(MAX_ELAPSED_ENV_VAR, "180")

    vision = GeminiVision("key", request_interval=0, secondary_model=None)

    assert vision.max_elapsed == 180.0


def test_explicit_argument_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MAX_ELAPSED_ENV_VAR, "180")

    vision = GeminiVision("key", max_elapsed=45, request_interval=0, secondary_model=None)

    assert vision.max_elapsed == 45.0


def test_shipped_default_is_still_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(MAX_ELAPSED_ENV_VAR, raising=False)

    vision = GeminiVision("key", request_interval=0, secondary_model=None)

    assert MAX_ELAPSED_SECONDS == 30.0
    assert vision.max_elapsed == 30.0


def test_blank_environment_value_means_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MAX_ELAPSED_ENV_VAR, "   ")

    vision = GeminiVision("key", request_interval=0, secondary_model=None)

    assert vision.max_elapsed == MAX_ELAPSED_SECONDS


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_invalid_environment_budget_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(MAX_ELAPSED_ENV_VAR, value)

    with pytest.raises(ValueError, match=MAX_ELAPSED_ENV_VAR):
        GeminiVision("key", request_interval=0, secondary_model=None)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_explicit_budget_raises_value_error(value: float) -> None:
    with pytest.raises(ValueError, match="max_elapsed"):
        GeminiVision("key", max_elapsed=value, request_interval=0, secondary_model=None)


def test_response_inside_its_own_timeout_is_accepted_after_the_budget() -> None:
    clock = FakeClock()
    transport = FakeTransport([(45.0, provider_response())], clock)
    vision = build_vision(transport, clock, max_elapsed=30, timeout=90, secondary_model=None)

    items = vision.perceive(VisionInput(text="rice"))

    assert [item.surface_form for item in items] == ["rice"]
    assert vision.last_attempts == 1
    # The request kept its configured timeout instead of being truncated to
    # what was left of the 30 s ladder.
    assert transport.requests[0][1] == 90.0


def test_request_timeout_still_retries_and_no_retry_starts_after_deadline() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        [(25.0, provider_response()), (25.0, provider_response())], clock
    )
    vision = build_vision(
        transport,
        clock,
        max_elapsed=30,
        timeout=20,
        max_attempts=3,
        secondary_model=None,
    )

    with pytest.raises(RuntimeError, match="local deadline"):
        vision.perceive(VisionInput(text="rice"))

    # The first timeout allowed a retry; the second spent the budget, so a
    # third request must not start.
    assert len(transport.requests) == 2
    assert [timeout for _request, timeout in transport.requests] == [20.0, 20.0]


def test_local_deadline_is_not_reported_as_provider_exhaustion(caplog) -> None:
    clock = FakeClock()
    transport = FakeTransport([(10.0, provider_error(503))], clock)
    vision = build_vision(transport, clock, max_elapsed=5, timeout=90, secondary_model=None)
    caplog.set_level(logging.INFO, logger="mealog")

    with pytest.raises(RuntimeError) as raised:
        vision.perceive(VisionInput(text="rice"))

    message = str(raised.value)
    assert "Gemini local deadline of 5s reached" in message
    assert "terminal_status=local_deadline" in message
    assert "provider exhausted" not in message
    assert vision.rung == vision_gemini.RUNG_FAILURE

    events = {record.getMessage(): record for record in caplog.records}
    assert "vision_provider_exhausted" not in events
    fields = events["vision_local_deadline"].extra_fields
    assert fields["terminal_status"] == "local_deadline"
    assert fields["max_elapsed"] == 5.0
    assert fields["attempts"] == 1


def test_provider_failure_then_expired_budget_is_local_deadline_with_detail(caplog) -> None:
    # The first rung returns 503, then the fallback rung never starts because
    # the first response consumed the whole budget. The stop condition is
    # local, but the provider failure must remain visible in the message.
    clock = FakeClock()
    transport = FakeTransport([(10.0, provider_error(503))], clock)
    vision = build_vision(
        transport,
        clock,
        max_elapsed=5,
        timeout=90,
        max_attempts=1,
        secondary_model=vision_gemini.SECONDARY_MODEL,
    )
    caplog.set_level(logging.INFO, logger="mealog")

    with pytest.raises(RuntimeError) as raised:
        vision.perceive(VisionInput(text="rice"))

    message = str(raised.value)
    assert "Gemini local deadline of 5s reached" in message
    assert "terminal_status=local_deadline" in message
    assert "last provider failure" in message
    assert "HTTP 503" in message

    events = {record.getMessage(): record for record in caplog.records}
    assert "vision_provider_exhausted" not in events
    assert events["vision_local_deadline"].extra_fields["terminal_status"] == "local_deadline"


def test_genuine_provider_failure_keeps_provider_exhaustion(caplog) -> None:
    clock = FakeClock()
    transport = FakeTransport(
        [(1.0, provider_error(503)), (1.0, provider_error(503)), (1.0, provider_error(503))],
        clock,
    )
    vision = build_vision(
        transport, clock, max_elapsed=30, timeout=10, max_attempts=3, secondary_model=None
    )
    caplog.set_level(logging.INFO, logger="mealog")

    with pytest.raises(RuntimeError, match=r"Gemini provider exhausted after 3 attempt\(s\)"):
        vision.perceive(VisionInput(text="rice"))

    events = {record.getMessage(): record for record in caplog.records}
    assert "vision_local_deadline" not in events
    assert events["vision_provider_exhausted"].extra_fields["terminal_status"] == 503


def test_model_version_names_the_model_that_answered() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        [provider_response(model_version="gemini-3.5-flash-lite")], clock
    )
    vision = build_vision(transport, clock, secondary_model=None)

    vision.perceive(VisionInput(text="rice"))

    assert vision.model_id == "gemini-flash-lite-latest"
    assert vision.last_model == "gemini-flash-lite-latest"
    assert vision.last_model_version == "gemini-3.5-flash-lite"
    assert vision.last_served_model == "gemini-3.5-flash-lite"


def test_missing_model_version_falls_back_to_the_requested_id() -> None:
    clock = FakeClock()
    transport = FakeTransport([provider_response()], clock)
    vision = build_vision(transport, clock, secondary_model=None)

    vision.perceive(VisionInput(text="rice"))

    assert vision.last_model_version is None
    assert vision.last_served_model == vision.model_id == "gemini-flash-lite-latest"


def test_observed_model_versions_accumulate_across_calls() -> None:
    clock = FakeClock()
    transport = FakeTransport(
        [
            provider_response(model_version="gemini-3.5-flash-lite"),
            provider_response(model_version="gemini-3.6-flash-lite"),
            provider_response(model_version="gemini-3.5-flash-lite"),
        ],
        clock,
    )
    vision = build_vision(transport, clock, secondary_model=None)

    for _ in range(3):
        vision.perceive(VisionInput(text="rice"))

    assert vision.observed_model_versions == [
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash-lite",
    ]
    # The per-call attributes still describe only the most recent response.
    assert vision.last_model_version == "gemini-3.5-flash-lite"


def test_shipping_prompt_and_variant_are_untouched() -> None:
    vision = GeminiVision("key", request_interval=0, secondary_model=None)

    assert vision.prompt_variant == vision_gemini.PROMPT_VERSION == "p4"
    assert vision.system_prompt is vision_gemini.SYSTEM_PROMPT
