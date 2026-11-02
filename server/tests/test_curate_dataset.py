import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conftest import requires_pack
from scripts.curate_dataset import curate_events


def test_missing_input_fails_without_creating_bootstrap_data(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"

    with pytest.raises(FileNotFoundError, match="telemetry input does not exist"):
        curate_events(missing, tmp_path / "out")

    assert not missing.exists()


@requires_pack("tr")
def test_review_candidates_keep_hash_and_never_emit_raw_idempotency_key(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    request_hash = "a" * 64
    events.write_text(
        json.dumps(
            {
                "request_hash": request_hash,
                "items": [
                    {
                        "original_query": "pilav",
                        "predicted_food_id": "tr.bulgur_pilavi",
                        "selected_food_id": "tr.pilav",
                        "predicted_grams": 180,
                        "selected_grams": 220,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "review"

    stats = curate_events(events, out_dir)

    assert stats["swaps"] == 1
    assert stats["portion_adjustments"] == 1
    for output_name in ("ft2_vision_alignment.jsonl", "ft1_portion_regression.jsonl"):
        row = json.loads((out_dir / output_name).read_text(encoding="utf-8"))
        assert row["request_hash"] == request_hash
        assert "idempotency_key" not in row


def test_invalid_request_hash_fails_loudly(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text('{"items": []}\n', encoding="utf-8")

    # A finite catalogue that is not the restricted Turkish one, so the test
    # exercises the event validation rather than the pack install step.
    with pytest.raises(ValueError, match="missing or invalid request_hash"):
        curate_events(events, tmp_path / "out", locale="en_US")
