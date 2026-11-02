"""The README's published numbers are a checked claim, not prose.

These tests use a synthetic summary and a temporary README so they assert the
contract (matching passes, drift fails with the text to write) rather than
today's numbers, which the CI step checks against the real evaluation.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "mealog_readme_claims", SCRIPTS / "check_readme_claims.py"
)
assert SPEC is not None and SPEC.loader is not None
claims = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = claims
SPEC.loader.exec_module(claims)

SCOPE_SPEC = importlib.util.spec_from_file_location(
    "mealog_locale_scope", Path(__file__).resolve().parents[2] / "eval" / "locale_scope.py"
)
assert SCOPE_SPEC is not None and SCOPE_SPEC.loader is not None
locale_scope = importlib.util.module_from_spec(SCOPE_SPEC)
sys.modules[SCOPE_SPEC.name] = locale_scope
SCOPE_SPEC.loader.exec_module(locale_scope)


def summaries() -> tuple[dict, dict]:
    harness = {
        "generator": "eval/harness.py",
        "scope": {"included_locales": ["en_US"], "excluded_locales": ["tr"]},
        "configs": {
            "V3": {
                "rows": 10,
                "committed": 4,
                "asked": 6,
                "abstained": 3,
                "coverage_pct": 40.0,
                "item_f1": 0.25,
                "fp_rate_pct": 50.0,
                "mape_pct": 9.5,
                "calorie_eligible": 3,
                "calorie_scored": 2,
                "worst_cuisine": {"name": "western", "mape_pct": 9.5},
            },
        },
    }
    retrieval = {
        "generator": "eval/retrieval_eval.py",
        "scope": {"included_locales": ["en_US"], "excluded_locales": ["tr"]},
        "variants": 12,
        "positive_inputs": 9,
        "negative_cases": 3,
        "confusion_cases": 0,
        "recall_at_1_hits": 9,
        "recall_at_1_pct": 100.0,
        "recall_at_5_pct": 100.0,
        "mrr": 1.0,
        "accept_at_1_pct": 88.9,
        "absent_negative_cases": 3,
        "false_accepts_blended": 0,
        "false_accepts_baseline": 1,
    }
    return harness, retrieval


def readme_for(measured: dict[str, str]) -> str:
    return (
        "# Mealog\n\n## Evidence snapshot\n\n"
        f"- **{measured['commit.commit']}/{measured['commit.rows']} proposed for review, "
        f"{measured['commit.ask']}/{measured['commit.rows']} ask:** "
        f"{measured['coverage.coverage']}% grounded coverage in the V3 configuration.\n"
        f"- **Item F1 {measured['identity.f1']}; "
        f"FP rate {measured['identity.fp']}%:** an editorial sentence.\n"
        f"- **Calorie MAPE {measured['calorie.mape']}% on "
        f"{measured['calorie.scored']}/{measured['calorie.eligible']} rows:** another.\n\n"
        f"**Retrieval:** {measured['retrieval.variants']} variants,\n"
        f"{measured['retrieval.recall_hit']}/{measured['retrieval.recall_n']} "
        "positive Recall@1, "
        f"MRR {measured['retrieval.mrr']}, "
        f"{measured['retrieval.false_accepts']}/{measured['retrieval.absent']} "
        "absent-food false accepts.\n\n"
        "The restricted catalogue adds "
        f"{measured['excluded.golden']} golden rows and "
        f"{measured['excluded.variants']} retrieval variants.\n\n"
        "## Measured failures\n\n| row |\n| --- |\n"
    )


def write_manifests(directory: Path, golden_rows: int, variants: int) -> None:
    """Two locales, so a count that ignores the scope would be visibly wrong."""
    golden = directory / "manifest.jsonl"
    golden.write_text(
        "\n".join(
            [json.dumps({"sample_id": f"s{i}", "locale": "tr"}) for i in range(golden_rows)]
            + [json.dumps({"sample_id": "shipped", "locale": "en_US"})]
        ) + "\n",
        encoding="utf-8",
    )
    query_variants = directory / "query_variants.jsonl"
    query_variants.write_text(
        "\n".join(
            [json.dumps({"locale": "tr", "query": f"q{i}"}) for i in range(variants)]
            + [json.dumps({"locale": "en_US", "query": "x"})]
        ) + "\n",
        encoding="utf-8",
    )


@pytest.fixture()
def fixture(tmp_path, monkeypatch):
    harness, retrieval = summaries()
    expected = claims.expected_tokens(harness, retrieval, {"golden_rows": 2, "variants": 5})
    write_manifests(tmp_path, golden_rows=2, variants=5)
    monkeypatch.setattr(claims, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(claims, "VARIANTS", tmp_path / "query_variants.jsonl")

    summary_dir = tmp_path / "summaries"
    summary_dir.mkdir()
    (summary_dir / "harness.json").write_text(json.dumps(harness), encoding="utf-8")
    (summary_dir / "retrieval.json").write_text(json.dumps(retrieval), encoding="utf-8")

    def run(text: str) -> tuple[int, str]:
        readme = tmp_path / "README.md"
        readme.write_text(text, encoding="utf-8")
        code = claims.main(["--readme", str(readme), "--from", str(summary_dir)])
        return code, ""

    return {"expected": expected, "run": run}


def test_matching_readme_passes(fixture, capsys):
    code, _ = fixture["run"](readme_for(fixture["expected"]))
    assert code == 0
    assert "matches the evaluation" in capsys.readouterr().out


def test_stale_number_fails_and_prints_the_fix(fixture, capsys):
    text = readme_for(fixture["expected"]).replace("Item F1 0.25", "Item F1 0.15")
    code, _ = fixture["run"](text)
    output = capsys.readouterr().out
    assert code == 1
    assert "Item F1" in output
    assert "README says '0.15', measured '0.25'" in output
    assert "Write this:" in output
    assert "Item F1 0.25" in output


def test_a_removed_claim_is_not_silently_accepted(fixture, capsys):
    text = readme_for(fixture["expected"]).replace(
        "- **Calorie MAPE", "- **Calorie error"
    )
    code, _ = fixture["run"](text)
    output = capsys.readouterr().out
    assert code == 1
    assert "no longer states the calorie claim" in output


def test_a_missing_snapshot_section_is_an_error(fixture):
    with pytest.raises(SystemExit) as raised:
        fixture["run"]("# Mealog\n\nno evidence here\n")
    assert "Evidence snapshot" in str(raised.value)


def test_inconsistent_summary_is_rejected_before_prose():
    harness, retrieval = summaries()
    harness["configs"]["V3"]["committed"] = 9  # 9 + 6 > 10 rows
    problems = claims.summary_problems(harness, retrieval)
    assert any("exceeds" in problem for problem in problems)


def test_manifest_counts_ignore_the_shipped_locale(fixture):
    assert claims.manifest_counts(["tr"]) == {"golden_rows": 2, "variants": 5}


def test_published_scope_excludes_a_restricted_pack(tmp_path):
    pack = tmp_path / "tr"
    pack.mkdir()
    (pack / "pack.yaml").write_text(
        "locale: tr\nlicense: restricted-noncommercial\n", encoding="utf-8"
    )
    inclusive = tmp_path / "en_US"
    inclusive.mkdir()
    (inclusive / "pack.yaml").write_text("locale: en_US\nlicense: public-domain\n", encoding="utf-8")

    included, excluded = locale_scope.evidence_scope(["en_US", "tr"], root=tmp_path)
    assert included == ["en_US"]
    assert excluded == ["tr"]

    with_restricted, still_excluded = locale_scope.evidence_scope(
        ["en_US", "tr"], include_restricted=True, root=tmp_path
    )
    assert with_restricted == ["en_US", "tr"]
    assert still_excluded == []
