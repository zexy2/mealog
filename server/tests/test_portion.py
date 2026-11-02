"""Mass estimates must expose density and evidence uncertainty."""
from copy import deepcopy

import pytest
from conftest import requires_pack
from pydantic import ValidationError

from mealog.domain.models import CanonicalFood, Nutrients, PerceivedItem
from mealog.locales.loader import load
from mealog.pipeline.portion import (
    DEFAULT_SPREAD,
    UNKNOWN_DENSITY_SPREAD,
    estimate,
)
from mealog.pipeline.ports import VisionInput

CATALOGUE_SERVING_ROWS = (
    ("tr.lahmacun", 2.0, "adet", 280),
    ("tr.yumurta_tavuk", 1.0, "adet", 50),
    ("tr.elma", 1.0, "adet", 150),
    ("tr.yaprak_sarma", 3.0, "adet", 75),
    ("tr.antep_baklavasi", 1.0, "dilim", 80),
    ("tr.pilav", 1.0, "porsiyon", 180),
    ("tr.ceviz", 1.0, "porsiyon", 30),
    ("tr.turk_kahvesi", 1.0, "fincan", 7),
    ("tr.simit", 2.0, "adet", 200),
    ("tr.ekmek_beyaz", 3.0, "dilim", 75),
    ("tr.mercimek_corbasi", 1.0, "kase", 250),
)


@requires_pack("tr")
@pytest.mark.parametrize("food_id, quantity, unit, expected_grams", CATALOGUE_SERVING_ROWS)
def test_catalogue_serving_wins_for_matching_unit(
    food_id: str,
    quantity: float,
    unit: str,
    expected_grams: int,
):
    pack = load("tr")
    result = estimate(pack.foods[food_id], quantity, unit, pack)

    assert result.grams == pytest.approx(expected_grams, abs=0.01)
    assert result.source == "explicit_unit"
    assert f"per_unit_g={expected_grams / quantity:g}" in result.provenance
    assert "source=catalogue_serving" in result.provenance


@requires_pack("tr")
def test_catalogue_serving_uses_one_unit_when_quantity_is_missing():
    pack = load("tr")
    result = estimate(pack.foods["tr.yaprak_sarma"], None, "adet", pack)

    assert tuple(result) == pytest.approx((25.0, 16.2, 36.2), abs=0.01)
    assert result.source == "assumed_unit"
    assert "per_unit_g=25" in result.provenance


@requires_pack("tr")
def test_catalogue_unit_matching_ignores_accents_case_spaces_and_underscores():
    pack = load("tr")
    tea = estimate(pack.foods["tr.tereyagi"], 1, "cay_kasigi", pack)
    lahmacun = estimate(pack.foods["tr.lahmacun"], 1, "ADET", pack)

    assert (tea.grams, tea.source) == (10.0, "explicit_unit")
    assert "source=catalogue_serving" in tea.provenance
    assert (lahmacun.grams, lahmacun.source) == (140.0, "explicit_unit")
    assert "source=catalogue_serving" in lahmacun.provenance


@requires_pack("tr")
def test_generic_unit_table_remains_fallback_when_catalogue_names_another_unit():
    food = CanonicalFood(
        food_id="test.food",
        name="Test food",
        per_100g=Nutrients(kcal=100),
        default_serving_g=80,
        default_serving_name="1 serving",
        source="test",
        locale="tr",
    )
    pack = deepcopy(load("tr"))
    pack.units = {"adet": {"g": 25}}

    result = estimate(food, 2.0, "adet", pack)

    assert tuple(result) == pytest.approx((50.0, 40.0, 62.5), abs=0.01)
    assert result.source == "explicit_unit"
    assert result.provenance == "unit=adet; quantity=2.0; conversion_g=25"


@requires_pack("tr")
def test_vision_count_is_not_explicit_unit_evidence():
    pack = load("tr")
    result = estimate(pack.foods["tr.simit"], 2.0, None, pack, "vision")

    assert tuple(result) == pytest.approx((200.0, 150.0, 270.0), abs=0.01)
    assert result.source == "vision_count"
    assert "count_origin=vision" in result.provenance


@requires_pack("tr")
def test_non_water_volume_uses_unknown_density_interval():
    pack = load("tr")
    food = pack.foods["tr.kuru_fasulye"]

    grams, p10, p90 = estimate(food, 2.0, "kepce", pack)

    assert grams == pytest.approx(300.0, abs=0.01)
    assert p10 == pytest.approx(135.0, abs=0.01)
    assert p90 == pytest.approx(525.0, abs=0.01)


def test_missing_density_widens_volume_interval():
    pack = deepcopy(load("en_US"))
    pack.units["unclassified_volume"] = {"ml": 200}
    food = pack.foods["us.chicken_breast_grilled"]

    grams, p10, p90 = estimate(food, 1.0, "unclassified_volume", pack)

    assert grams == pytest.approx(200.0, abs=0.1)
    assert (p10, p90) == pytest.approx(
        (grams * UNKNOWN_DENSITY_SPREAD[0], grams * UNKNOWN_DENSITY_SPREAD[1]),
        abs=0.1,
    )
    assert p10 < grams * DEFAULT_SPREAD[0]
    assert p90 > grams * DEFAULT_SPREAD[1]


@requires_pack("tr")
def test_missing_quantity_does_not_get_explicit_unit_spread():
    pack = load("tr")
    food = pack.foods["tr.kuru_fasulye"]

    grams, p10, p90 = estimate(food, None, "kepce", pack)

    assert grams == pytest.approx(150.0, abs=0.1)
    assert (p10, p90) == pytest.approx(
        (grams * UNKNOWN_DENSITY_SPREAD[0], grams * UNKNOWN_DENSITY_SPREAD[1]),
        abs=0.1,
    )
    assert p10 < grams * 0.8
    assert p90 > grams * 1.25


def test_known_food_density_narrows_volume_interval():
    pack = load("en_US")
    food = pack.foods["us.rice_white_cooked"]

    grams, p10, p90 = estimate(food, 1.0, "cup", pack)

    assert grams == pytest.approx(158.0, abs=0.1)
    assert (p10, p90) == pytest.approx((126.4, 197.5), abs=0.1)
    assert p10 > grams * UNKNOWN_DENSITY_SPREAD[0]
    assert p90 < grams * UNKNOWN_DENSITY_SPREAD[1]
    assert food.density_source


@pytest.mark.parametrize("density_source", [None, ""])
def test_density_requires_a_source(density_source):
    with pytest.raises(ValidationError):
        CanonicalFood(
            food_id="test.food",
            name="Test food",
            per_100g=Nutrients(kcal=1),
            default_serving_g=100,
            default_serving_name="1 serving",
            source="test",
            locale="test",
            density_g_per_ml=1.0,
            density_source=density_source,
        )


@requires_pack("tr")
@pytest.mark.parametrize("locale", ["en_US", "tr", "ja_JP"])
def test_volume_units_never_carry_density(locale: str):
    pack = load(locale)
    volume_units = [conversion for conversion in pack.units.values() if "ml" in conversion]

    assert volume_units
    for conversion in volume_units:
        assert "density_g_per_ml" not in conversion
        assert "density_source" not in conversion


def test_packaged_label_serving_overrides_package_size_hint():
    pack = load("en_US")
    food = pack.foods["us.yogurt_greek_plain"]

    estimate_result = estimate(food, 32.0, "oz", pack)

    grams, p10, p90 = estimate_result
    assert (grams, p10, p90) == pytest.approx((170.0, 153.0, 187.0), abs=0.1)
    assert estimate_result.source == "label_serving"
    assert "Open Food Facts" in estimate_result.provenance
    assert "serving_size" in estimate_result.provenance


def test_single_serve_packaged_food_uses_sourced_net_weight():
    food = CanonicalFood(
        food_id="test.packaged_single",
        name="Packaged single serve",
        per_100g=Nutrients(kcal=100),
        default_serving_g=999,
        default_serving_name="catalogue prior",
        source="test",
        locale="en_US",
        packaged=True,
        net_weight_g=250,
        net_weight_source="dataset=product-record; field=net_weight",
    )
    pack = load("en_US")

    result = estimate(food, None, None, pack)

    assert tuple(result) == pytest.approx((250.0, 225.0, 275.0), abs=0.1)
    assert result.source == "net_weight"
    assert result.provenance == "dataset=product-record; field=net_weight"


def test_packaged_without_label_serving_marks_catalogue_fallback():
    food = CanonicalFood(
        food_id="test.packaged_missing",
        name="Packaged without serving",
        per_100g=Nutrients(kcal=100),
        default_serving_g=250,
        default_serving_name="catalogue prior",
        source="test",
        locale="en_US",
        packaged=True,
    )
    pack = load("en_US")

    result = estimate(food, None, None, pack)

    assert tuple(result) == pytest.approx((250.0, 162.5, 362.5), abs=0.1)
    assert result.source == "packaged_fallback"
    assert "fallback=catalogue.default_serving_g" in result.provenance


def test_packaged_serving_requires_provenance():
    with pytest.raises(ValidationError):
        CanonicalFood(
            food_id="test.unprovenanced_packaged",
            name="Unprovenanced packaged food",
            per_100g=Nutrients(kcal=100),
            default_serving_g=100,
            default_serving_name="catalogue prior",
            source="test",
            locale="en_US",
            packaged=True,
            serving_size_g=170,
        )


def test_portion_provenance_reaches_resolved_item_without_moving_cooked_path():
    from mealog.adapters.vision_fixture import FixtureVision
    from mealog.pipeline.runner import CONFIGS, run

    vision = FixtureVision()
    packaged = run(
        vision, "pkg_0001", "en_US", CONFIGS["V3"], "test-packaged-serving"
    )
    cooked = run(
        vision, "n5k_0002", "en_US", CONFIGS["V3"], "test-cooked-serving"
    )

    packaged_item = packaged.items[0]
    cooked_item = cooked.items[0]
    assert (packaged_item.grams, packaged_item.grams_p10, packaged_item.grams_p90) == (
        170.0,
        153.0,
        187.0,
    )
    assert packaged_item.portion_source == "label_serving"
    assert "Open Food Facts" in packaged_item.portion_provenance
    assert (cooked_item.grams, cooked_item.grams_p10, cooked_item.grams_p90) == (
        100.0,
        65.0,
        145.0,
    )
    assert cooked_item.portion_source == "catalogue_default"


class StubVision:
    name = "handwritten-stub"

    def __init__(self, items: list[PerceivedItem]):
        self.items = items

    def perceive(self, _input: VisionInput) -> list[PerceivedItem]:
        return self.items


@requires_pack("tr")
def test_runner_reconciles_repeated_unknown_count_observations():
    from mealog.pipeline.runner import CONFIGS, run

    result = run(
        StubVision([
            PerceivedItem(surface_form="ayran", confidence=1),
            PerceivedItem(surface_form="ayran", confidence=1),
            PerceivedItem(surface_form="ayran", confidence=1),
            PerceivedItem(surface_form="ayran", confidence=1),
        ]),
        VisionInput(text="one glass of ayran"),
        "tr",
        CONFIGS["V3"],
        "runner-duplicate-ayran",
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert (item.food_id, item.quantity, item.grams, item.grams_p10, item.grams_p90) == (
        "tr.ayran", None, 200.0, 130.0, 290.0
    )
    assert item.portion_source == "catalogue_default"


@requires_pack("tr")
def test_runner_keeps_unobserved_simit_count_null_and_unscaled():
    from mealog.pipeline.runner import CONFIGS, run

    result = run(
        StubVision([
            PerceivedItem(surface_form="simit", portion_hint="several", confidence=1),
        ]),
        VisionInput(text="two stacked simits"),
        "tr",
        CONFIGS["V3"],
        "runner-two-simit-unknown-count",
    )

    item = result.items[0]
    assert (item.food_id, item.quantity, item.grams, item.grams_p10, item.grams_p90) == (
        "tr.simit", None, 100.0, 65.0, 145.0
    )
    assert item.portion_source == "catalogue_default"
    assert item.portion_provenance == "catalogue.default_serving_g=100"


@requires_pack("tr")
def test_runner_sums_known_counts_for_duplicate_observations():
    from mealog.pipeline.runner import CONFIGS, run

    result = run(
        StubVision([
            PerceivedItem(surface_form="simit", portion_hint="1 adet", confidence=1),
            PerceivedItem(surface_form="simit", portion_hint="1 adet", confidence=1),
        ]),
        VisionInput(text="two simits"),
        "tr",
        CONFIGS["V3"],
        "runner-known-count-reconciliation",
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert (item.food_id, item.quantity, item.unit, item.grams) == (
        "tr.simit", 2.0, "adet", 200.0
    )


def test_runner_portion_branch_is_stable_across_repeated_submissions():
    from mealog.pipeline.runner import CONFIGS, run

    results = [
        run(
            StubVision([
                PerceivedItem(surface_form="chicken breast", confidence=1),
            ]),
            VisionInput(text="chicken breast"),
            "en_US",
            CONFIGS["V3"],
            f"runner-repeat-{index}",
        )
        for index in range(1, 4)
    ]

    results[1] = run(
        StubVision([
            PerceivedItem(surface_form="chicken breast", portion_hint="cup", confidence=1),
        ]),
        VisionInput(text="chicken breast"),
        "en_US",
        CONFIGS["V3"],
        "runner-repeat-with-uncounted-unit",
    )

    assert [
        (result.items[0].portion_source,
         result.items[0].grams_p10,
         result.items[0].grams_p90)
        for result in results
    ] == [
        ("catalogue_default", 78.0, 174.0),
        ("catalogue_default", 78.0, 174.0),
        ("catalogue_default", 78.0, 174.0),
    ]


@requires_pack("tr")
def test_runner_does_not_reconcile_different_foods():
    from mealog.pipeline.runner import CONFIGS, run

    result = run(
        StubVision([
            PerceivedItem(surface_form="simit", confidence=1),
            PerceivedItem(surface_form="ayran", confidence=1),
        ]),
        VisionInput(text="simit and ayran"),
        "tr",
        CONFIGS["V3"],
        "runner-different-foods",
    )

    assert [item.food_id for item in result.items] == ["tr.simit", "tr.ayran"]
