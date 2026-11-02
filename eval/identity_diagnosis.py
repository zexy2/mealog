"""Attribute identity errors to the stage that caused them.

The scorecard gives one number (Item F1) and the README gives one explanation
("perception, not retrieval, is the ceiling"). An explanation that is not
recomputed is a story. This tool replays the same fixtures and the same
retrieval/resolver code as the scorecard and charges every truth item and every
false positive to a named mechanism, so the explanation can be checked and can
fail.

Truth items are attributed in this order:

``resolved``
    The food is among the answered items.
``gating``
    It was the **top-1** candidate but the resolver abstained for being below
    ``MIN_ACCEPT_SCORE``: the catalog saw it, the risk policy refused it.
``ranking``
    It was in a top-5 candidate list but not first, so a better ranker could
    have chosen it.
``never_perceived``
    No candidate list for any perceived item contained it. The model never
    named anything that could reach the food, so no ranker or threshold can
    recover it without new evidence.

False positives are split by whether the model actually named the prediction:

``named``
    The food's canonical name or one of its aliases appears verbatim in the
    perceived surfaces. The model said this food; the score counts it because
    truth does not list it.
``fuzzy``
    It was bound by character similarity alone, so the model said something
    else and retrieval attached a nearby catalogue food.

This is a diagnostic, not a metric: it derives nothing that the scorecard does
not already measure, and it must agree with the scorecard's TP/FP totals or the
attribution is wrong. ``--json`` reports those totals so a test can assert it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _path in (REPO / "eval", REPO / "server" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import harness
from locale_scope import evidence_scope, exclusion_note
from mealog.domain.models import ABSTAIN
from mealog.locales.loader import load
from mealog.pipeline import normalize, retrieval
from mealog.pipeline.normalize import fold
from mealog.pipeline.resolve import MIN_ACCEPT_SCORE, resolve
from mealog.pipeline.runner import CONFIGS, make_vision

OUTCOMES = ("resolved", "gating", "ranking", "never_perceived")

DOC = REPO / "docs" / "identity-diagnosis.md"


def _named_in_perception(food, aliases: list[str], folded_surfaces: str, pack) -> bool:
    """True when the model's own words equal a surface for this food."""
    surfaces = [food.name, *aliases]
    return any(
        (folded := fold(surface, pack)) and folded in folded_surfaces
        for surface in surfaces
        if surface
    )


def diagnose(
    *,
    config_name: str = "V3",
    manifest_path: Path | None = None,
    include_restricted: bool = False,
    limit: int | None = None,
) -> dict:
    """Replay one configuration and attribute every truth item and FP."""
    manifest_path = manifest_path or harness.GOLDEN
    locales, excluded = evidence_scope(
        harness.manifest_locales(manifest_path), include_restricted
    )
    rows = harness.select_rows(manifest_path, set(locales), limit)
    cfg = CONFIGS[config_name]
    vision = make_vision("fixture")

    outcomes: Counter[str] = Counter()
    never_by_food: Counter[str] = Counter()
    never_grams: defaultdict[str, list[float]] = defaultdict(list)
    false_positives: Counter[str] = Counter()

    for entry in rows:
        pack = load(entry["locale"])
        perceived = vision.perceive(entry["sample_id"])
        normalized = normalize.normalize(perceived, pack, apply_rules=cfg.locale_rules)
        folded_surfaces = fold(" | ".join(item.query for item in normalized), pack)

        candidates_by_query = [
            retrieval.search(item.query, pack, k=5) for item in normalized
        ]
        resolved = [
            resolve(item.query, candidates, allow_abstain=cfg.gating)
            for item, candidates in zip(normalized, candidates_by_query)
        ]
        predicted = {item.food_id for item in resolved if item.food_id != ABSTAIN}
        truth = {item["food_id"] for item in entry["truth"]["items"]}

        for item in entry["truth"]["items"]:
            food_id = item["food_id"]
            if food_id in predicted:
                outcomes["resolved"] += 1
                continue
            hit = [c for c in candidates_by_query if any(x.food_id == food_id for x in c)]
            if not hit:
                outcomes["never_perceived"] += 1
                never_by_food[food_id] += 1
                if item.get("grams"):
                    never_grams[food_id].append(float(item["grams"]))
            elif hit[0] and hit[0][0].food_id == food_id:
                outcomes["gating"] += 1
            else:
                outcomes["ranking"] += 1

        for food_id in predicted - truth:
            false_positives["total"] += 1
            food = pack.foods[food_id]
            if _named_in_perception(food, pack.aliases.get(food_id, []), folded_surfaces, pack):
                false_positives["named"] += 1
            else:
                false_positives["fuzzy"] += 1
            if entry.get("unmapped_source_ingredients"):
                false_positives["on_partial_truth"] += 1

    # The attribution must reproduce the scorecard, or it explains something
    # else. Re-run the scored path rather than recomputing its definitions here.
    results, row_errors = harness.evaluate(
        config_name,
        locales=set(locales),
        manifest_path=manifest_path,
        limit=limit,
    )
    scored_tp = sum(len(result.truth_ids & result.pred_ids) for result in results)
    scored_fp = sum(len(result.pred_ids - result.truth_ids) for result in results)

    truth_items = sum(outcomes.values())
    reachable = outcomes["resolved"] + outcomes["gating"] + outcomes["ranking"]
    ceiling_f1 = (
        2 * reachable / (2 * reachable + outcomes["never_perceived"])
        if truth_items
        else 0.0
    )
    f1 = (
        2 * scored_tp / (2 * scored_tp + scored_fp + (truth_items - scored_tp))
        if truth_items
        else 0.0
    )

    return {
        "config": config_name,
        "rows": len(rows),
        "row_errors": row_errors,
        "scope": {"included_locales": locales, "excluded_locales": excluded},
        "truth_items": truth_items,
        "outcomes": {name: outcomes[name] for name in OUTCOMES},
        "false_positives": {
            "total": false_positives["total"],
            "named": false_positives["named"],
            "fuzzy": false_positives["fuzzy"],
            "on_partial_truth": false_positives["on_partial_truth"],
        },
        "never_perceived_by_food": [
            {
                "food_id": food_id,
                "count": count,
                "median_grams": (
                    round(statistics.median(never_grams[food_id]), 2)
                    if never_grams[food_id]
                    else None
                ),
            }
            for food_id, count in never_by_food.most_common()
        ],
        "agreement": {
            "scorecard_tp": scored_tp,
            "scorecard_fp": scored_fp,
            "attributed_tp": outcomes["resolved"],
            "attributed_fp": false_positives["total"],
            "matches": scored_tp == outcomes["resolved"]
            and scored_fp == false_positives["total"],
        },
        "item_f1": round(f1, 3),
        "perfect_resolver_f1": round(ceiling_f1, 3),
        "min_accept_score": MIN_ACCEPT_SCORE,
    }


def _share(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "—"


def render_markdown(report: dict) -> str:
    total = report["truth_items"]
    outcomes = report["outcomes"]
    fps = report["false_positives"]
    rows = [
        ("Resolved (TP)", outcomes["resolved"], "the food was answered"),
        (
            "Gating",
            outcomes["gating"],
            f"ranked first, refused below the {report['min_accept_score']} accept threshold",
        ),
        ("Ranking", outcomes["ranking"], "in a top-5 list, not first"),
        ("Never perceived", outcomes["never_perceived"], "no candidate list contained it"),
    ]

    lines = [
        "# Identity diagnosis",
        "",
        f"Generated by `python eval/identity_diagnosis.py --configs {report['config']}`.",
        "It replays the committed fixtures and attributes every truth item and",
        "false positive to a named stage. The totals are cross-checked against",
        "the scorecard, because an attribution that does not reproduce the metric",
        "is a story about a different run.",
        "",
        exclusion_note(
            report["scope"]["included_locales"], report["scope"]["excluded_locales"]
        ),
        "",
        "## Where the truth items go",
        "",
        "| Outcome | Truth items | Share | What it means |",
        "|---|---:|---:|---|",
    ]
    lines += [
        f"| {label} | {count} | {_share(count, total)} | {meaning} |"
        for label, count, meaning in rows
    ]
    lines += [
        f"| **Total** | **{total}** | **100%** | |",
        "",
        "A perfect resolver over the foods the model actually named would reach at",
        (f"most Item F1 **{report['perfect_resolver_f1']:.2f}** on this truth set. "
         f"{outcomes['never_perceived']} items never entered a"),
        "candidate list, so no ranker or threshold can recover them.",
        f"The current F1 is **{report['item_f1']:.2f}**.",
        "",
        "## Never perceived, by food",
        "",
        "| Food | Truth items | Median source grams |",
        "|---|---:|---:|",
    ]
    for row in report["never_perceived_by_food"][:12]:
        grams = "—" if row["median_grams"] is None else f"{row['median_grams']:g}"
        lines.append(f"| `{row['food_id']}` | {row['count']} | {grams} |")
    lines += [
        "",
        "A truth item that never reaches a candidate list is a perception gap, not a",
        "resolver gap. Small `median_grams` rows are the more awkward case: cooking",
        "oil and garnish dollops a photograph cannot show at any detection quality,",
        "because the truth is a recipe rather than a plate.",
        "",
        "## False positives",
        "",
        "| Class | Count | Share |",
        "|---|---:|---:|",
    ]
    lines += [
        f"| {label} | {count} | {_share(count, fps['total'])} |"
        for label, count in [
            ("Named in the perception", fps["named"]),
            ("Bound by similarity only", fps["fuzzy"]),
        ]
    ]
    lines += [
        f"| **Total** | **{fps['total']}** | **100%** |",
        "",
        "A named false positive is a food the model said and truth does not list. A",
        "fuzzy one is retrieval attaching a plausible neighbour to a surface the",
        "model did use, which is the only class a better ranker can fix.",
        "",
        (f"{fps['on_partial_truth']} of the {fps['total']} "
         f"({_share(fps['on_partial_truth'], fps['total'])}) also sit on a row"),
        "whose truth is incomplete (`unmapped_source_ingredients` is non-empty).",
        "That is a different axis, and on those rows a named false positive is a",
        "measurement limit rather than a model error.",
        "",
        "## Cross-check",
        "",
        f"- Attributed TP/FP: {report['agreement']['attributed_tp']} / {report['agreement']['attributed_fp']}.",
        f"- Scorecard TP/FP: {report['agreement']['scorecard_tp']} / {report['agreement']['scorecard_fp']}.",
        f"- Agreement: {'yes' if report['agreement']['matches'] else 'NO — investigate'}.",
        "",
        f"Scope: {report['rows']} rows in the published evidence scope.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="V3")
    ap.add_argument("--manifest", type=Path, default=harness.GOLDEN)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None, help="write the same counts as JSON")
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail if docs/identity-diagnosis.md is not what this run generates",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--include-restricted", action="store_true")
    args = ap.parse_args()

    if args.check:
        args.out = str(DOC) if args.out is None else args.out

    if args.configs != "V3":
        ap.error("the diagnosis attributes the gated configuration; pass V3")

    report = diagnose(
        config_name=args.configs,
        manifest_path=args.manifest,
        include_restricted=args.include_restricted,
        limit=args.limit,
    )
    markdown = render_markdown(report)
    if args.check:
        current = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
        if current != markdown:
            print(
                f"{DOC.relative_to(REPO)} is stale. Run "
                "`python eval/identity_diagnosis.py --out docs/identity-diagnosis.md` "
                "and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"{DOC.relative_to(REPO)} matches the committed fixtures")
    elif args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(markdown)

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    if not report["agreement"]["matches"]:
        print("attribution does not reproduce the scorecard; do not publish it",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
