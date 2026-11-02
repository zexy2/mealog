"""Retrieval tests.

The regression cases pin the three defects documented on issue #17, so they
cannot silently come back. The rest pin properties that must survive any future
swap of the matching implementation — including the embedding model that
replaces this.
"""
from copy import deepcopy

import pytest
from conftest import requires_pack

from mealog.domain.models import CanonicalFood, Nutrients
from mealog.locales.loader import load
from mealog.pipeline.normalize import fold
from mealog.pipeline.resolve import MIN_ACCEPT_SCORE, resolve
from mealog.pipeline.retrieval import CONFUSION_SCORE, search

NEW_EN_US_FOOD_IDS = frozenset({
    "us.potatoes_baked", "us.broccoli_cooked", "us.strawberries_raw",
    "us.blueberries_raw", "us.pineapple_raw", "us.grapes_raw",
    "us.sweet_potato_baked", "us.watermelon_raw", "us.raspberries_raw",
    "us.blackberries_raw", "us.chicken_breaded_fried", "us.squash_summer_cooked",
    "us.kale_cooked", "us.pork_roasted", "us.tofu_firm", "us.corn_cooked",
    "us.beef_cooked", "us.tomatoes_cooked", "us.mushrooms_cooked", "us.coleslaw",
    "us.chickpeas_cooked", "us.salmon_cooked", "us.long_beans_cooked",
    "us.zucchini_cooked", "us.yellow_squash_cooked", "us.lasagna_meat",
    "us.leaf_lettuce_raw", "us.arugula_raw", "us.spinach_raw",
    "us.brussels_sprouts_cooked",
})


def top(query: str, locale: str) -> str | None:
    pack = load(locale)
    cands = search(fold(query, pack), pack)
    return cands[0].food_id if cands else None


# --- defect 1: inflected forms missed the catalogue entirely -----------------

@requires_pack("tr")
@pytest.mark.parametrize("query", ["pilav", "pilavi", "pirinc pilavi", "sade pirinc pilavi"])
def test_inflected_forms_reach_the_same_canonical_food(query):
    assert top(query, "tr") == "tr.pilav"


# --- defect 2: negative_alias was loaded but never read ----------------------

@requires_pack("tr")
def test_known_confusion_is_surfaced_and_still_asked_about():
    """The trap must be recognised, not merely missed.

    Returning nothing would also abstain, but for the wrong reason. We want the
    confusable food on the table so the user gets a specific question.
    """
    pack = load("tr")
    query = fold("baked beans", pack)
    cands = search(query, pack)

    assert "tr.kuru_fasulye" in [c.food_id for c in cands], "confusable food not surfaced"
    assert resolve(query, cands, allow_abstain=True).abstained, "accepted instead of asking"


@requires_pack("tr")
@pytest.mark.parametrize("query", ["some baked beans", "baked beans and rice"])
def test_known_confusion_matches_a_token_bounded_subphrase(query):
    pack = load("tr")
    cands = search(fold(query, pack), pack)

    confusion = next(c for c in cands if c.food_id == "tr.kuru_fasulye")
    assert confusion.score == CONFUSION_SCORE
    assert resolve(query, cands, allow_abstain=True).abstained


@requires_pack("tr")
def test_known_confusion_does_not_match_inside_a_token():
    pack = load("tr")

    cands = search(fold("baked beanstalk", pack), pack)

    assert "tr.kuru_fasulye" not in [c.food_id for c in cands]


@requires_pack("tr")
def test_search_builds_index_from_passed_pack():
    pack = deepcopy(load("tr"))
    pack.foods = {
        "tr.injected": CanonicalFood(
            food_id="tr.injected", name="Injected dish",
            per_100g=Nutrients(kcal=1), default_serving_g=1,
            default_serving_name="1 serving", source="test", locale=pack.locale,
        ),
    }
    pack.aliases = {"tr.injected": ["injected"]}
    pack.negative_aliases = {}

    cands = search(fold("injected", pack), pack)

    assert [c.food_id for c in cands[:1]] == ["tr.injected"]


@requires_pack("tr")
def test_changed_pack_content_invalidates_cached_index():
    pack = deepcopy(load("tr"))
    pack.aliases["tr.pilav"] = [*pack.aliases.get("tr.pilav", []), "changed alias"]

    cands = search(fold("changed alias", pack), pack)

    assert [c.food_id for c in cands[:1]] == ["tr.pilav"]


def test_confusion_score_stays_below_the_accept_threshold():
    """Encoded as a test rather than an import so both constants stay readable
    on their own; this is the coupling between them."""
    assert CONFUSION_SCORE < MIN_ACCEPT_SCORE


# --- properties any implementation must keep --------------------------------

@requires_pack("tr")
def test_absent_food_is_never_accepted():
    """Fuzzy matching buys recall by making everything look slightly similar.
    That must not turn an honest abstention into a confident wrong answer."""
    for locale, query in [("tr", "pizza margherita"), ("en_US", "pad thai"),
                          ("ja_JP", "lahmacun"), ("en_US", "asdfgh")]:
        pack = load(locale)
        q = fold(query, pack)
        assert resolve(q, search(q, pack), allow_abstain=True).abstained, \
            f"{locale}: '{query}' should not be accepted"


def test_same_surface_form_resolves_per_locale():
    """'rice' is a different canonical food in different markets. Locale is the
    only thing that disambiguates it, and it comes from data, not code."""
    assert top("rice", "en_US") == "us.rice_white_cooked"
    assert top("rice", "ja_JP") == "jp.rice_steamed"


def test_empty_query_returns_no_candidates():
    assert search("", load("en_US")) == []


@requires_pack("tr")
def test_scores_are_ordered_and_bounded():
    pack = load("tr")
    cands = search(fold("mercimek", pack), pack)
    assert cands
    assert all(0.0 <= c.score <= 1.0 for c in cands)
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)


def test_all_thirty_new_en_us_entries_have_an_unambiguous_positive_alias():
    pack = load("en_US")
    assert len(NEW_EN_US_FOOD_IDS) == 30
    assert NEW_EN_US_FOOD_IDS <= pack.foods.keys()

    negative_forms = {
        fold(alias, pack)
        for aliases in pack.negative_aliases.values()
        for alias in aliases
    }
    covered = set()
    for food_id in NEW_EN_US_FOOD_IDS:
        aliases = [alias for alias in pack.aliases[food_id]
                   if fold(alias, pack) not in negative_forms]
        assert aliases, f"{food_id} has no unambiguous positive alias"
        for alias in aliases:
            query = fold(alias, pack)
            candidates = search(query, pack)
            result = resolve(query, candidates, allow_abstain=True)
            assert result.food_id == food_id, (food_id, alias, candidates, result)
            covered.add(food_id)

    assert covered == NEW_EN_US_FOOD_IDS


def test_new_en_us_negative_aliases_abstain():
    pack = load("en_US")
    for food_id in NEW_EN_US_FOOD_IDS:
        for alias in pack.negative_aliases.get(food_id, []):
            query = fold(alias, pack)
            result = resolve(query, search(query, pack), allow_abstain=True)
            assert result.abstained, (food_id, alias, result)


@pytest.mark.parametrize(
    ("query", "confusable_food_ids"),
    [
        ("squash", {"us.squash_summer_cooked", "us.yellow_squash_cooked"}),
        ("green salad", {"us.leaf_lettuce_raw"}),
    ],
)
def test_new_en_us_ambiguities_surface_neighbours_and_abstain(query, confusable_food_ids):
    pack = load("en_US")
    folded = fold(query, pack)
    candidates = search(folded, pack)

    assert confusable_food_ids <= {candidate.food_id for candidate in candidates}
    assert resolve(folded, candidates, allow_abstain=True).abstained
