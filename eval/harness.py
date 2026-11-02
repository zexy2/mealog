#!/usr/bin/env python3
"""Evaluation harness.

`make eval` runs this offline against recorded fixtures and reproduces the
scorecard in the README. No API key, no network, no spend -- so the numbers we
publish can be re-derived by whoever reads the repo.

Usage:
    python eval/harness.py --configs V0,V1,V2,V3 --out eval/reports/scorecard.md
    python eval/harness.py --check-regression
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server" / "src"))

from mealog import obs                                    # noqa: E402
from mealog.adapters.vision_gemini import GeminiVision    # noqa: E402
from mealog.domain.taxonomy import ErrorCode, UNCLASSIFIED, tag_errors  # noqa: E402
from mealog.pipeline.nutrition import scale_per_100g      # noqa: E402
from mealog.locales.loader import PackUnavailableError, load  # noqa: E402
from mealog.pipeline.runner import CONFIGS, make_vision, run  # noqa: E402

sys.path.insert(0, str(REPO / "eval"))
from locale_scope import evidence_scope, exclusion_note  # noqa: E402
from metrics import (Bucket, SampleResult, aggregate, aggregate_by_tier, error_distribution,
                     spread, worst_cuisine)  # noqa: E402

GOLDEN = REPO / "eval" / "golden" / "manifest.jsonl"
BASELINE = REPO / "eval" / "reports" / "baseline.json"


def calorie_truth_complete(entry: dict) -> bool:
    """Return whether the manifest contains complete meal nutrition truth.

    Nutrition5k rows retain source ingredients that are outside the catalogue
    in ``unmapped_source_ingredients``.  Their mapped ``truth.items`` total is
    intentionally preserved for identity/portion evidence, but cannot be the
    meal's total calorie truth.
    """
    return not bool(entry.get("unmapped_source_ingredients"))


def truth_kcal(entry: dict) -> float:
    """Calculate the mapped-item calorie total; eligibility is separate."""
    pack = load(entry["locale"])
    total = 0.0
    for item in entry["truth"]["items"]:
        food = pack.foods[item["food_id"]]
        total += scale_per_100g(food.per_100g, item["grams"]).kcal
    return round(total, 1)


def truth_grams(entry: dict) -> dict[str, float]:
    """Aggregate truth mass by food ID for the E7 comparison."""
    grams: dict[str, float] = {}
    for item in entry["truth"]["items"]:
        food_id = item["food_id"]
        grams[food_id] = grams.get(food_id, 0.0) + item["grams"]
    return grams


def evaluate(
    config_name: str,
    live: bool = False,
    record: bool = False,
    locales: set[str] | None = None,
) -> list[SampleResult]:
    """Score one configuration.

    `locales` is the declared evidence scope. Rows outside it are not run at
    all: they are a scope decision made once in `main`, not a failure to load a
    pack, and conflating the two would let a broken installation masquerade as
    a deliberate exclusion.
    """
    cfg = CONFIGS[config_name]
    if live:
        vision = GeminiVision(os.getenv("GEMINI_API_KEY", ""))
    else:
        vision = make_vision("fixture")
    results = []
    skipped = set()
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if locales is not None and entry["locale"] not in locales:
            continue
        try:
            truth_kcal(entry)  # the pack must be loadable before anything runs
        except PackUnavailableError:
            # A licence-restricted catalogue that is not installed removes that
            # market from the scorecard. Say so; do not let the market vanish.
            skipped.add(entry["locale"])
            continue
        log = run(vision, entry["sample_id"], entry["locale"], cfg,
                  idempotency_key=f"eval::{config_name}::{entry['sample_id']}")
        if live and record:
            if vision.last_input is None:
                raise RuntimeError("live vision returned no input metadata to record")
            vision.record_fixture(REPO / "eval" / "fixtures", vision.last_input)
        predicted_items = [item for item in log.items if not item.abstained]
        predicted_grams: dict[str, float] = {}
        for item in predicted_items:
            predicted_grams[item.food_id] = predicted_grams.get(item.food_id, 0.0) + item.grams
        truth_ids = {i["food_id"] for i in entry["truth"]["items"]}
        pred_ids = {item.food_id for item in predicted_items}
        asked = log.action == "ask"
        expected_grams = truth_grams(entry)
        results.append(SampleResult(
            sample_id=entry["sample_id"],
            cuisine=entry["cuisine"],
            tier=entry["tier"],
            truth_ids=truth_ids,
            pred_ids=pred_ids,
            truth_kcal=truth_kcal(entry),
            pred_kcal=log.totals.kcal,
            calorie_eligible=calorie_truth_complete(entry),
            abstained=sum(i.abstained for i in log.items),
            asked=asked,
            truth_grams=expected_grams,
            pred_grams=predicted_grams,
            identity_applicable=cfg.grounded,
            error_codes=tag_errors(
                truth_ids=truth_ids,
                pred_ids=pred_ids,
                truth_grams=expected_grams,
                pred_grams=predicted_grams,
                asked=asked,
                identity_applicable=cfg.grounded,
            ),
        ))
    if skipped:
        print(
            f"[{config_name}] skipped golden samples for locale(s) {', '.join(sorted(skipped))}: "
            "catalogue not installed (licence-restricted; see docs/licensing.md). "
            "Metrics for those markets are absent, not zero.",
            file=sys.stderr,
        )
    return results


def _percent(bucket: Bucket, value: float) -> str:
    """Render a percentage without turning an empty denominator into 0%."""
    if not bucket.apes:
        return "—"
    return f"{value:.1f}%"


def scorecard(all_results: dict[str, list[SampleResult]]) -> str:
    lines = ["# Scorecard", "",
             "Generated by `make eval` (offline, recorded fixtures).",
             "Headline metric is the **worst cuisine bucket**, not the mean.", ""]

    lines += ["## Ablation", "",
              "| Config | What it adds | Worst-cuisine MAPE | Mean MAPE | Spread | Coverage | Calorie eligible | Calorie scored | Item F1 | FP rate |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, results in all_results.items():
        buckets, overall = aggregate(results)
        w = worst_cuisine(buckets)
        worst = f"{w.mape:.1f}% ({w.name})" if w else "—"
        spread_value = f"{spread(buckets):.2f}x" if any(b.apes for b in buckets.values()) else "—"
        lines.append(
            f"| {name} | {CONFIGS[name].description} | "
            f"{worst} | {_percent(overall, overall.mape)} | {spread_value} | "
            f"{overall.coverage:.0f}% | {overall.calorie_eligible} | {len(overall.apes)} | "
            f"{overall.f1:.2f} | "
            f"{overall.hallucination_rate:.1f}% |")

    for name, results in all_results.items():
        buckets, overall = aggregate(results)
        lines += ["", f"## {name} - per cuisine", "",
                  "| Cuisine | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for b in sorted(buckets.values(), key=lambda x: float(x.mape), reverse=True):
            lines.append(f"| {b.name} | {b.n} | {b.coverage:.0f}% | {b.calorie_eligible} | {len(b.apes)} | "
                         f"{b.f1:.2f} | {_percent(b, b.mape)} | {_percent(b, b.within_20pct)} | "
                         f"{b.hallucination_rate:.1f}% |")
        lines.append(f"| **overall** | **{overall.n}** | **{overall.coverage:.0f}%** | "
                     f"**{overall.calorie_eligible}** | **{len(overall.apes)}** | "
                     f"**{overall.f1:.2f}** | **{_percent(overall, overall.mape)}** | "
                     f"**{_percent(overall, overall.within_20pct)}** | "
                     f"**{overall.hallucination_rate:.1f}%** |")

        tier_buckets, tier_overall = aggregate_by_tier(results)
        lines += ["", f"## {name} - per ground-truth tier", "",
                  "| Ground-truth tier | n | Coverage | Calorie eligible | Calorie scored | Item F1 | kcal MAPE | within +/-20% | FP rate |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for b in sorted(tier_buckets.values(), key=lambda x: x.name):
            lines.append(f"| {b.name} | {b.n} | {b.coverage:.0f}% | {b.calorie_eligible} | {len(b.apes)} | "
                         f"{b.f1:.2f} | {_percent(b, b.mape)} | {_percent(b, b.within_20pct)} | "
                         f"{b.hallucination_rate:.1f}% |")
        lines.append(f"| **overall** | **{tier_overall.n}** | **{tier_overall.coverage:.0f}%** | "
                     f"**{tier_overall.calorie_eligible}** | **{len(tier_overall.apes)}** | "
                     f"**{tier_overall.f1:.2f}** | **{_percent(tier_overall, tier_overall.mape)}** | "
                     f"**{_percent(tier_overall, tier_overall.within_20pct)}** | "
                     f"**{tier_overall.hallucination_rate:.1f}%** |")

    error_labels = [code.value for code in ErrorCode] + [UNCLASSIFIED]
    lines += ["", "## Error distribution", "",
              "> One count is one sample carrying the tag. Human-causal labels are",
              "> intentionally reported as `unclassified`; no E1/E2/E5/E6/E8/E9/E10/E11",
              "> code is guessed from aggregate results.", "",
              "| Config | Error tag | Samples | Share of tagged samples |",
              "|---|---|---:|---:|"]
    for name, results in all_results.items():
        counts = error_distribution(results)
        total = sum(counts.values())
        for code in error_labels:
            count = counts.get(code, 0)
            share = count / total * 100.0 if total else 0.0
            lines.append(f"| {name} | {code} | {count} | {share:.1f}% |")

    lines += ["", "---", "",
              "> Calorie eligibility and scored counts expose the denominator: rows with",
              "> partial truth or zero calories remain visible to identity metrics but do",
              "> not become fake calorie errors. Numbers here are offline evidence, not a",
              "> claim that an empty calorie denominator means zero error.",
              "",
              "> Read MAPE and coverage together: a config that answers fewer meals",
              "> is not directly comparable to one that answers all of them. Whether",
              "> gating actually trades coverage for accuracy is a risk–coverage claim,",
              "> not a calorie-denominator shortcut; inspect both columns alongside",
              "> the eligibility/scored counts before drawing a product conclusion."]
    return "\n".join(lines) + "\n"


def manifest_locales() -> list[str]:
    """Every locale the golden set mentions, before any scope decision."""
    return sorted({
        json.loads(line)["locale"]
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    })


def summary(
    all_results: dict[str, list[SampleResult]],
    included: list[str],
    excluded: list[str],
) -> dict:
    """The machine-readable form of the numbers the README quotes.

    The README is prose and must stay prose; this is the other half of the
    contract so `scripts/check_readme_claims.py` can compare the two instead of
    trusting the person who last edited the paragraph.
    """
    out: dict = {
        "generator": "eval/harness.py",
        "scope": {"included_locales": included, "excluded_locales": excluded},
        "configs": {},
    }
    for name, results in all_results.items():
        buckets, overall = aggregate(results)
        worst = worst_cuisine(buckets)
        out["configs"][name] = {
            "rows": overall.n,
            "committed": overall.n_covered,
            "asked": overall.asked,
            "abstained": overall.abstained,
            "coverage_pct": round(overall.coverage, 1),
            "item_f1": round(overall.f1, 2),
            "fp_rate_pct": round(overall.hallucination_rate, 1),
            "mape_pct": round(float(overall.mape), 1),
            "calorie_eligible": overall.calorie_eligible,
            "calorie_scored": len(overall.apes),
            "worst_cuisine": (
                {"name": worst.name, "mape_pct": round(float(worst.mape), 1)}
                if worst else None
            ),
        }
    return out


def check_regression(all_results: dict[str, list[SampleResult]]) -> int:
    """Per-cuisine no-regression guard: improving one market must not silently
    cost another. Fails on any bucket that got worse against the stored baseline."""
    best = max(all_results)
    buckets, _ = aggregate(all_results[best])
    current = {name: round(b.mape, 2) for name, b in buckets.items() if b.apes}

    if not BASELINE.exists():
        BASELINE.write_text(json.dumps(current, indent=2))
        print(f"baseline written for {best}: {current}")
        return 0

    previous = json.loads(BASELINE.read_text())
    failures = []
    for cuisine, previous_mape in previous.items():
        bucket = buckets.get(cuisine)
        if bucket is None or not bucket.apes:
            if previous_mape > 1e-9:
                failures.append(
                    f"  {cuisine}: {previous_mape:.2f}% -> — "
                    "(no eligible calorie rows; not an improvement)"
                )
            continue
        current_mape = round(bucket.mape, 2)
        if current_mape > previous_mape + 1e-9:
            failures.append(f"  {cuisine}: {previous_mape:.2f}% -> {current_mape:.2f}%")
    if failures:
        print(f"REGRESSION in {best}:\n" + "\n".join(failures))
        return 1
    print(f"no per-cuisine regression in {best}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="V0,V1,V2,V3")
    ap.add_argument("--out", default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument(
        "--record",
        action="store_true",
        help="record live provider observations into eval/fixtures/",
    )
    ap.add_argument("--check-regression", action="store_true")
    ap.add_argument(
        "--include-restricted",
        action="store_true",
        help=(
            "also score locales whose catalogue is licence-restricted and not "
            "redistributable; the result is a local measurement a clean clone "
            "cannot reproduce, so it is not what the README publishes"
        ),
    )
    ap.add_argument(
        "--summary-json",
        default=None,
        help="write the README-facing numbers as JSON (used by scripts/check_readme_claims.py)",
    )
    args = ap.parse_args()

    if args.record and not args.live:
        ap.error("--record requires --live")

    obs.configure("WARNING")  # keep the scorecard readable; INFO for debugging

    # The scope is decided once, before any evaluation runs. A locale the
    # repository cannot distribute is excluded by default so the published
    # snapshot is exactly what a clean clone reproduces (see eval/locale_scope.py).
    locales, excluded = evidence_scope(manifest_locales(), args.include_restricted)
    print(exclusion_note(locales, excluded))

    # `make eval-live` predates the flag and must keep recording by default.
    all_results = {name: evaluate(name, live=args.live, record=args.record or args.live,
                                  locales=set(locales))
                   for name in args.configs.split(",")}

    if args.summary_json:
        path = Path(args.summary_json)
        if not path.is_absolute():
            path = REPO / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary(all_results, locales, excluded), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.summary_json}")

    if args.check_regression:
        return check_regression(all_results)

    report = scorecard(all_results)
    if args.out:
        Path(REPO / args.out).write_text(report, encoding="utf-8")
        print(f"wrote {args.out}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
