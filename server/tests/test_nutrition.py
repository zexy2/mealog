"""Nutrition is the one place numbers are produced, so it is the one place that
must be provably right. These are the highest-value tests in the repo."""
import pytest
from conftest import requires_pack

from mealog.domain.models import Nutrients
from mealog.locales.loader import load
from mealog.pipeline.nutrition import scale_per_100g, total


def test_scaling_is_linear_and_exact():
    per100 = Nutrients(kcal=200.0, protein_g=10.0, carb_g=20.0, fat_g=5.0)
    assert scale_per_100g(per100, 250).kcal == pytest.approx(500.0)
    assert scale_per_100g(per100, 0).kcal == 0.0


def test_negative_grams_rejected():
    with pytest.raises(ValueError):
        scale_per_100g(Nutrients(kcal=100), -1)


@requires_pack("tr")
def test_totals_sum_across_items():
    pack = load("tr")
    pairs = [(pack.foods["tr.pilav"], 180.0), (pack.foods["tr.ayran"], 200.0)]
    expected = sum(f.per_100g.kcal * g / 100 for f, g in pairs)
    assert total(pairs).kcal == pytest.approx(expected)
