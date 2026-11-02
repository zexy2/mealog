#!/usr/bin/env python3
"""Record real Gemini observations for the current golden manifest.

The script deliberately owns the live recording loop instead of changing the
offline harness. The default model writes the files that ``make eval`` replays;
other model IDs are kept under ``eval/fixtures/models/`` for comparison.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "eval/golden/manifest.jsonl"
DEFAULT_IMAGES = ROOT / "data/golden-images"
DEFAULT_FIXTURES = ROOT / "eval/fixtures"
MODEL_DIRECTORY = "models"

sys.path.insert(0, str(ROOT / "server" / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from golden_inputs import input_for_row, load_manifest

from mealog.adapters.vision_gemini import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    REQUEST_INTERVAL_SECONDS,
    GeminiVision,
    configured_model_id,
)


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _safe_model_id(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_id)


def _fixture_matches(path: Path, sample_id: str, model_id: str) -> bool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(raw, dict)
        and raw.get("sample_id") == sample_id
        and raw.get("provider") == "gemini"
        and raw.get("model_id") == model_id
        and raw.get("prompt_version") == PROMPT_VERSION
        and raw.get("_synthetic") is False
    )


def _existing_fixture(fixture_dir: Path, sample_id: str, model_id: str) -> Path | None:
    for path in sorted(fixture_dir.rglob("*.json")):
        if _fixture_matches(path, sample_id, model_id):
            return path
    return None


def _model_fixture_dir(fixture_dir: Path, model_id: str) -> Path:
    if model_id == DEFAULT_MODEL:
        return fixture_dir
    return fixture_dir / MODEL_DIRECTORY / _safe_model_id(model_id)


def _fixture_path(fixture_dir: Path, model_id: str, sample_id: str) -> Path:
    return _model_fixture_dir(fixture_dir, model_id) / f"{sample_id}.json"


def record_model(
    *,
    rows: list[dict[str, Any]],
    api_key: str,
    model_id: str,
    images_dir: Path,
    fixture_dir: Path,
    request_interval: float = REQUEST_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Record one model, skipping only matching real fixtures."""
    started = time.monotonic()
    vision = GeminiVision(
        api_key,
        model_id=model_id,
        # Recording compares exact model IDs. A degradation fallback would
        # produce a fixture for another model under this run's directory.
        secondary_model=None,
        request_interval=request_interval,
    )
    recorded = 0
    skipped = 0
    target_dir = _model_fixture_dir(fixture_dir, model_id)

    for row in rows:
        sample_id = row["sample_id"]
        existing = _existing_fixture(fixture_dir, sample_id, model_id)
        if existing is not None:
            print(f"skip {sample_id}: {existing.relative_to(fixture_dir)}")
            skipped += 1
            continue

        input_ref = input_for_row(row, images_dir)
        try:
            vision.perceive(input_ref)
            path = _fixture_path(fixture_dir, model_id, sample_id)
            vision.record_fixture(target_dir, input_ref, path=path)
        except Exception as exc:
            raise RuntimeError(
                f"recording failed for sample {sample_id} with model {model_id}: {exc}"
            ) from exc
        print(f"record {sample_id}: {path.relative_to(fixture_dir)}")
        recorded += 1

    elapsed = time.monotonic() - started
    summary = {
        "model_id": model_id,
        "recorded": recorded,
        "skipped": skipped,
        "requests": vision.request_count,
        "elapsed_seconds": round(elapsed, 2),
        "estimated_cost_usd": 0.0,
    }
    print(
        "summary "
        f"model_id={model_id} recorded={recorded} skipped={skipped} "
        f"requests={vision.request_count} elapsed_seconds={summary['elapsed_seconds']:.2f} "
        "estimated_cost_usd=0.00"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--images-dir", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--model", default=None, help="override GEMINI_MODEL for this run")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=REQUEST_INTERVAL_SECONDS,
        help="minimum seconds between provider requests (default: 4)",
    )
    args = parser.parse_args(argv)

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key.strip():
        parser.error("GEMINI_API_KEY is required; value is never written to fixtures or logs")
    if args.request_interval < 0:
        parser.error("--request-interval cannot be negative")

    manifest = _resolve(args.manifest)
    images_dir = _resolve(args.images_dir)
    fixture_dir = _resolve(args.fixtures_dir)
    model_id = (args.model or configured_model_id()).strip()
    if not model_id:
        parser.error("model ID cannot be empty")

    summary = record_model(
        rows=load_manifest(manifest),
        api_key=api_key,
        model_id=model_id,
        images_dir=images_dir,
        fixture_dir=fixture_dir,
        request_interval=args.request_interval,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
