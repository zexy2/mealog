"""The eligibility arithmetic in docs/evaluation.md must describe the run.

The document said "two complete, positive-truth rows are calorie-eligible" when
five are, and two of those five are scored. Both statements can be derived from
the manifest and the scorecard, so a reader should not have to trust the prose:
this test recomputes the three counts and fails when the sentence drifts.

The pattern is anchored on the meaning (in-scope rows, partial truth, eligible,
covered), not only on the numbers, so a reworded sentence fails here instead of
going unchecked.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))

import harness
from locale_scope import evidence_scope

DOC = ROOT / "docs" / "evaluation.md"

WORDS = {
    "seventy-two": 72,
    "five": 5,
    "two": 2,
    "three": 3,
    "four": 4,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _number(token: str) -> int:
    token = token.strip()
    return int(token) if token.isdigit() else WORDS[token.lower()]


def _claim() -> tuple[int, int, int, int]:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(
        r"(?P<partial>\w[\w-]*) of the (?P<rows>\d+) in-scope rows are\s+"
        r"partial truth;\s+"
        r"(?P<eligible>\w[\w-]*) complete, positive-truth rows are calorie-eligible and\s+"
        r"(?P<scored>\w[\w-]*)\s+of them are covered",
        text,
    )
    assert match is not None, (
        "the eligibility sentence changed shape; update this test with it, "
        "rather than deleting the check"
    )
    return (
        _number(match.group("partial")),
        int(match.group("rows")),
        _number(match.group("eligible")),
        _number(match.group("scored")),
    )


_ERROR_TAG_SENTENCE = re.compile(
    r"For the current V3 replay on \*\*n=(?P<n>\d+)\*\*,\s*"
    r"the observable tag counts are\s+"
    r"`E3=(?P<E3>\d+)`,\s*"
    r"`E4=(?P<E4>\d+)`,\s*"
    r"`E7=(?P<E7>\d+)`,\s*"
    r"`E12=(?P<E12>\d+)`,\s*and\s+"
    r"`unclassified=(?P<unclassified>\d+)`"
)


def _error_tag_claim() -> dict[str, int]:
    match = _ERROR_TAG_SENTENCE.search(DOC.read_text(encoding="utf-8"))
    assert match is not None, (
        "the V3 error-tag sentence changed shape; update this test with it, "
        "rather than deleting the check"
    )
    return {name: int(match.group(name)) for name in ("n", "E3", "E4", "E7", "E12", "unclassified")}


def test_v3_error_tag_counts_match_a_fresh_run() -> None:
    """The five observable tag counts must be the ones a replay produces.

    The D25 truth correction changed these counts and left the prose stale. The
    sentence is parsed by meaning, not by a bare number search, so a reword that
    silently drops a tag fails here.
    """
    claim = _error_tag_claim()
    locales, _excluded = evidence_scope(harness.manifest_locales())
    results, _errors = harness.evaluate("V3", locales=set(locales))
    counts = harness.error_distribution(results)

    assert claim["n"] == len(results)
    for code in ("E3", "E4", "E7", "E12", "unclassified"):
        assert claim[code] == counts.get(code, 0), (
            f"{code}: docs say {claim[code]}, replay has {counts.get(code, 0)}"
        )


def test_calorie_eligibility_sentence_matches_the_manifest_and_scorecard() -> None:
    locales, _excluded = evidence_scope(harness.manifest_locales())
    rows = harness.select_rows(locales=set(locales))

    partial = sum(1 for row in rows if row.get("unmapped_source_ingredients"))
    eligible = [row for row in rows if harness.calorie_truth_complete(row)]

    results, _errors = harness.evaluate("V3", locales=set(locales))
    eligible_ids = {row["sample_id"] for row in eligible}
    scored = sum(
        1 for result in results if result.sample_id in eligible_ids and result.covered
    )

    assert _claim() == (partial, len(rows), len(eligible), scored)
