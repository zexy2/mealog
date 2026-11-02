"""Produce an offline decomposition of the real nine-sample V3 evaluation.

This script deliberately uses the fixture provider.  It does not call Gemini,
change the catalogue, or change any evaluation thresholds.  Its counterfactual
MAPEs use the same denominator as the headline metric: positive-calorie truth,
covered samples, and an exact identity alignment.
"""

# The path bootstrap intentionally precedes project imports when this script is
# run directly from a checkout, matching eval/harness.py.
# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from mealog.adapters.vision_fixture import FixtureVision
from mealog.domain.models import ABSTAIN
from mealog.domain.taxonomy import tag_errors
from mealog.locales.loader import load
from mealog.pipeline import normalize, nutrition, retrieval
from mealog.pipeline.runner import CONFIGS, run

sys.path.insert(0, str(ROOT / "eval"))
from locale_scope import evidence_scope, exclusion_note  # noqa: E402

MANIFEST = ROOT / "eval" / "golden" / "manifest.jsonl"
FIXTURE_DIR = ROOT / "eval" / "fixtures"


def _load_manifest(include_restricted: bool = False) -> list[dict[str, Any]]:
    """Manifest rows in the published scope, for the same reason the harness
    uses it: a diagnostic a clean clone cannot run is not a diagnostic."""
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    locales, excluded = evidence_scope({row["locale"] for row in rows}, include_restricted)
    if excluded:
        print(exclusion_note(locales, excluded), file=sys.stderr)
    return [row for row in rows if row["locale"] in set(locales)]


def _fixture(sample_id: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{sample_id}.json").read_text())


def _truth_grams(entry: dict[str, Any]) -> dict[str, float]:
    return {
        item["food_id"]: float(item.get("grams", 0))
        for item in entry.get("truth", {}).get("items", [])
    }


def _truth_kcal(entry: dict[str, Any], pack: Any) -> float:
    total = 0.0
    for food_id, grams in _truth_grams(entry).items():
        if grams <= 0:
            continue
        food = pack.foods.get(food_id)
        if food is not None:
            total += nutrition.scale_per_100g(food.per_100g, grams).kcal
    return round(total, 1)


def _fmt(value: float) -> str:
    return f"{value:.1f}"


def _fmt_provider(items: list[dict[str, Any]]) -> str:
    if not items:
        return "— (empty)"
    values = []
    for item in items:
        surface = item.get("surface_form", "")
        method = item.get("cooking_method")
        values.append(f"{surface} ({method})" if method else surface)
    return "<br>".join(values)


def _fmt_retrieval(rows: list[dict[str, Any]]) -> str:
    values = []
    for row in rows:
        candidates = row["candidates"]
        if candidates:
            proposed = ", ".join(
                f"{candidate.food_id} [{candidate.score:.3f}]"
                for candidate in candidates
            )
        else:
            proposed = "none"
        values.append(f"{row['query']} → {proposed}")
    return "<br>".join(values) if values else "—"


def _fmt_resolution(items: list[Any], action: str) -> str:
    values = []
    for item in items:
        food_id = item.food_id if item.food_id != ABSTAIN else "ABSTAIN"
        values.append(f"{item.query} → {food_id}")
    result = "<br>".join(values) if values else "—"
    return f"{result}<br>route={action}"


def _fmt_predicted_grams(items: list[Any]) -> str:
    values = []
    for item in items:
        if item.food_id == ABSTAIN:
            continue
        values.append(
            f"{item.food_id}: {_fmt(item.grams)} "
            f"({_fmt(item.grams_p10)}–{_fmt(item.grams_p90)})"
        )
    return "<br>".join(values) if values else "—"


def _fmt_truth(entry: dict[str, Any]) -> str:
    items = entry.get("truth", {}).get("items", [])
    if not items:
        return "— (empty truth)"
    values = [f"{item['food_id']}: {_fmt(float(item.get('grams', 0)))}" for item in items]
    if all(float(item.get("grams", 0)) == 0 for item in items):
        values.append("identity-only sentinel")
    return "<br>".join(values) + f"<br>tier={entry['tier']}"


def _fmt_ape(record: dict[str, Any]) -> str:
    if record["truth_kcal"] <= 0:
        return "— (zero-truth)"
    if not record["covered"]:
        return "— (not covered)"
    return f"{record['ape']:.1f}%"


def _fmt_codes(codes: list[str]) -> str:
    return ", ".join(codes) if codes else "—"


def _evaluate(entry: dict[str, Any], vision: FixtureVision) -> dict[str, Any]:
    sample_id = entry["sample_id"]
    fixture = _fixture(sample_id)
    pack = load(entry["locale"])
    perceived = vision.perceive(sample_id)
    normalized = normalize.normalize(perceived, pack, apply_rules=True)
    retrieval_rows = []
    for item in normalized:
        candidates = retrieval.search(item.query, pack, k=5)
        retrieval_rows.append({"query": item.query, "candidates": candidates})

    meal_log = run(
        vision,
        sample_id,
        entry["locale"],
        config=CONFIGS["V3"],
        idempotency_key=f"decompose-{sample_id}",
    )
    truth_grams = _truth_grams(entry)
    truth_ids = set(truth_grams)
    predicted_grams: dict[str, float] = {}
    for item in meal_log.items:
        if item.food_id != ABSTAIN:
            predicted_grams[item.food_id] = (
                predicted_grams.get(item.food_id, 0.0) + item.grams
            )
    predicted_ids = set(predicted_grams)
    truth_kcal = _truth_kcal(entry, pack)
    covered = meal_log.action != "ask" and not any(
        item.food_id == ABSTAIN for item in meal_log.items
    )
    ape = (
        abs(meal_log.totals.kcal - truth_kcal) / truth_kcal * 100
        if truth_kcal > 0 and covered
        else None
    )
    errors = tag_errors(
        truth_ids=truth_ids,
        pred_ids=predicted_ids,
        truth_grams=truth_grams,
        pred_grams=predicted_grams,
        asked=meal_log.action == "ask",
        identity_applicable=True,
    )
    return {
        "entry": entry,
        "fixture": fixture,
        "meal_log": meal_log,
        "retrieval_rows": retrieval_rows,
        "truth_grams": truth_grams,
        "truth_ids": truth_ids,
        "truth_kcal": truth_kcal,
        "predicted_grams": predicted_grams,
        "predicted_ids": predicted_ids,
        "covered": covered,
        "ape": ape,
        "errors": errors,
    }


def _counterfactuals(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float]:
    aligned = []
    for record in records:
        if (
            record["truth_kcal"] <= 0
            or not record["covered"]
            or record["truth_ids"] != record["predicted_ids"]
        ):
            continue
        pack = load(record["entry"]["locale"])
        identity_perfect_kcal = 0.0
        for food_id, grams in record["predicted_grams"].items():
            identity_perfect_kcal += nutrition.scale_per_100g(
                pack.foods[food_id].per_100g, grams
            ).kcal
        identity_perfect_kcal = round(identity_perfect_kcal, 1)
        aligned.append(
            {
                "sample_id": record["entry"]["sample_id"],
                "identity_perfect_kcal": identity_perfect_kcal,
                "truth_kcal": record["truth_kcal"],
                "identity_ape": abs(identity_perfect_kcal - record["truth_kcal"])
                / record["truth_kcal"]
                * 100,
                "grams_perfect_kcal": record["truth_kcal"],
                "grams_ape": 0.0,
            }
        )
    if not aligned:
        return aligned, float("nan"), float("nan")
    identity_mape = sum(row["identity_ape"] for row in aligned) / len(aligned)
    grams_mape = sum(row["grams_ape"] for row in aligned) / len(aligned)
    return aligned, identity_mape, grams_mape


def _markdown(records: list[dict[str, Any]]) -> str:
    lines = [
        "## Offline decomposition output",
        "",
        "The table below is generated from the committed fixtures and manifest.",
        "The metric denominator is positive-calorie truth, covered V3 rows only.",
        "",
        "| Sample | Provider reported | Retrieval proposed (score) | Resolution | Predicted grams (p10–p90) | Truth grams (tier) | kcal predicted / truth | APE | E-code |",
        "|---|---|---|---|---|---|---:|---:|---|",
    ]
    for record in records:
        entry = record["entry"]
        fixture_items = record["fixture"].get("items", [])
        meal_log = record["meal_log"]
        kcal = f"{meal_log.totals.kcal:.1f} / {record['truth_kcal']:.1f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    entry["sample_id"],
                    _fmt_provider(fixture_items),
                    _fmt_retrieval(record["retrieval_rows"]),
                    _fmt_resolution(meal_log.items, meal_log.action),
                    _fmt_predicted_grams(meal_log.items),
                    _fmt_truth(entry),
                    kcal,
                    _fmt_ape(record),
                    _fmt_codes(record["errors"]),
                ]
            )
            + "|"
        )

    apes = [record["ape"] for record in records if record["ape"] is not None]
    ape_total = sum(apes)
    lines += [
        "",
        "### Scored APE distribution",
        "",
        "Only rows with positive-calorie truth and covered V3 output enter this distribution.",
        "",
        "| Rank | Sample | APE | Share of summed APE |",
        "|---:|---|---:|---:|",
    ]
    scored = sorted(
        (record for record in records if record["ape"] is not None),
        key=lambda record: record["ape"],
        reverse=True,
    )
    for rank, record in enumerate(scored, start=1):
        share = record["ape"] / ape_total * 100 if ape_total else 0.0
        lines.append(
            f"| {rank} | {record['entry']['sample_id']} | "
            f"{record['ape']:.1f}% | {share:.1f}% |"
        )
    if not scored:
        lines.append("| — | — | — | — |")

    aligned, identity_mape, grams_mape = _counterfactuals(records)
    lines += [
        "",
        "### Counterfactuals",
        "",
        (
            "These counterfactuals keep the headline denominator and require exact identity alignment. "
            "They therefore do not invent grams for identity-only truth or assign truth grams to an unrelated food."
        ),
        "",
        "| Counterfactual | MAPE | n | Eligible samples |",
        "|---|---:|---:|---|",
        (
            f"| Perfect identity; observed grams only | {identity_mape:.2f}% | "
            f"{len(aligned)} | {', '.join(row['sample_id'] for row in aligned)} |"
        ),
        (
            f"| Perfect grams; observed identity only | {grams_mape:.2f}% | "
            f"{len(aligned)} | {', '.join(row['sample_id'] for row in aligned)} |"
        ),
        "",
        "No covered positive-calorie row has an identity mismatch. The identity-only rows have no calorie truth, so they cannot produce an identity counterfactual MAPE.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="write Markdown to this path instead of stdout",
    )
    parser.add_argument(
        "--include-restricted",
        action="store_true",
        help="also decompose locales whose catalogue is licence-restricted",
    )
    args = parser.parse_args()
    records = []
    vision = FixtureVision()
    for entry in _load_manifest(args.include_restricted):
        records.append(_evaluate(entry, vision))
    output = _markdown(records)
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
