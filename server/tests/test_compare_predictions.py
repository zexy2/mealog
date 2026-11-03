"""The prediction comparison must say what it compared and on which rows.

`eval/compare_predictions.py` reads the JSONL artifacts `harness.py
--predictions` writes and classifies every truth item. These tests build small
hand-written artifacts under `tmp_path`, so every count in the report can be
checked against an expected number rather than against another run. They also
pin the failure modes that would turn a broken artifact into a quietly smaller
denominator: a malformed line, a missing key, an empty file, and two artifacts
that did not score the same rows.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mealog_compare_predictions", ROOT / "eval" / "compare_predictions.py"
)
assert SPEC is not None and SPEC.loader is not None
compare_predictions = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compare_predictions
SPEC.loader.exec_module(compare_predictions)


def make_row(
    sample_id: str,
    *,
    truth: list[str],
    pred: list[str],
    candidates: list[str] | None = None,
    cuisine: str = "western",
    tier: str = "tier_1",
    prompt: str = "p4",
    error: str | None = None,
) -> dict:
    """One artifact row in the schema `harness._perceived_detail` writes."""
    candidates = pred if candidates is None else candidates
    perceived = []
    if candidates and error is None:
        perceived.append(
            {
                "query": "synthetic surface",
                "food_id": pred[0] if pred else candidates[0],
                "abstained": not pred,
                "confidence": 0.8,
                "candidates": [
                    {"food_id": food_id, "score": 0.9}
                    for food_id in candidates
                ],
            }
        )
    return {
        "config": "V3",
        "sample_id": sample_id,
        "locale": "en_US",
        "cuisine": cuisine,
        "tier": tier,
        "prompt_variant": prompt,
        "perceived": [] if error is not None else perceived,
        "truth_ids": truth,
        "pred_ids": [] if error is not None else pred,
        "row_error": error,
    }


def write_artifact(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def run(*args: str, capsys) -> tuple[int, str, str]:
    code = compare_predictions.main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_single_artifact_counts_classes_and_denominator(tmp_path, capsys):
    artifact = write_artifact(
        tmp_path / "baseline.jsonl",
        [
            make_row(
                "row_1",
                truth=["us.rice", "us.egg"],
                pred=["us.rice"],
                candidates=["us.rice", "us.egg"],
                cuisine="western",
                tier="tier_1",
            ),
            make_row(
                "row_2",
                truth=["jp.miso"],
                pred=[],
                candidates=["jp.tofu"],
                cuisine="japanese",
                tier="tier_2",
            ),
            make_row(
                "row_3",
                truth=["tr.bread", "tr.cheese"],
                pred=["tr.bread", "tr.cheese"],
                cuisine="turkish",
                tier="tier_1",
            ),
            make_row(
                "row_4",
                truth=["us.rice"],
                pred=[],
                cuisine="western",
                tier="tier_2",
                error="provider failed for row_4",
            ),
        ],
    )

    code, out, err = run("--baseline", str(artifact), capsys=capsys)

    assert code == 0, err
    report = compare_predictions.build_report(
        artifact, compare_predictions.load_artifact(artifact)
    )
    summary = report["baseline"]
    assert report["candidate"] is None
    assert report["comparison"] is None
    assert summary["rows"] == 4
    assert summary["failed_rows"] == 1
    assert summary["scored_rows"] == 3
    assert summary["rows_with_truth"] == 4
    assert summary["truth_items"] == 5
    assert summary["failed_truth_items"] == 1
    assert summary["classes"] == {"resolved": 3, "perceived": 1, "absent": 1}

    by_cuisine = summary["by_cuisine"]
    assert by_cuisine["western"] == {
        "resolved": 1,
        "perceived": 1,
        "absent": 0,
        "truth_items": 2,
    }
    assert by_cuisine["japanese"]["absent"] == 1
    assert by_cuisine["turkish"]["resolved"] == 2
    assert summary["by_tier"]["tier_2"]["truth_items"] == 1

    assert summary["absent_foods"] == [{"food_id": "jp.miso", "count": 1}]

    assert compare_predictions.CAVEAT in out
    assert "top three" in out and "top five" in out
    assert "| resolved | 3 | 60.0% |" in out
    assert "| perceived | 1 | 20.0% |" in out
    assert "| absent | 1 | 20.0% |" in out
    assert "`row_4` line 4" in out
    assert "| japanese | 0 | 0 | 1 | 1 |" in out


def test_two_artifacts_report_flows_and_net_on_the_join_key(tmp_path, capsys):
    baseline = write_artifact(
        tmp_path / "p4.jsonl",
        [
            make_row(
                "row_1",
                truth=["f.one", "f.two", "f.three"],
                pred=["f.one"],
                candidates=["f.one", "f.two"],
            ),
            make_row("row_2", truth=["f.one"], pred=[], candidates=[]),
        ],
    )
    candidate = write_artifact(
        tmp_path / "p5.jsonl",
        [
            make_row(
                "row_1",
                truth=["f.one", "f.two", "f.three"],
                pred=["f.two"],
                candidates=["f.two", "f.three"],
            ),
            make_row("row_2", truth=["f.one"], pred=["f.one"]),
        ],
    )

    code, out, err = run(
        "--baseline", str(baseline), "--candidate", str(candidate), capsys=capsys
    )
    assert code == 0, err

    report = compare_predictions.build_report(
        baseline,
        compare_predictions.load_artifact(baseline),
        candidate,
        compare_predictions.load_artifact(candidate),
    )
    comparison = report["comparison"]
    assert comparison["flows"] == {
        "resolved": {"resolved": 0, "perceived": 0, "absent": 1},
        "perceived": {"resolved": 1, "perceived": 0, "absent": 0},
        "absent": {"resolved": 1, "perceived": 1, "absent": 0},
    }
    assert comparison["baseline_totals"] == {
        "resolved": 1,
        "perceived": 1,
        "absent": 2,
    }
    assert comparison["candidate_totals"] == {
        "resolved": 2,
        "perceived": 1,
        "absent": 1,
    }
    assert comparison["net"] == {"resolved": 1, "perceived": 0, "absent": -1}
    assert report["baseline"]["classes"] == {
        "resolved": 1,
        "perceived": 1,
        "absent": 2,
    }

    # The same food id appears in two rows. The join key is
    # (sample_id, food_id), so row_2's absent → resolved flow survives next to
    # row_1's resolved → absent instead of collapsing onto one `f.one` entry.
    assert sum(
        row[outcome]
        for row in comparison["flows"].values()
        for outcome in compare_predictions.CLASSES
    ) == 4

    assert "| resolved | 0 | 0 | 1 | 1 |" in out
    assert "| perceived | 1 | 0 | 0 | 1 |" in out
    assert "| absent | 1 | 1 | 0 | 2 |" in out
    assert "| resolved | 1 | 2 | +1 |" in out
    assert "| perceived | 1 | 1 | 0 |" in out
    assert "| absent | 2 | 1 | -1 |" in out


def test_denominator_guard_limits_flows_to_the_intersection(tmp_path, capsys):
    baseline = write_artifact(
        tmp_path / "baseline.jsonl",
        [
            make_row("row_1", truth=["a"], pred=["a"]),
            make_row("row_2", truth=["a"], pred=["a"]),
            make_row("row_3", truth=["a"], pred=["a"]),
        ],
    )
    candidate = write_artifact(
        tmp_path / "candidate.jsonl",
        [
            make_row("row_1", truth=["a"], pred=["a"]),
            make_row("row_2", truth=["a"], pred=["a"]),
            make_row("row_3", truth=["a"], pred=[], error="provider timeout"),
        ],
    )

    code, out, err = run(
        "--baseline", str(baseline), "--candidate", str(candidate), capsys=capsys
    )
    assert code == 0, err

    report = compare_predictions.build_report(
        baseline,
        compare_predictions.load_artifact(baseline),
        candidate,
        compare_predictions.load_artifact(candidate),
    )
    guard = report["comparison"]["guard"]
    assert guard["baseline_scored_rows"] == 3
    assert guard["candidate_scored_rows"] == 2
    assert guard["intersection_rows"] == 2
    assert guard["dropped_baseline_rows"] == ["row_3"]
    assert guard["dropped_candidate_rows"] == []
    assert guard["candidate_failed"] == ["row_3"]
    assert guard["dropped_baseline_truth_items"] == 1
    assert guard["unpaired_baseline_truth_items"] == 0

    # The flow table is the 2-row intersection; the per-artifact totals keep
    # their own denominators. They must not be presented as the same number.
    assert report["comparison"]["baseline_totals"]["resolved"] == 2
    assert report["baseline"]["classes"]["resolved"] == 3
    assert report["candidate"]["classes"]["resolved"] == 2

    assert "intersection-only" in out
    assert "not a full-run comparison" in out
    assert "`row_3`" in out
    assert "Rows dropped from the baseline side: `row_3` (1 truth items)." in out
    assert "different denominators" in out
    assert "| **Candidate total** | **2** | **0** | **0** | **2** |" in out


def test_prompt_variants_are_labelled_or_called_a_self_comparison(tmp_path, capsys):
    baseline = write_artifact(
        tmp_path / "p4.jsonl", [make_row("row_1", truth=["a"], pred=["a"])]
    )
    other = write_artifact(
        tmp_path / "p5.jsonl",
        [make_row("row_1", truth=["a"], pred=["a"], prompt="p5")],
    )
    same = write_artifact(
        tmp_path / "p4-again.jsonl",
        [make_row("row_1", truth=["a"], pred=["a"])],
    )

    code, out, _ = run(
        "--baseline", str(baseline), "--candidate", str(other), capsys=capsys
    )
    assert code == 0
    assert "Prompts differ: baseline p4 vs candidate p5." in out
    assert "self-comparison" not in out

    code, out, _ = run(
        "--baseline", str(baseline), "--candidate", str(same), capsys=capsys
    )
    assert code == 0
    assert "self-comparison" in out
    assert "run-to-run variation" in out


def test_a_malformed_line_names_its_line_number(tmp_path, capsys):
    artifact = tmp_path / "broken.jsonl"
    good = make_row("row_1", truth=["a"], pred=["a"])
    artifact.write_text(json.dumps(good) + "\n{not json\n", encoding="utf-8")

    code, out, err = run("--baseline", str(artifact), capsys=capsys)

    assert code == 2
    assert out == ""
    assert f"{artifact}:2:" in err
    assert "malformed JSON" in err


def test_a_missing_key_names_its_line_number(tmp_path, capsys):
    artifact = tmp_path / "missing.jsonl"
    good = make_row("row_1", truth=["a"], pred=["a"])
    broken = make_row("row_2", truth=["a"], pred=["a"])
    del broken["truth_ids"]
    artifact.write_text(
        json.dumps(good) + "\n" + json.dumps(broken) + "\n", encoding="utf-8"
    )

    code, out, err = run("--baseline", str(artifact), capsys=capsys)

    assert code == 2
    assert out == ""
    assert f"{artifact}:2:" in err
    assert "truth_ids" in err


def test_an_empty_artifact_is_not_a_zero_result(tmp_path, capsys):
    artifact = tmp_path / "empty.jsonl"
    artifact.write_text("", encoding="utf-8")

    code, out, err = run("--baseline", str(artifact), capsys=capsys)

    assert code == 2
    assert out == ""
    assert "no rows" in err
    assert "not a zero result" in err


def test_a_repeated_sample_id_is_rejected(tmp_path, capsys):
    artifact = write_artifact(
        tmp_path / "duplicate.jsonl",
        [
            make_row("row_1", truth=["a"], pred=["a"]),
            make_row("row_1", truth=["b"], pred=["b"]),
        ],
    )

    code, out, err = run("--baseline", str(artifact), capsys=capsys)

    assert code == 2
    assert out == ""
    assert f"{artifact}:2:" in err
    assert "duplicate sample_id 'row_1'" in err


def test_json_is_stable_and_carries_the_markdown_numbers(tmp_path, capsys):
    baseline = write_artifact(
        tmp_path / "baseline.jsonl",
        [
            make_row("row_1", truth=["a", "b"], pred=["a"], candidates=["a", "b"]),
            make_row("row_2", truth=["c"], pred=[], candidates=[]),
        ],
    )
    candidate = write_artifact(
        tmp_path / "candidate.jsonl",
        [
            make_row("row_1", truth=["a", "b"], pred=["a", "b"]),
            make_row("row_2", truth=["c"], pred=["c"], candidates=["c"]),
        ],
    )

    code, first, err = run(
        "--baseline", str(baseline), "--candidate", str(candidate), "--json",
        capsys=capsys,
    )
    assert code == 0, err
    payload = json.loads(first)
    assert payload["baseline"]["classes"] == {
        "resolved": 1,
        "perceived": 1,
        "absent": 1,
    }
    assert payload["candidate"]["classes"] == {
        "resolved": 3,
        "perceived": 0,
        "absent": 0,
    }
    assert payload["comparison"]["flows"] == {
        "resolved": {"resolved": 1, "perceived": 0, "absent": 0},
        "perceived": {"resolved": 1, "perceived": 0, "absent": 0},
        "absent": {"resolved": 1, "perceived": 0, "absent": 0},
    }

    code, second, _ = run(
        "--baseline", str(baseline), "--candidate", str(candidate), "--json",
        capsys=capsys,
    )
    assert code == 0
    assert first == second
    assert json.dumps(json.loads(first), indent=2) == second.strip()

    code, markdown, _ = run(
        "--baseline", str(baseline), "--candidate", str(candidate), capsys=capsys
    )
    assert code == 0
    for name, count in payload["baseline"]["classes"].items():
        assert f"| {name} | {count} |" in markdown
    for name, count in payload["comparison"]["net"].items():
        net_cell = f"{count:+d}" if count else "0"
        assert (
            f"| {name} | {payload['comparison']['baseline_totals'][name]} | "
            f"{payload['comparison']['candidate_totals'][name]} | {net_cell} |"
        ) in markdown
