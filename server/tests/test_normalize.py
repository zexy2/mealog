"""Portion hints must preserve quantity evidence instead of silently dropping it."""
import pytest
from conftest import requires_pack

from mealog.domain.models import PerceivedItem
from mealog.locales.loader import load
from mealog.pipeline.normalize import normalize, parse_portion


@pytest.mark.parametrize(
    ("locale", "hint", "expected_quantity", "expected_unit"),
    [
        ("en_US", "1/2 bowl", 0.5, "bowl"),
        ("en_US", "½ bowl", 0.5, "bowl"),
        ("en_US", "half a bowl", 0.5, "bowl"),
        ("en_US", "one and a half cups", 1.5, "cups"),
        ("tr", "yarım ekmek", 0.5, "ekmek"),
        ("tr", "iki kepçe", 2.0, "kepce"),
        ("tr", "bir buçuk kepçe", 1.5, "kepce"),
    ],
)
@requires_pack("tr")
def test_fraction_and_word_quantities_are_parsed(
    locale: str, hint: str, expected_quantity: float, expected_unit: str
):
    quantity, unit = parse_portion(hint, load(locale))
    assert quantity == pytest.approx(expected_quantity)
    assert unit == expected_unit


def test_mixed_numeric_fraction_is_parsed():
    quantity, unit = parse_portion("1 1/2 cups", load("en_US"))
    assert quantity == pytest.approx(1.5)
    assert unit == "cups"


@requires_pack("tr")
def test_known_unit_without_quantity_keeps_unit_but_no_quantity_evidence():
    quantity, unit = parse_portion("kepçe", load("tr"))
    assert quantity is None
    assert unit == "kepce"


@requires_pack("tr")
def test_vision_hint_never_becomes_user_quantity():
    item = PerceivedItem(
        surface_form="simit",
        portion_hint="1 whole",
        count_origin="vision",
    )

    normalized = normalize([item], load("tr"))[0]

    assert (normalized.quantity, normalized.unit, normalized.count_origin) == (
        None,
        None,
        "vision",
    )


@requires_pack("tr")
def test_structured_vision_count_survives_without_hint_parsing():
    item = PerceivedItem(
        surface_form="simit",
        portion_hint="stacked",
        count=2,
        count_origin="vision",
    )

    normalized = normalize([item], load("tr"))[0]

    assert (normalized.quantity, normalized.unit, normalized.count_origin) == (
        2,
        None,
        "vision",
    )
