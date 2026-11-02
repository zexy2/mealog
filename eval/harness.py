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
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server" / "src"))

from mealog import obs                                    # noqa: E402
from mealog.adapters.vision_gemini import (                # noqa: E402
    PROMPT_VARIANTS,
    PROMPT_VERSION,
    GeminiVision,
    configured_model_id,
)
from mealog.domain.taxonomy import ErrorCode, UNCLASSIFIED, tag_errors  # noqa: E402
from mealog.pipeline.nutrition import scale_per_100g      # noqa: E402
from mealog.locales.loader import PackUnavailableError, load  # noqa: E402
from mealog.pipeline.runner import CONFIGS, make_vision, run  # noqa: E402

sys.path.insert(0, str(REPO / "eval"))
from golden_inputs import (  # noqa: E402
    LiveExclusion,
    LiveIneligibleRow,
    input_for_row,
    live_ineligible_reason,
    load_manifest,
)
from locale_scope import evidence_scope, exclusion_note  # noqa: E402
from metrics import (Bucket, SampleResult, aggregate, aggregate_by_tier, error_distribution,
                     spread, worst_cuisine)  # noqa: E402

GOLDEN = REPO / "eval" / "golden" / "manifest.jsonl"
IMAGES = REPO / "data" / "golden-images"
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


def select_rows(
    manifest_path: Path = GOLDEN,
    locales: set[str] | None = None,
    limit: int | None = None,
    *,
    live: bool = False,
    exclusions: list[LiveExclusion] | None = None,
) -> list[dict]:
    """Golden rows in manifest order, after scope filtering and an optional limit.

    A live run drops rows whose image licence does not permit third-party
    processing. The drop happens before ``limit`` so ``--live --limit 10``
    requests ten eligible rows, and ``exclusions`` receives one structured
    record per dropped row for the scorecard and summary.
    """
    rows = load_manifest(manifest_path)
    if locales is not None:
        rows = [row for row in rows if row["locale"] in locales]
    if live:
        eligible = []
        for row in rows:
            reason = live_ineligible_reason(row)
            if reason is None:
                eligible.append(row)
            elif exclusions is not None:
                exclusions.append(LiveExclusion(
                    sample_id=row["sample_id"],
                    image_license=row.get("image_license"),
                    reason=reason,
                ))
        rows = eligible
    if limit is not None:
        rows = rows[:limit]
    return rows


def evaluate(
    config_name: str,
    *,
    live: bool = False,
    locales: set[str] | None = None,
    manifest_path: Path = GOLDEN,
    images_dir: Path = IMAGES,
    limit: int | None = None,
    prompt_variant: str = PROMPT_VERSION,
    adapter_sink: list[Any] | None = None,
) -> tuple[list[SampleResult], list[str]]:
    """Score one configuration and return ``(results, row_errors)``.

    ``locales`` is the declared evidence scope. Rows outside it are not run at
    all: they are a scope decision made once in `main`, not a failure to load a
    pack, and conflating the two would let a broken installation masquerade as
    a deliberate exclusion.

    Offline replays fixtures by ``sample_id`` and raises on a broken fixture:
    that is a repository defect, not a measurement. Live sends image bytes or
    explicit text from the manifest and isolates input/provider failures per
    row. A failed live row is named in ``row_errors`` and the rest still run.

    ``adapter_sink`` is an optional live-only hook: the constructed adapter is
    appended so ``main`` can read the served model and effective budget after
    the run. Offline construction is unchanged.
    """
    cfg = CONFIGS[config_name]
    if live:
        # The variant is a live-provider concern. Offline replays fixtures by
        # sample_id, so the flag has no meaning there and is not plumbed in.
        vision = GeminiVision(
            os.getenv("GEMINI_API_KEY", ""), prompt_variant=prompt_variant
        )
        if adapter_sink is not None:
            adapter_sink.append(vision)
    else:
        vision = make_vision("fixture")
    results = []
    row_errors: list[str] = []
    skipped = set()
    for entry in select_rows(manifest_path, locales, limit, live=live):
        try:
            truth_kcal(entry)  # the pack must be loadable before anything runs
        except PackUnavailableError:
            # A licence-restricted catalogue that is not installed removes that
            # market from the scorecard. Say so; do not let the market vanish.
            skipped.add(entry["locale"])
            continue
        if live:
            sample_id = entry["sample_id"]
            try:
                log = run(
                    vision,
                    input_for_row(entry, images_dir),
                    entry["locale"],
                    cfg,
                    idempotency_key=f"eval::{config_name}::{sample_id}",
                )
            except LiveIneligibleRow:
                # select_rows should have removed this row. If it did not, a
                # licence refusal is a defect in the selection, not a failed
                # measurement, so do not let it look like a provider error.
                raise
            except (OSError, ValueError, RuntimeError) as exc:
                # Input/provider failure for this row only; keep measuring.
                print(f"row {sample_id} failed: {exc}", file=sys.stderr)
                row_errors.append(sample_id)
                continue
        else:
            log = run(vision, entry["sample_id"], entry["locale"], cfg,
                      idempotency_key=f"eval::{config_name}::{entry['sample_id']}")
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
    return results, row_errors


def _percent(bucket: Bucket, value: float) -> str:
    """Render a percentage without turning an empty denominator into 0%."""
    if not bucket.apes:
        return "—"
    return f"{value:.1f}%"


def scorecard(
    all_results: dict[str, list[SampleResult]],
    *,
    mode: str = "offline",
    provider_model: str | None = None,
    prompt_version: str = PROMPT_VERSION,
    rows_requested: int | None = None,
    rows_scoped: int | None = None,
    live_exclusions: list[LiveExclusion] | None = None,
    model_versions: list[str] | None = None,
    max_elapsed_seconds: float | None = None,
    request_timeout_seconds: float | None = None,
) -> str:
    lines = ["# Scorecard", ""]
    if mode == "live":
        lines += [
            (
                "Generated by `make eval-live`: a live provider measurement "
                f"(model `{provider_model}`, prompt `{prompt_version}`)."
            ),
        ]
        if model_versions is not None:
            if len(model_versions) == 1:
                lines.append(
                    f"Provider model: `{provider_model}` (requested); "
                    f"served `{model_versions[0]}`."
                )
            elif len(model_versions) > 1:
                served = ", ".join(f"`{version}`" for version in model_versions)
                lines.append(
                    f"Provider model: `{provider_model}` (requested); served by "
                    f"multiple versions: {served}; not a single-model measurement."
                )
            else:
                lines.append(
                    f"Provider model: `{provider_model}` (requested); "
                    "served version not reported by the provider."
                )
        if max_elapsed_seconds is not None:
            timeout_clause = (
                f"a single request may use the {request_timeout_seconds:g}s request timeout"
                if request_timeout_seconds is not None
                else "a single request may use its configured request timeout"
            )
            lines.append(
                f"Wall-clock budget: {max_elapsed_seconds:g}s per row; retries "
                f"and fallbacks stop at the budget, {timeout_clause}."
            )
        lines += [
            (
                "It is not reproducible (provider outputs vary) and is not "
                "comparable to the offline snapshot."
            ),
            "Headline metric is the **worst cuisine bucket**, not the mean.", "",
        ]
        if live_exclusions is not None:
            requested = rows_requested or 0
            excluded_count = len(live_exclusions)
            if rows_scoped is None:
                total = requested + excluded_count
                lines.append(
                    f"Live scope: {requested} of {total} scoped manifest rows "
                    f"requested; {excluded_count} excluded by image licence."
                )
            else:
                eligible = rows_scoped - excluded_count
                if requested == eligible:
                    lines.append(
                        f"Live scope: {eligible} of {rows_scoped} scoped "
                        f"manifest rows requested; {excluded_count} excluded "
                        "by image licence."
                    )
                else:
                    lines.append(
                        f"Live scope: {eligible} of {rows_scoped} scoped "
                        f"manifest rows eligible; {excluded_count} excluded by "
                        f"image licence; {requested} requested after --limit."
                    )
            if live_exclusions:
                details = "; ".join(
                    f"{row.sample_id} ({row.reason})" for row in live_exclusions
                )
                lines.append(f"Excluded by licence: {details}")
            lines.append("")
    else:
        lines += [
            "Generated by `make eval` (offline, recorded fixtures).",
            "Headline metric is the **worst cuisine bucket**, not the mean.", "",
        ]

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

    provenance = ("a live observation" if mode == "live"
                  else "offline evidence")
    lines += ["", "---", "",
              "> Calorie eligibility and scored counts expose the denominator: rows with",
              "> partial truth or zero calories remain visible to identity metrics but do",
              f"> not become fake calorie errors. Numbers here are {provenance}, not a",
              "> claim that an empty calorie denominator means zero error.",
              "",
              "> Read MAPE and coverage together: a config that answers fewer meals",
              "> is not directly comparable to one that answers all of them. Whether",
              "> gating actually trades coverage for accuracy is a risk–coverage claim,",
              "> not a calorie-denominator shortcut; inspect both columns alongside",
              "> the eligibility/scored counts before drawing a product conclusion."]
    return "\n".join(lines) + "\n"


def manifest_locales(manifest_path: Path = GOLDEN) -> list[str]:
    """Every locale the selected golden manifest mentions, before scope."""
    return sorted({row["locale"] for row in load_manifest(manifest_path)})


def summary(
    all_results: dict[str, list[SampleResult]],
    included: list[str],
    excluded: list[str],
    *,
    mode: str = "offline",
    provider_model: str | None = None,
    prompt_version: str | None = PROMPT_VERSION,
    prompt_variant: str | None = None,
    rows_requested: int | None = None,
    row_errors: list[str] | None = None,
    live_exclusions: list[LiveExclusion] | None = None,
    model_versions: list[str] | None = None,
    max_elapsed_seconds: float | None = None,
) -> dict:
    """The machine-readable form of the numbers the README quotes.

    The README is prose and must stay prose; this is the other half of the
    contract so `scripts/check_readme_claims.py` can compare the two instead of
    trusting the person who last edited the paragraph.

    ``mode``/``provider_model``/``prompt_version`` describe how the run was
    produced. ``rows_requested`` is the manifest row count after scope, live
    eligibility, and ``--limit``; ``row_errors`` names live rows that failed
    without stopping the run. Live summaries also carry
    ``provider_model_versions`` (every observed version, in order) and
    ``provider_model_version`` (the single version, or ``None`` when there were
    none or several), plus ``effective_budget_seconds``, ``rows_excluded_live``
    and the ids, licences, and reasons behind the rule-based cap; offline
    summaries keep their existing shape.
    """
    out: dict = {
        "generator": "eval/harness.py",
        "mode": mode,
        "provider_model": provider_model,
        "prompt_version": prompt_version,
        "prompt_variant": prompt_variant or prompt_version,
        "rows_requested": rows_requested,
        "row_errors": list(row_errors or []),
        "scope": {"included_locales": included, "excluded_locales": excluded},
        "configs": {},
    }
    if mode == "live":
        versions = list(model_versions or [])
        out["provider_model_version"] = versions[0] if len(versions) == 1 else None
        out["provider_model_versions"] = versions
        out["effective_budget_seconds"] = max_elapsed_seconds
        exclusions = list(live_exclusions or [])
        out["rows_excluded_live"] = len(exclusions)
        out["live_exclusions"] = [
            {
                "sample_id": row.sample_id,
                "image_license": row.image_license,
                "reason": row.reason,
            }
            for row in exclusions
        ]
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
        "--manifest",
        type=Path,
        default=GOLDEN,
        help="JSONL golden manifest (default: eval/golden/manifest.jsonl)",
    )
    ap.add_argument(
        "--images-dir",
        type=Path,
        default=IMAGES,
        help="directory holding manifest image_filename files (default: data/golden-images)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="run at most N rows after scope filtering, in manifest order",
    )
    ap.add_argument(
        "--prompt-variant",
        default=PROMPT_VERSION,
        choices=PROMPT_VARIANTS,
        help=(
            "named prompt variant for --live (default: the shipping variant, "
            f"{PROMPT_VERSION}); ignored offline, where fixtures replay by sample_id"
        ),
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

    if args.limit is not None and args.limit < 0:
        ap.error("--limit cannot be negative")

    manifest_path = args.manifest if args.manifest.is_absolute() else REPO / args.manifest
    images_dir = args.images_dir if args.images_dir.is_absolute() else REPO / args.images_dir

    obs.configure("WARNING")  # keep the scorecard readable; INFO for debugging

    # The scope is decided once, before any evaluation runs. A locale the
    # repository cannot distribute is excluded by default so the published
    # snapshot is exactly what a clean clone reproduces (see eval/locale_scope.py).
    locales, excluded = evidence_scope(
        manifest_locales(manifest_path), args.include_restricted
    )
    print(exclusion_note(locales, excluded))
    rows_scoped = len(select_rows(manifest_path, set(locales))) if args.live else None
    live_exclusions: list[LiveExclusion] = []
    selected = select_rows(
        manifest_path,
        set(locales),
        args.limit,
        live=args.live,
        exclusions=live_exclusions,
    )

    # Offline output must not change when the flag is passed: fixtures replay
    # by sample_id, so the shipping variant is what that run actually used.
    run_prompt_variant = args.prompt_variant if args.live else PROMPT_VERSION

    all_results: dict[str, list[SampleResult]] = {}
    row_errors: list[str] = []
    adapters: list[Any] = []
    for name in args.configs.split(","):
        results, errors = evaluate(
            name,
            live=args.live,
            locales=set(locales),
            manifest_path=manifest_path,
            images_dir=images_dir,
            limit=args.limit,
            prompt_variant=run_prompt_variant,
            adapter_sink=adapters if args.live else None,
        )
        all_results[name] = results
        row_errors.extend(errors)
    failed_ids = list(dict.fromkeys(row_errors))

    mode = "live" if args.live else "offline"
    provider_model = configured_model_id() if args.live else None
    model_versions: list[str] = []
    max_elapsed_seconds: float | None = None
    request_timeout_seconds: float | None = None
    if args.live:
        # One adapter is constructed per configuration; the run's identity is
        # the union of every version any of them observed, not the last row.
        for adapter in adapters:
            versions = getattr(adapter, "observed_model_versions", None)
            if versions is None:
                last = getattr(adapter, "last_model_version", None)
                versions = [last] if last else []
            for version in versions:
                if version and version not in model_versions:
                    model_versions.append(version)
        if adapters:
            max_elapsed_seconds = getattr(adapters[-1], "max_elapsed", None)
            request_timeout_seconds = getattr(adapters[-1], "timeout", None)

    if args.summary_json:
        path = Path(args.summary_json)
        if not path.is_absolute():
            path = REPO / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                summary(
                    all_results,
                    locales,
                    excluded,
                    mode=mode,
                    provider_model=provider_model,
                    prompt_version=run_prompt_variant,
                    prompt_variant=run_prompt_variant,
                    rows_requested=len(selected),
                    row_errors=failed_ids,
                    live_exclusions=live_exclusions if args.live else None,
                    model_versions=model_versions,
                    max_elapsed_seconds=max_elapsed_seconds,
                ),
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.summary_json}")

    exit_code = 0
    if args.check_regression:
        exit_code = check_regression(all_results)
    else:
        report = scorecard(
            all_results,
            mode=mode,
            provider_model=provider_model,
            prompt_version=run_prompt_variant,
            rows_requested=len(selected),
            rows_scoped=rows_scoped,
            live_exclusions=live_exclusions if args.live else None,
            model_versions=model_versions,
            max_elapsed_seconds=max_elapsed_seconds,
            request_timeout_seconds=request_timeout_seconds,
        )
        if args.out:
            Path(REPO / args.out).write_text(report, encoding="utf-8")
            print(f"wrote {args.out}")
        print(report)

    if args.live:
        expected = len(selected) * len(all_results)
        scored = sum(len(results) for results in all_results.values())
        detail = f"; failed rows: {', '.join(failed_ids)}" if failed_ids else ""
        print(
            f"live evaluation: {scored}/{expected} config-rows scored"
            f"{detail}",
            file=sys.stderr,
        )
        if failed_ids:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
