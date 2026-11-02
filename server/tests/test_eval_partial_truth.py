"""Regression tests for partial Nutrition5k calorie truth in the evaluator."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

from harness import calorie_truth_complete, check_regression, scorecard
from metrics import SampleResult, aggregate


def result(**overrides: object) -> SampleResult:
    values: dict[str, object] = {
        "sample_id": "sample",
        "cuisine": "western",
        "tier": "tier_1",
        "truth_ids": {"food"},
        "pred_ids": {"food"},
        "truth_kcal": 100.0,
        "pred_kcal": 110.0,
        "truth_grams": {"food": 100.0},
        "pred_grams": {"food": 100.0},
    }
    values.update(overrides)
    return SampleResult(**values)  # type: ignore[arg-type]


def test_complete_positive_calorie_truth_computes_ape():
    assert result().ape == 10.0


def test_n5k_0010_partial_truth_is_not_calorie_eligible():
    rows = [
        json.loads(line)
        for line in (ROOT / "eval/golden/manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entry = next(row for row in rows if row["sample_id"] == "n5k_0010")

    assert [item["food_id"] for item in entry["truth"]["items"]] == [
        "us.rice_white_cooked",
        "us.pork_roasted",
        "us.tofu_firm",
    ]
    assert {item["name"] for item in entry["unmapped_source_ingredients"]} == {
        "pepper", "bok choy", "garlic", "soy sauce", "salt", "sugar",
    }
    assert not calorie_truth_complete(entry)
    assert result(calorie_eligible=False, truth_kcal=205.4, pred_kcal=5.4).ape is None


def test_zero_truth_remains_non_scoring():
    zero = result(truth_kcal=0.0, pred_kcal=110.0)

    assert zero.ape is None
    _, overall = aggregate([zero])
    assert overall.calorie_eligible == 0
    assert overall.apes == []


def test_partial_truth_keeps_identity_and_coverage_metrics():
    complete = result(pred_ids={"food", "extra"})
    partial = result(
        calorie_eligible=False,
        truth_kcal=205.4,
        pred_kcal=5.4,
        pred_ids={"food", "extra"},
    )

    buckets, overall = aggregate([partial])
    _, complete_overall = aggregate([complete])

    assert buckets["western"].n == 1
    assert buckets["western"].coverage == 100.0
    assert buckets["western"].f1 == complete_overall.f1
    assert buckets["western"].hallucination_rate == complete_overall.hallucination_rate
    assert partial.error_codes == complete.error_codes
    assert overall.calorie_eligible == 0
    assert overall.apes == []


def test_empty_calorie_denominator_renders_dash_not_zero_accuracy():
    report = scorecard({"V3": [result(calorie_eligible=False)]})

    assert "| **overall** | **1** | **100%** | **0** | **0** | **1.00** | **—** | **—** |" in report
    assert "| **1.00** | **—** | **—** | **0.0%** |" in report


def test_regression_guard_does_not_call_empty_denominator_an_improvement(tmp_path, monkeypatch):
    import harness

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"western": 12.69}), encoding="utf-8")
    monkeypatch.setattr(harness, "BASELINE", baseline)

    status = check_regression({"V3": [result(calorie_eligible=False)]})

    assert status == 1
