"""The identity diagnosis must reproduce the scorecard it explains.

`eval/identity_diagnosis.py` attributes every truth item and false positive to a
stage. That attribution is only useful if it charges exactly the same items the
scorecard scores; otherwise it explains a different run. These tests assert the
arithmetic of the attribution against the scored path, and that the committed
document is what the current fixtures generate.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mealog_identity_diagnosis", ROOT / "eval" / "identity_diagnosis.py"
)
assert SPEC is not None and SPEC.loader is not None
diagnosis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnosis
SPEC.loader.exec_module(diagnosis)


@pytest.fixture(scope="module")
def report() -> dict:
    return diagnosis.diagnose()


def test_every_truth_item_is_attributed_once(report: dict) -> None:
    outcomes = report["outcomes"]
    assert set(outcomes) == set(diagnosis.OUTCOMES)
    assert all(value >= 0 for value in outcomes.values())
    assert sum(outcomes.values()) == report["truth_items"]
    assert report["truth_items"] > 0


def test_attribution_reproduces_the_scorecard(report: dict) -> None:
    agreement = report["agreement"]
    assert agreement["matches"] is True, agreement
    assert agreement["attributed_tp"] == agreement["scorecard_tp"]
    assert agreement["attributed_fp"] == agreement["scorecard_fp"]
    # The F1 the diagnosis derives from its own counts is the published one.
    assert round(report["item_f1"], 2) == 0.38


def test_false_positives_are_classified_exactly_once(report: dict) -> None:
    fps = report["false_positives"]
    assert fps["named"] + fps["fuzzy"] == fps["total"]
    assert 0 <= fps["on_partial_truth"] <= fps["total"]


def test_a_perfect_resolver_cannot_exceed_the_perception_ceiling(report: dict) -> None:
    outcomes = report["outcomes"]
    reachable = outcomes["resolved"] + outcomes["gating"] + outcomes["ranking"]
    never = outcomes["never_perceived"]
    expected = 2 * reachable / (2 * reachable + never)
    assert report["perfect_resolver_f1"] == pytest.approx(round(expected, 3))


def test_the_committed_diagnosis_matches_the_fixtures() -> None:
    markdown = diagnosis.render_markdown(diagnosis.diagnose())
    committed = (ROOT / "docs" / "identity-diagnosis.md").read_text(encoding="utf-8")
    assert committed == markdown, (
        "docs/identity-diagnosis.md is stale; regenerate it with "
        "`python eval/identity_diagnosis.py --out docs/identity-diagnosis.md`"
    )
