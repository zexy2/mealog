"""Offline regression tests for the messy-input retrieval set in issue #84."""
import json
from pathlib import Path

import pytest
from conftest import pack_installed

from mealog.locales.loader import load
from mealog.pipeline.normalize import fold
from mealog.pipeline.resolve import resolve
from mealog.pipeline.retrieval import search

VARIANTS = Path(__file__).resolve().parents[2] / "eval" / "golden" / "query_variants.jsonl"


def rows() -> list[dict]:
    return [json.loads(line) for line in VARIANTS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def positive_rows() -> list[dict]:
    return [row for row in rows()
            if row.get("role", "positive") == "positive"
            and row.get("expected_food_id") is not None]


def negative_rows() -> list[dict]:
    return [row for row in rows() if row.get("expected_food_id") is None]


def confusion_rows() -> list[dict]:
    return [row for row in rows() if row.get("role") == "confusion"]


def _skipped(locale: str) -> str | None:
    """Skip rows whose pack is licence-restricted and not installed."""
    if pack_installed(locale):
        return None
    return f"locale pack {locale!r} is licence-restricted and not installed (run `make pack`)"


def query_for(row: dict) -> tuple[str, object]:
    pack = load(row["locale"])
    query = fold(row.get("retrieval_query", row["query"]), pack)
    return query, pack


def test_dataset_has_sixty_turkish_positive_inputs_and_ten_negatives():
    turkish = [row for row in positive_rows() if row["locale"] == "tr"]
    assert len(turkish) >= 60
    assert len(negative_rows()) >= 10
    assert any(row["query"] == "lahmakun" for row in turkish)
    assert any(row["query"] == "bi simit bi ayran" for row in turkish)
    assert any(row["query"] == "2 adet lahmacun" for row in turkish)


@pytest.mark.parametrize(
    "row",
    positive_rows(),
    ids=lambda row: f"{row['locale']}-{row['kind']}-{row['query']}",
)
def test_positive_variant_ranks_expected_food_first(row: dict):
    if reason := _skipped(row["locale"]):
        pytest.skip(reason)
    query, pack = query_for(row)
    candidates = search(query, pack)
    assert candidates, f"no candidates for {row['query']!r}"
    assert candidates[0].food_id == row["expected_food_id"], row["query"]


@pytest.mark.parametrize(
    "row",
    negative_rows(),
    ids=lambda row: f"{row['locale']}-{row['kind']}-{row['query']}",
)
def test_negative_variant_abstains_and_never_returns_forbidden_food(row: dict):
    if reason := _skipped(row["locale"]):
        pytest.skip(reason)
    query, pack = query_for(row)
    resolved = resolve(query, search(query, pack), allow_abstain=True)
    forbidden = set(row.get("forbidden_food_ids", []))
    assert resolved.abstained, f"{row['query']!r} resolved to {resolved.food_id}"
    assert resolved.food_id not in forbidden


@pytest.mark.parametrize(
    "row",
    confusion_rows(),
    ids=lambda row: f"{row['locale']}-{row['query']}",
)
def test_documented_confusion_surfaces_neighbour_but_abstains(row: dict):
    if reason := _skipped(row["locale"]):
        pytest.skip(reason)
    query, pack = query_for(row)
    candidates = search(query, pack)
    confusable = row.get("confusable_food_id")
    assert confusable in [candidate.food_id for candidate in candidates]
    assert resolve(query, candidates, allow_abstain=True).abstained
