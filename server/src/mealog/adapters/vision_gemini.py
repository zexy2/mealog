"""Live Gemini vision adapter.

The adapter owns only provider I/O and response validation. It returns observed
items, never catalogue IDs or nutrient values. The evaluation harness can turn
that validated response into an offline fixture without storing the input image
or the API response envelope.
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import re
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from mealog import obs
from mealog.domain.models import CountOrigin, PerceivedItem
from mealog.pipeline.ports import VisionInput

PROMPT_VERSION = "p4"
DEFAULT_MODEL = "gemini-flash-lite-latest"
SECONDARY_MODEL = "gemini-2.5-flash-lite"
MODEL_ENV_VAR = "GEMINI_MODEL"
MAX_ELAPSED_ENV_VAR = "GEMINI_MAX_ELAPSED_SECONDS"
REQUEST_INTERVAL_SECONDS = 4.0
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
MAX_ERROR_BODY = 500
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
NON_RETRYABLE_STATUS_CODES = frozenset({400, 401})
MAX_ATTEMPTS = 3
MAX_ELAPSED_SECONDS = 30.0
BACKOFF_BASE_SECONDS = 0.25
BACKOFF_CAP_SECONDS = 2.0
RUNG_CONFIGURED_MODEL = "configured_model"
RUNG_SECONDARY_MODEL = "secondary_model"
RUNG_TEXT_ONLY = "text_only"
RUNG_FAILURE = "failure"

SYSTEM_PROMPT = """You list what food is visible in the supplied image or text.
Return observed items only. You do NOT estimate calories, macros, nutrients, or
grams. The downstream catalogue and nutrition stages handle those values.

Rules:
- Name dishes in the language on the plate's origin if you recognise it.
- If unsure between two dishes, return the more general one and lower confidence.
- Never invent an item you cannot see. Omission is cheaper than invention.
- Counting precision rules:
  * For individually countable food items that are clearly and distinctly visible as single standalone items (e.g. a single whole simit on a plate, one apple, one boiled egg, a standalone whole pastry, or a single glass of drink), return `count: 1`.
  * For multiple countable items where each instance is distinctly separated and completely visible, return the exact integer count (e.g. `count: 2`).
  * Only when instances are overlapping, stacked, cropped, occluded, or when the exact total quantity is genuinely ambiguous, return `count: null`; never guess. Two stacked simit rings are an occluded arrangement: return `count: null` even if two rings appear recognisable.
- Return one `items[]` object for each distinct primary prepared dish or edible side dish. Never combine multiple visible foods into one `surface_form`: do not return comma-separated or conjunction-linked food lists. A plate with meatballs, rice, bread, and salad has four item objects.
- A single serving in one glass, bowl, plate, or other container is one observed
  item: return one item with `count: null`. Never count liquid volume, pixels,
  or a serving container as multiple food instances. Do not report garnish,
  decorative leaves, or unidentifiable background as separate food items. Do not
  add ABSTAIN or other placeholder items.
- `count` is the only count field. Keep `portion_hint` non-numeric: use a
  qualitative description such as `whole`, `bowl`, or `stacked`, never a count,
  gram estimate, or numeric serving estimate.
- Set `medium` to exactly one of `real_plate`, `screen`, `printed`,
  `toy_or_model`, or `unclear` for every observed item. Use `screen` for food
  shown inside a display, `printed` for paper, packaging, or other printed
  imagery, and `toy_or_model` for a toy, miniature, moulded replica, or
  obviously synthetic food. Use `real_plate` only for a real serving
  photographed directly. If you cannot tell, or the image is torn between a
  real serving and another medium, use `unclear`. `real_plate` is neutral
  evidence, never positive evidence.
"""

_P5_SYSTEM_PROMPT = """You list what food is visible in the supplied image or text.
Return observed items only. You do NOT estimate calories, macros, nutrients, or
grams. The downstream catalogue and nutrition stages handle those values.

Rules:
- Name dishes in the language on the plate's origin if you recognise it.
- If unsure between two dishes, return the more general one and lower confidence.
- Never invent an item you cannot see. Omission is cheaper than invention.
- Counting precision rules:
  * For individually countable food items that are clearly and distinctly visible as single standalone items (e.g. a single whole simit on a plate, one apple, one boiled egg, a standalone whole pastry, or a single glass of drink), return `count: 1`.
  * For multiple countable items where each instance is distinctly separated and completely visible, return the exact integer count (e.g. `count: 2`).
  * Only when instances are overlapping, stacked, cropped, occluded, or when the exact total quantity is genuinely ambiguous, return `count: null`; never guess. Two stacked simit rings are an occluded arrangement: return `count: null` even if two rings appear recognisable.
- Decompose composite surfaces into their visible components. When the components are distinguishable, return one `items[]` object per component; never return `rice and meat` or `chicken salad` as one item. A plate with meatballs, rice, bread, and salad has four item objects. Never combine multiple visible foods into one `surface_form`: do not return comma-separated or conjunction-linked food lists.
- List visible fats, oils, dressings, sauces, garnishes, and drinks as their own items when they are visible or clearly implied by the plate (a glisten of oil, a dressing pool, a sauce ladle). Give each a small portion (a qualitative `small` or `a drizzle`, never a gram estimate) rather than omitting it because it is small. A clearly implied item must still be supported by visible evidence; do not use this rule to invent food that is not there.
- A single serving in one glass, bowl, plate, or other container is one observed
  item: return one item with `count: null`. Never count liquid volume, pixels,
  or a serving container as multiple food instances. Do not report inedible
  decorative leaves or unidentifiable background as separate food items. Do not
  add ABSTAIN or other placeholder items.
- Return every item with all required schema fields: `surface_form`,
  `cooking_method`, `portion_hint`, `count`, `medium`, and `confidence`.
- `count` is the only count field. Keep `portion_hint` non-numeric: use a
  qualitative description such as `whole`, `bowl`, `stacked`, `small`, or
  `a drizzle`, never a count, gram estimate, or numeric serving estimate.
- Set `medium` to exactly one of `real_plate`, `screen`, `printed`,
  `toy_or_model`, or `unclear` for every observed item. Use `screen` for food
  shown inside a display, `printed` for paper, packaging, or other printed
  imagery, and `toy_or_model` for a toy, miniature, moulded replica, or
  obviously synthetic food. Use `real_plate` only for a real serving
  photographed directly. If you cannot tell, or the image is torn between a
  real serving and another medium, use `unclear`. `real_plate` is neutral
  evidence, never positive evidence.
"""

#: Named prompt variants. ``p4`` is the shipped prompt and is kept byte-for-byte
#: as it was, so the default path cannot drift. ``p5`` is an opt-in experiment.
PROMPTS: dict[str, str] = {
    "p4": SYSTEM_PROMPT,
    "p5": _P5_SYSTEM_PROMPT,
}
PROMPT_VARIANTS: tuple[str, ...] = tuple(PROMPTS)


class UnknownPromptVariant(ValueError):
    """The requested prompt variant is not one this adapter can send."""


def prompt_for_variant(name: str) -> str:
    """Return the system prompt for ``name`` or fail with the valid names.

    Resolving eagerly (rather than at request time) means a typo cannot reach
    the provider, and the error tells the caller what it could have asked for.
    """
    try:
        return PROMPTS[name]
    except KeyError:
        available = ", ".join(PROMPT_VARIANTS)
        raise UnknownPromptVariant(
            f"unknown prompt variant '{name}'; available variants: {available}"
        ) from None


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "surface_form": {
                        "type": "STRING",
                        "description": "The visible dish or food name.",
                    },
                    "cooking_method": {
                        "type": "STRING",
                        "description": "Visible or explicitly stated cooking method.",
                    },
                    "portion_hint": {
                        "type": "STRING",
                        "description": "Non-numeric serving description, if visible or stated.",
                    },
                    "count": {
                        "type": "INTEGER",
                        "nullable": True,
                        "minimum": 1,
                        "description": "Count only when each individually countable instance is distinctly visible; otherwise null.",
                    },
                    "medium": {
                        "type": "STRING",
                        "enum": ["real_plate", "screen", "printed", "toy_or_model", "unclear"],
                        "description": "Capture medium; real_plate is neutral, every other value is a safety red flag.",
                    },
                    "confidence": {
                        "type": "NUMBER",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Confidence that this item is present, from 0 to 1.",
                    },
                },
                "required": [
                    "surface_form",
                    "cooking_method",
                    "portion_hint",
                    "count",
                    "medium",
                    "confidence",
                ],
            },
        }
    },
    "required": ["items"],
}

_FORBIDDEN_NUTRIENT_FIELDS = {
    "kcal",
    "calories",
    "carb_g",
    "fat_g",
    "food_id",
    "grams",
    "nutrients",
    "protein_g",
    "ungrounded_kcal",
}
_ALLOWED_ITEM_FIELDS = frozenset(RESPONSE_SCHEMA["properties"]["items"]["items"]["properties"])
_CONTAINER_HINT = re.compile(r"\b(?:bowl|glass|cup|plate|serving|container)\b", re.IGNORECASE)
_IMAGE_MIME_FALLBACKS = {
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_ALLOWED_IMAGE_MIME_TYPES = frozenset(_IMAGE_MIME_FALLBACKS.values()) | {"image/jpg"}


def configured_model_id() -> str:
    """Read the live model from environment-backed application config."""
    return os.getenv(MODEL_ENV_VAR, DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _validated_seconds(value: object, source: str) -> float:
    """Return ``value`` as a positive finite number of seconds, or fail.

    The budget is a measurement input, so a typo must stop the run rather than
    silently become a smaller or larger ceiling. Clamping was the original bug:
    a caller asking for 180 s got 30 s and no error.
    """
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        seconds = math.nan
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(
            f"{source} must be a finite number of seconds greater than 0; got {value!r}"
        )
    return seconds


def resolve_max_elapsed(explicit: float | None = None) -> float:
    """Resolve the per-row wall-clock budget in documented precedence order.

    An explicit argument wins over the environment, which wins over the shipped
    constant. Resolution happens at construction time, so a caller (or an
    environment variable set for the process) can raise the budget without
    editing this module. There is no hidden upper clamp: the configured value is
    the effective value, and ``_validated_seconds`` rejects nonsense instead of
    quietly reducing it.
    """
    if explicit is not None:
        return _validated_seconds(explicit, "max_elapsed")
    raw = os.getenv(MAX_ELAPSED_ENV_VAR)
    if raw is None or not raw.strip():
        return MAX_ELAPSED_SECONDS
    return _validated_seconds(raw.strip(), MAX_ELAPSED_ENV_VAR)


class _ProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        fallback_allowed: bool = True,
        retry_after: float | None = None,
        attempts: int = 0,
        local_deadline: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.fallback_allowed = fallback_allowed
        self.retry_after = retry_after
        self.attempts = attempts
        self.local_deadline = local_deadline


def _retry_after_seconds(headers: Any) -> float | None:
    value = headers.get("Retry-After") if headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _is_timeout(error: BaseException) -> bool:
    reason = getattr(error, "reason", error)
    return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()


def _image_part(input_ref: VisionInput) -> dict[str, Any]:
    if input_ref.image_bytes is None or not input_ref.image_media_type:
        raise ValueError("Gemini image input needs bytes and a MIME type")
    mime_type = input_ref.image_media_type.lower()
    if mime_type not in _ALLOWED_IMAGE_MIME_TYPES:
        raise ValueError(f"unsupported Gemini image MIME type '{mime_type}'")
    if len(input_ref.image_bytes) > 10 * 1024 * 1024:
        raise ValueError("Gemini image exceeds 10 MiB limit")

    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(input_ref.image_bytes).decode("ascii"),
        }
    }


def _response_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        reason = response.get("promptFeedback") or response.get("error") or "no candidates"
        raise RuntimeError(f"Gemini returned no candidate: {reason}")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise TypeError("Gemini returned an invalid candidate")
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text:
        reason = candidate.get("finishReason", "empty response")
        raise RuntimeError(f"Gemini returned no text candidate: {reason}")
    return text


def _parse_items(text: str, count_origin: CountOrigin = None) -> list[PerceivedItem]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini returned non-JSON text despite JSON schema mode") from exc

    if not isinstance(document, dict) or not isinstance(document.get("items"), list):
        raise TypeError("Gemini JSON response must contain an items array")

    parsed: list[PerceivedItem] = []
    for index, raw in enumerate(document["items"]):
        if not isinstance(raw, dict):
            raise TypeError(f"Gemini item {index} is not an object")
        forbidden = _FORBIDDEN_NUTRIENT_FIELDS.intersection(raw)
        if forbidden:
            fields = ", ".join(sorted(forbidden))
            raise RuntimeError(f"Gemini item {index} contains forbidden nutrient field(s): {fields}")
        unknown = set(raw) - _ALLOWED_ITEM_FIELDS
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise RuntimeError(f"Gemini item {index} contains unknown field(s): {fields}")
        if "medium" not in raw:
            raise RuntimeError(f"Gemini item {index} medium is required")
        try:
            item = PerceivedItem.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError(f"Gemini item {index} failed response validation") from exc
        count = raw.get("count")
        if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 1):
            raise RuntimeError(f"Gemini item {index} count must be a positive integer or null")
        if count_origin == "vision" and (
            count == 1
            or (item.portion_hint and _CONTAINER_HINT.search(item.portion_hint))
        ):
            item = item.model_copy(update={"count": None})
        item = item.model_copy(update={"count_origin": count_origin})
        if not item.surface_form.strip():
            raise RuntimeError(f"Gemini item {index} has an empty surface_form")
        if not 0 <= item.confidence <= 1:
            raise RuntimeError(f"Gemini item {index} confidence is outside [0, 1]")
        parsed.append(item)
    return parsed


class GeminiVision:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        timeout: float = 90.0,
        opener: Callable[..., Any] = urlopen,
        secondary_model: str | None = SECONDARY_MODEL,
        max_attempts: int = MAX_ATTEMPTS,
        max_elapsed: float | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        jitter_fn: Callable[[float], float] | None = None,
        request_interval: float = REQUEST_INTERVAL_SECONDS,
        model_id: str | None = None,
        prompt_variant: str = PROMPT_VERSION,
    ):
        if not api_key.strip():
            raise ValueError("GEMINI_API_KEY is required for the live vision provider")
        self.api_key = api_key
        self.prompt_variant = prompt_variant
        self.system_prompt = prompt_for_variant(prompt_variant)
        self.model_id = model_id or model or configured_model_id()
        self.model = self.model_id
        self.timeout = timeout
        self._opener = opener
        self.secondary_model = secondary_model
        self.max_attempts = min(MAX_ATTEMPTS, max(1, max_attempts))
        # No import-time default and no min() clamp: the 2026-11-02 run set
        # MAX_ELAPSED_SECONDS = 180 and silently ran with 30 because the old
        # default argument had already bound and the constructor re-clamped.
        self.max_elapsed = resolve_max_elapsed(max_elapsed)
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._jitter = jitter_fn or (lambda cap: random.uniform(0.0, cap))
        self.request_interval = max(0.0, request_interval)
        self._last_request_started: float | None = None
        self.request_count = 0
        self.last_items: list[PerceivedItem] | None = None
        self.last_input: VisionInput | None = None
        self.degraded = False
        self.rung = RUNG_CONFIGURED_MODEL
        self.last_model = self.model_id
        # ``last_model`` stays the requested id of the rung that answered,
        # which is what fixture_payload has always stamped. The provider's
        # ``modelVersion`` is separate so an alias like
        # ``gemini-flash-lite-latest`` cannot stand in for what was served.
        self.last_model_version: str | None = None
        self.last_served_model = self.model_id
        #: Ordered, de-duplicated versions seen across every successful call.
        #: The run is not a single-model measurement if this holds more than one.
        self.observed_model_versions: list[str] = []
        self.last_attempts = 0

    def _wait_for_request_slot(self) -> None:
        now = self._clock()
        if self._last_request_started is not None:
            remaining = self.request_interval - (now - self._last_request_started)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_started = self._clock()

    def _request(
        self,
        parts: list[dict[str, Any]],
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "systemInstruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
        request_model = model or self.model
        url = f"{API_ROOT}/models/{quote(request_model, safe='')}:generateContent"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        self.request_count += 1
        try:
            with self._opener(request, timeout=timeout or self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:MAX_ERROR_BODY]
            status = exc.code
            raise _ProviderFailure(
                f"Gemini request failed with HTTP {status}: {detail}",
                status=status,
                retryable=status in TRANSIENT_STATUS_CODES,
                fallback_allowed=status not in NON_RETRYABLE_STATUS_CODES,
                retry_after=_retry_after_seconds(exc.headers),
            ) from exc
        except TimeoutError as exc:
            raise _ProviderFailure("Gemini request timed out", retryable=True) from exc
        except URLError as exc:
            raise _ProviderFailure(
                f"Gemini request failed: {exc.reason}",
                retryable=_is_timeout(exc),
            ) from exc
        except json.JSONDecodeError as exc:
            raise _ProviderFailure(
                "Gemini returned an invalid JSON envelope",
                fallback_allowed=True,
            ) from exc

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        exponential = min(
            BACKOFF_CAP_SECONDS,
            BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
        )
        jittered = min(BACKOFF_CAP_SECONDS, exponential + max(0.0, self._jitter(exponential)))
        return max(retry_after or 0.0, jittered)

    def _local_deadline_failure(
        self,
        attempts: int,
        last_failure: _ProviderFailure | None = None,
    ) -> _ProviderFailure:
        """Name the local ceiling, keeping any provider detail that preceded it."""
        detail = f"; last provider failure: {last_failure}" if last_failure else ""
        return _ProviderFailure(
            f"local deadline of {self.max_elapsed:g}s reached after {attempts} attempt(s){detail}",
            attempts=attempts,
            local_deadline=True,
        )

    def _request_with_retry(
        self,
        parts: list[dict[str, Any]],
        model: str,
        deadline: float,
    ) -> tuple[dict[str, Any], int]:
        attempts = 0
        last_failure: _ProviderFailure | None = None
        while attempts < self.max_attempts:
            # Pacing is part of starting a request, so account for it before
            # deciding whether this attempt fits. That keeps the bound exact:
            # nothing starts after the deadline, and the only overrun is the
            # request timeout of an attempt that already started in time.
            self._wait_for_request_slot()
            if deadline - self._clock() <= 0:
                # An attempt that starts before the deadline may finish after
                # it; an attempt that has not started by then never starts.
                # Reaching this guard means our own clock, not the provider,
                # stopped the ladder.
                raise self._local_deadline_failure(attempts, last_failure)
            attempts += 1
            try:
                # A request gets its own timeout. The ladder budget governs
                # retries and fallbacks; it must not truncate the first answer
                # before the model has had the time the caller configured.
                return self._request(parts, model=model, timeout=self.timeout), attempts
            except _ProviderFailure as exc:
                last_failure = exc
                if not exc.retryable or attempts >= self.max_attempts:
                    break
                delay = self._retry_delay(attempts, exc.retry_after)
                if delay >= deadline - self._clock():
                    raise self._local_deadline_failure(attempts, last_failure) from exc
                self._sleep(delay)

        if last_failure is None:
            raise self._local_deadline_failure(attempts)
        last_failure.attempts = attempts
        raise last_failure

    def _parts(self, input_ref: VisionInput, *, include_image: bool) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if include_image and input_ref.image_bytes is not None:
            parts.append(_image_part(input_ref))
        elif not input_ref.text or not input_ref.text.strip():
            raise FileNotFoundError(
                "live Gemini provider requires image bytes or explicit text; sample_id is fixture-only"
            )

        if input_ref.text and input_ref.text.strip():
            parts.append({"text": input_ref.text.strip()})
        parts.append({"text": "List only the visible food items using the required JSON schema."})
        return parts

    def perceive(self, input_ref: VisionInput) -> list[PerceivedItem]:
        """Call Gemini with bounded retries and explicit fallback metadata."""
        has_image = input_ref.image_bytes is not None
        self.last_input = input_ref
        self.last_items = None
        self.degraded = False
        self.rung = RUNG_CONFIGURED_MODEL
        self.last_model = self.model_id
        self.last_model_version = None
        self.last_served_model = self.model_id
        self.last_attempts = 0
        started = self._clock()
        deadline = started + self.max_elapsed

        rung_chain: list[tuple[str, str, bool]] = [(RUNG_CONFIGURED_MODEL, self.model, True)]
        if self.secondary_model and self.secondary_model != self.model:
            rung_chain.append((RUNG_SECONDARY_MODEL, self.secondary_model, True))
        if has_image and input_ref.text and input_ref.text.strip():
            rung_chain.append(
                (RUNG_TEXT_ONLY, self.secondary_model or self.model, False)
            )

        failures: list[tuple[str, str, _ProviderFailure]] = []
        total_attempts = 0
        deadline_hit = False
        for rung, model, include_image in rung_chain:
            if self._clock() >= deadline:
                deadline_hit = True
                break
            parts = self._parts(input_ref, include_image=include_image)
            attempts = 0
            try:
                response, attempts = self._request_with_retry(parts, model, deadline)
                items = _parse_items(
                    _response_text(response),
                    "vision" if has_image else "user_text",
                )
            except _ProviderFailure as exc:
                total_attempts += exc.attempts
                failures.append((rung, model, exc))
                if exc.local_deadline:
                    deadline_hit = True
                    break
                if not exc.fallback_allowed:
                    break
                continue
            except (RuntimeError, TypeError, ValueError) as exc:
                total_attempts += attempts
                failure = _ProviderFailure(str(exc), attempts=attempts)
                failures.append((rung, model, failure))
                continue

            total_attempts += attempts
            self.last_items = items
            self.last_model = model
            version = response.get("modelVersion") if isinstance(response, dict) else None
            self.last_model_version = (
                version.strip() if isinstance(version, str) and version.strip() else None
            )
            self.last_served_model = self.last_model_version or model
            if (
                self.last_model_version
                and self.last_model_version not in self.observed_model_versions
            ):
                self.observed_model_versions.append(self.last_model_version)
            self.last_attempts = total_attempts
            self.degraded = rung != RUNG_CONFIGURED_MODEL
            self.rung = rung
            if self.degraded:
                obs.event(
                    "vision_fallback",
                    rung=rung,
                    model=model,
                    served_model=self.last_served_model,
                    model_version=self.last_model_version,
                    attempts=total_attempts,
                    max_elapsed=self.max_elapsed,
                )
            return items

        if failures:
            last_rung, last_model, last_failure = failures[-1]
        else:
            last_rung, last_model = RUNG_CONFIGURED_MODEL, self.model
            last_failure = self._local_deadline_failure(0)
        if deadline_hit and not last_failure.local_deadline:
            # A provider failure came first, but the fallback rung never got a
            # chance because our own ceiling expired. Keep the provider detail
            # in the message while naming the actual stop condition.
            last_failure = self._local_deadline_failure(total_attempts, last_failure)
        self.degraded = True
        self.rung = RUNG_FAILURE
        self.last_model = last_model
        self.last_model_version = None
        self.last_served_model = last_model
        self.last_attempts = total_attempts
        elapsed_ms = round((self._clock() - started) * 1000, 2)
        if last_failure.local_deadline:
            obs.event(
                "vision_local_deadline",
                attempts=total_attempts,
                terminal_status="local_deadline",
                elapsed_ms=elapsed_ms,
                rung=last_rung,
                max_elapsed=self.max_elapsed,
            )
            raise RuntimeError(
                f"Gemini local deadline of {self.max_elapsed:g}s reached after "
                f"{total_attempts} attempt(s); terminal_status=local_deadline; "
                f"rung={last_rung}: {last_failure}"
            ) from last_failure
        obs.event(
            "vision_provider_exhausted",
            attempts=total_attempts,
            terminal_status=last_failure.status,
            elapsed_ms=elapsed_ms,
            rung=last_rung,
            max_elapsed=self.max_elapsed,
            requested_model=self.model_id,
        )
        status = last_failure.status if last_failure.status is not None else "unknown"
        raise RuntimeError(
            f"Gemini provider exhausted after {total_attempts} attempt(s); "
            f"terminal_status={status}; rung={last_rung}: {last_failure}"
        ) from last_failure

    def fixture_payload(self, input_ref: VisionInput, items: list[PerceivedItem]) -> dict[str, Any]:
        """Return safe, deterministic fixture data from a validated response."""
        if not input_ref.fixture_key:
            raise ValueError("fixture recording needs an image hash or sample_id")
        return {
            "_synthetic": False,
            "sample_id": input_ref.sample_id,
            "input_sha256": input_ref.content_hash,
            "provider": self.name,
            "model_id": self.last_model,
            "prompt_version": self.prompt_variant,
            "input_kind": "user_text" if input_ref.text and input_ref.text.strip() else "vision",
            "degraded": self.degraded,
            "rung": self.rung,
            "attempts": self.last_attempts,
            "items": [item.model_dump(exclude_none=True, exclude={"count_origin"}) for item in items],
        }

    def record_fixture(
        self, directory: Path, input_ref: VisionInput, path: Path | None = None
    ) -> Path:
        """Persist last validated observations without the image or envelope."""
        if self.last_items is None or self.last_input != input_ref:
            raise ValueError("record_fixture must follow a successful perceive call")
        key = input_ref.fixture_key
        if not key:
            raise ValueError("fixture recording needs an image hash or sample_id")
        directory.mkdir(parents=True, exist_ok=True)
        path = path or directory / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.fixture_payload(input_ref, self.last_items), indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path
