"""Compare truth-item outcomes across live prediction artifacts.

``eval/harness.py --predictions`` writes one JSON line per attempted live row:
what the model perceived, what the resolver answered, and the truth the row was
scored against. Reading several of those files by hand to answer "did this
prompt perceive more truth items, or commit more of what it already perceived?"
produces an answer once and cannot be checked afterwards. This tool applies one
classification rule to every artifact, so two analysts with the same files get
the same numbers, and a comparison names its denominator.

Each truth item in a successfully scored row is classified once, in this order:

``resolved``
    The food id is in the row's ``pred_ids``.
``perceived``
    It appears in a candidate list of some item in the row's ``perceived``, but
    was not answered. A better ranker or threshold could reach it.
``absent``
    No candidate list in that row contained it. No ranker can recover it without
    new perception.

A failed row (``row_error`` is non-null) is not a measurement: it is counted in
the denominator and named, but its truth items are not classified. With two
artifacts the flow between classes is computed only on the sample ids both
artifacts scored successfully; rows outside that intersection are listed with
the counts they contribute, so an intersection result is never presented as a
full-run comparison.

The artifact keeps at most three candidates per perceived item, while the
offline identity diagnosis uses five, so ``absent`` is stricter here and the two
counts are not interchangeable.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CLASSES = ("resolved", "perceived", "absent")

CAVEAT = (
    "The artifact records at most the top three candidates for each perceived "
    "item, while the offline identity diagnosis uses the top five. `absent` here "
    "is therefore stricter, and these counts are not interchangeable with the "
    "diagnosis."
)

REQUIRED_KEYS = (
    "config",
    "sample_id",
    "locale",
    "cuisine",
    "tier",
    "prompt_variant",
    "perceived",
    "truth_ids",
    "pred_ids",
    "row_error",
)

STRING_KEYS = ("config", "sample_id", "locale", "cuisine", "tier")


class ArtifactError(Exception):
    """An artifact that cannot be compared without guessing."""

    def __init__(self, path: Path, line: int | None, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.line is None:
            return f"{self.path}: {self.message}"
        return f"{self.path}:{self.line}: {self.message}"


def _validate(path: Path, line: int, record: dict) -> None:
    for key in REQUIRED_KEYS:
        if key not in record:
            raise ArtifactError(path, line, f"missing required key {key!r}")
    for key in STRING_KEYS:
        if not isinstance(record[key], str):
            raise ArtifactError(path, line, f"{key} must be a string")
    if record["prompt_variant"] is not None and not isinstance(
        record["prompt_variant"], str
    ):
        raise ArtifactError(path, line, "prompt_variant must be a string or null")
    for key in ("truth_ids", "pred_ids"):
        value = record[key]
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise ArtifactError(path, line, f"{key} must be a list of food ids")
    if not isinstance(record["perceived"], list):
        raise ArtifactError(path, line, "perceived must be a list")
    for index, item in enumerate(record["perceived"]):
        if not isinstance(item, dict):
            raise ArtifactError(
                path, line, f"perceived[{index}] must be an object"
            )
        if "candidates" not in item:
            raise ArtifactError(
                path, line, f"missing required key 'perceived[{index}].candidates'"
            )
        if not isinstance(item["candidates"], list):
            raise ArtifactError(
                path, line, f"perceived[{index}].candidates must be a list"
            )
        for position, candidate in enumerate(item["candidates"]):
            if not isinstance(candidate, dict) or "food_id" not in candidate:
                raise ArtifactError(
                    path,
                    line,
                    "missing required key "
                    f"'perceived[{index}].candidates[{position}].food_id'",
                )
            if not isinstance(candidate["food_id"], str):
                raise ArtifactError(
                    path,
                    line,
                    f"perceived[{index}].candidates[{position}].food_id must be a string",
                )
    if record["row_error"] is not None and not isinstance(record["row_error"], str):
        raise ArtifactError(path, line, "row_error must be a string or null")


def load_artifact(path: Path) -> list[dict]:
    """Read one JSONL artifact, refusing to skip a line it cannot read."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactError(path, None, f"cannot read artifact: {exc}") from exc

    rows: list[dict] = []
    first_line: dict[str, int] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArtifactError(
                path,
                line_number,
                f"malformed JSON: {exc.msg} (column {exc.colno})",
            ) from exc
        if not isinstance(record, dict):
            raise ArtifactError(
                path, line_number, f"expected a JSON object, got {type(record).__name__}"
            )
        _validate(path, line_number, record)
        sample_id = record["sample_id"]
        if sample_id in first_line:
            # The join key starts with sample_id; a repeated row would make the
            # flow table compare a row with itself or silently drop one side.
            raise ArtifactError(
                path,
                line_number,
                f"duplicate sample_id {sample_id!r} (first at line "
                f"{first_line[sample_id]})",
            )
        first_line[sample_id] = line_number
        record["_line"] = line_number
        rows.append(record)

    if not rows:
        raise ArtifactError(
            path, None, "artifact has no rows; an empty artifact is not a zero result"
        )
    return rows


def _row_classes(row: dict) -> list[tuple[str, str]]:
    """One ``(food_id, class)`` pair per truth occurrence, in row order."""
    predicted = set(row["pred_ids"])
    perceived = {
        candidate["food_id"]
        for item in row["perceived"]
        for candidate in item["candidates"]
    }
    classes = []
    for food_id in row["truth_ids"]:
        if food_id in predicted:
            classes.append((food_id, "resolved"))
        elif food_id in perceived:
            classes.append((food_id, "perceived"))
        else:
            classes.append((food_id, "absent"))
    return classes


def _class_bucket(counter: Counter[str]) -> dict[str, int]:
    bucket = {name: counter[name] for name in CLASSES}
    bucket["truth_items"] = sum(counter[name] for name in CLASSES)
    return bucket


def _bucket_order(buckets: dict[str, dict[str, int]]) -> list[str]:
    return sorted(buckets, key=lambda name: (-buckets[name]["truth_items"], name))


def summarize(path: Path, rows: list[dict]) -> dict:
    """Classify one artifact, keeping failed rows out of the class counts."""
    failed = [row for row in rows if row["row_error"] is not None]
    scored = [row for row in rows if row["row_error"] is None]

    classes: Counter[str] = Counter()
    by_cuisine: defaultdict[str, Counter[str]] = defaultdict(Counter)
    by_tier: defaultdict[str, Counter[str]] = defaultdict(Counter)
    absent_foods: Counter[str] = Counter()

    for row in scored:
        for food_id, outcome in _row_classes(row):
            classes[outcome] += 1
            by_cuisine[row["cuisine"]][outcome] += 1
            by_tier[row["tier"]][outcome] += 1
            if outcome == "absent":
                absent_foods[food_id] += 1

    return {
        "path": str(path),
        "configs": sorted({row["config"] for row in rows}),
        "prompt_variants": sorted(
            {row["prompt_variant"] or "unspecified" for row in rows}
        ),
        "rows": len(rows),
        "failed_rows": len(failed),
        "scored_rows": len(scored),
        "rows_with_truth": sum(1 for row in rows if row["truth_ids"]),
        "truth_items": sum(classes.values()),
        "failed_truth_items": sum(len(row["truth_ids"]) for row in failed),
        "classes": {name: classes[name] for name in CLASSES},
        "by_cuisine": {
            name: _class_bucket(by_cuisine[name])
            for name in _bucket_order(by_cuisine)
        },
        "by_tier": {
            name: _class_bucket(by_tier[name]) for name in _bucket_order(by_tier)
        },
        "absent_foods": [
            {"food_id": food_id, "count": count}
            for food_id, count in sorted(
                absent_foods.items(), key=lambda pair: (-pair[1], pair[0])
            )
        ],
        "sample_ids": [row["sample_id"] for row in rows],
        "failed": [
            {
                "sample_id": row["sample_id"],
                "line": row["_line"],
                "row_error": row["row_error"],
            }
            for row in failed
        ],
    }


def compare(
    baseline_rows: list[dict],
    candidate_rows: list[dict],
    baseline_summary: dict,
    candidate_summary: dict,
) -> dict:
    """Join two artifacts on ``(sample_id, food_id)`` over their common rows."""
    baseline_scored = {
        row["sample_id"]: row
        for row in baseline_rows
        if row["row_error"] is None
    }
    candidate_scored = {
        row["sample_id"]: row
        for row in candidate_rows
        if row["row_error"] is None
    }

    intersection = [
        sample_id for sample_id in baseline_scored if sample_id in candidate_scored
    ]
    dropped_baseline = [
        sample_id for sample_id in baseline_scored if sample_id not in candidate_scored
    ]
    dropped_candidate = [
        sample_id for sample_id in candidate_scored if sample_id not in baseline_scored
    ]

    baseline_ids = set(baseline_summary["sample_ids"])
    candidate_ids = set(candidate_summary["sample_ids"])
    only_baseline = [
        sample_id for sample_id in baseline_summary["sample_ids"]
        if sample_id not in candidate_ids
    ]
    only_candidate = [
        sample_id for sample_id in candidate_summary["sample_ids"]
        if sample_id not in baseline_ids
    ]

    flows = {baseline: {candidate: 0 for candidate in CLASSES} for baseline in CLASSES}
    candidate_classes = {
        sample_id: dict(_row_classes(candidate_scored[sample_id]))
        for sample_id in intersection
    }
    for sample_id in intersection:
        counterpart = candidate_classes[sample_id]
        for food_id, baseline_class in _row_classes(baseline_scored[sample_id]):
            candidate_class = counterpart.get(food_id)
            if candidate_class is not None:
                flows[baseline_class][candidate_class] += 1

    baseline_totals = {
        name: sum(flows[name][other] for other in CLASSES) for name in CLASSES
    }
    candidate_totals = {
        name: sum(flows[other][name] for other in CLASSES) for name in CLASSES
    }
    net = {
        name: candidate_totals[name] - baseline_totals[name] for name in CLASSES
    }

    # Truth sets should match for a shared row because both artifacts are scored
    # against the same manifest. If they do not, the join loses items; count them
    # instead of letting the flow table look complete.
    baseline_keys: Counter[tuple[str, str]] = Counter(
        (sample_id, food_id)
        for sample_id in intersection
        for food_id in baseline_scored[sample_id]["truth_ids"]
    )
    candidate_keys: Counter[tuple[str, str]] = Counter(
        (sample_id, food_id)
        for sample_id in intersection
        for food_id in candidate_scored[sample_id]["truth_ids"]
    )
    unpaired_baseline = sum(
        max(0, count - candidate_keys[key]) for key, count in baseline_keys.items()
    )
    unpaired_candidate = sum(
        max(0, count - baseline_keys[key]) for key, count in candidate_keys.items()
    )

    if dropped_baseline or dropped_candidate:
        state = "intersection_only"
    else:
        state = "same_rows"

    variants_same = (
        baseline_summary["prompt_variants"]
        == candidate_summary["prompt_variants"]
    )

    return {
        "join_key": ["sample_id", "food_id"],
        "state": state,
        "prompt_variants": {
            "baseline": baseline_summary["prompt_variants"],
            "candidate": candidate_summary["prompt_variants"],
            "same": variants_same,
        },
        "flows": flows,
        "baseline_totals": baseline_totals,
        "candidate_totals": candidate_totals,
        "net": net,
        "guard": {
            "baseline_scored_rows": len(baseline_scored),
            "candidate_scored_rows": len(candidate_scored),
            "intersection_rows": len(intersection),
            "only_in_baseline": only_baseline,
            "only_in_candidate": only_candidate,
            "baseline_failed": [row["sample_id"] for row in baseline_summary["failed"]],
            "candidate_failed": [row["sample_id"] for row in candidate_summary["failed"]],
            "dropped_baseline_rows": dropped_baseline,
            "dropped_candidate_rows": dropped_candidate,
            "dropped_baseline_truth_items": sum(
                len(baseline_scored[sample_id]["truth_ids"])
                for sample_id in dropped_baseline
            ),
            "dropped_candidate_truth_items": sum(
                len(candidate_scored[sample_id]["truth_ids"])
                for sample_id in dropped_candidate
            ),
            "unpaired_baseline_truth_items": unpaired_baseline,
            "unpaired_candidate_truth_items": unpaired_candidate,
        },
    }


def build_report(
    baseline_path: Path,
    baseline_rows: list[dict],
    candidate_path: Path | None = None,
    candidate_rows: list[dict] | None = None,
) -> dict:
    baseline = summarize(baseline_path, baseline_rows)
    candidate = (
        summarize(candidate_path, candidate_rows)
        if candidate_path is not None and candidate_rows is not None
        else None
    )
    comparison = (
        compare(baseline_rows, candidate_rows, baseline, candidate)
        if candidate is not None and candidate_rows is not None
        else None
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "caveat": CAVEAT,
    }


def _share(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%" if total else "—"


def _names(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _summary_lines(title: str, summary: dict) -> list[str]:
    lines = [
        f"## {title}: `{summary['path']}`",
        "",
        (
            f"Config {', '.join(summary['configs'])}; prompt variant "
            f"{', '.join(summary['prompt_variants'])}."
        ),
        "",
        "### Denominator",
        "",
        "| | Count |",
        "|---|---:|",
        f"| Rows in artifact | {summary['rows']} |",
        f"| Failed rows | {summary['failed_rows']} |",
        f"| Rows with truth | {summary['rows_with_truth']} |",
        f"| Successfully scored rows | {summary['scored_rows']} |",
        f"| Truth items scored | {summary['truth_items']} |",
        f"| Truth items on failed rows | {summary['failed_truth_items']} |",
    ]
    if summary["failed"]:
        lines += [
            "",
            "Failed rows (excluded from the class counts): "
            + "; ".join(
                f"`{row['sample_id']}` line {row['line']} — {row['row_error']}"
                for row in summary["failed"]
            )
            + ".",
        ]

    lines += [
        "",
        "### Truth items by class",
        "",
        "| Class | Items | Share |",
        "|---|---:|---:|",
    ]
    for name in CLASSES:
        count = summary["classes"][name]
        lines.append(f"| {name} | {count} | {_share(count, summary['truth_items'])} |")
    lines += [
        f"| **Total** | **{summary['truth_items']}** | **100%** |",
    ]
    if summary["scored_rows"] == 0:
        lines += [
            "",
            (
                "No row was successfully scored, so there is nothing to classify. "
                "The failed rows are named above rather than counted as absent."
            ),
        ]
    lines += [
        "",
        "### By cuisine",
        "",
        "| Cuisine | resolved | perceived | absent | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, bucket in summary["by_cuisine"].items():
        lines.append(
            f"| {name} | {bucket['resolved']} | {bucket['perceived']} | "
            f"{bucket['absent']} | {bucket['truth_items']} |"
        )
    lines += [
        "",
        "### By tier",
        "",
        "| Tier | resolved | perceived | absent | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, bucket in summary["by_tier"].items():
        lines.append(
            f"| {name} | {bucket['resolved']} | {bucket['perceived']} | "
            f"{bucket['absent']} | {bucket['truth_items']} |"
        )

    lines += [
        "",
        "### Absent foods",
        "",
    ]
    if summary["absent_foods"]:
        lines += ["| Food | Truth items |", "|---|---:|"]
        lines += [
            f"| `{row['food_id']}` | {row['count']} |"
            for row in summary["absent_foods"]
        ]
    else:
        lines.append("No scored truth item was absent.")
    return lines


def _comparison_lines(comparison: dict, report: dict) -> list[str]:
    baseline = report["baseline"]
    candidate = report["candidate"]
    guard = comparison["guard"]
    variants = comparison["prompt_variants"]

    lines = ["## Baseline → candidate", ""]
    if variants["same"]:
        lines += [
            (
                "Both artifacts declare prompt variant "
                f"{', '.join(variants['baseline'])}: this is a self-comparison, "
                "so any difference is run-to-run variation, not an effect of the "
                "prompt."
            ),
        ]
    else:
        lines += [
            (
                "Prompts differ: baseline "
                f"{', '.join(variants['baseline'])} vs candidate "
                f"{', '.join(variants['candidate'])}."
            ),
        ]

    lines += [
        "",
        "### Totals, each artifact on its own denominator",
        "",
        (
            "| Class | Baseline "
            f"({baseline['scored_rows']} scored rows) | Candidate "
            f"({candidate['scored_rows']} scored rows) |"
        ),
        "|---|---:|---:|",
    ]
    for name in CLASSES:
        lines.append(
            f"| {name} | {baseline['classes'][name]} | {candidate['classes'][name]} |"
        )
    if baseline["scored_rows"] != candidate["scored_rows"]:
        lines += [
            "",
            (
                "The two columns use different denominators and are not "
                "directly comparable; the flow table below covers only the rows "
                "both artifacts scored successfully."
            ),
        ]

    lines += [
        "",
        "### Denominator guard",
        "",
        (
            "Join key `(sample_id, food_id)`. "
            f"{guard['intersection_rows']} rows were successfully scored by both "
            "artifacts."
        ),
    ]
    if comparison["state"] == "same_rows":
        lines += [
            "",
            (
                "Both artifacts scored the same rows, so the flow table is a "
                "full-run comparison."
            ),
        ]
    else:
        lines += [
            "",
            (
                "The two artifacts did not score the same rows. The flow table is "
                "**intersection-only** and is not a full-run comparison."
            ),
            "",
            f"- Rows only in baseline: {_names(guard['only_in_baseline'])}.",
            f"- Rows only in candidate: {_names(guard['only_in_candidate'])}.",
            f"- Failed in baseline: {_names(guard['baseline_failed'])}.",
            f"- Failed in candidate: {_names(guard['candidate_failed'])}.",
            (
                "- Rows dropped from the baseline side: "
                f"{_names(guard['dropped_baseline_rows'])} "
                f"({guard['dropped_baseline_truth_items']} truth items)."
            ),
            (
                "- Rows dropped from the candidate side: "
                f"{_names(guard['dropped_candidate_rows'])} "
                f"({guard['dropped_candidate_truth_items']} truth items)."
            ),
            (
                "- Truth items present on one side of the join only: "
                f"baseline {guard['unpaired_baseline_truth_items']}, candidate "
                f"{guard['unpaired_candidate_truth_items']}."
            ),
        ]

    lines += [
        "",
        "### Flows (baseline → candidate"
        + (", intersection only)" if comparison["state"] != "same_rows" else ")"),
        "",
        "| Baseline ↓ / Candidate → | resolved | perceived | absent | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in CLASSES:
        row = comparison["flows"][name]
        lines.append(
            f"| {name} | {row['resolved']} | {row['perceived']} | "
            f"{row['absent']} | {comparison['baseline_totals'][name]} |"
        )
    totals = comparison["candidate_totals"]
    lines += [
        (
            f"| **Candidate total** | **{totals['resolved']}** | "
            f"**{totals['perceived']}** | **{totals['absent']}** | "
            f"**{sum(totals.values())}** |"
        ),
        "",
        "### Net change per class (intersection)",
        "",
        "| Class | Baseline | Candidate | Net |",
        "|---|---:|---:|---:|",
    ]
    for name in CLASSES:
        value = comparison["net"][name]
        net_cell = f"{value:+d}" if value else "0"
        lines.append(
            f"| {name} | {comparison['baseline_totals'][name]} | "
            f"{comparison['candidate_totals'][name]} | {net_cell} |"
        )
    return lines


def render_markdown(report: dict) -> str:
    baseline = report["baseline"]
    candidate = report["candidate"]
    if candidate is None:
        header = [
            "# Prediction comparison",
            "",
            (
                f"One artifact: baseline `{baseline['path']}` "
                f"(config {', '.join(baseline['configs'])}, prompt "
                f"{', '.join(baseline['prompt_variants'])})."
            ),
            (
                "Every truth item on a successfully scored row is classified "
                "once, in the order resolved → perceived → absent."
            ),
        ]
        lines = header + [""] + _summary_lines("Artifact", baseline)
    else:
        comparison = report["comparison"]
        header = [
            "# Prediction comparison",
            "",
            (
                f"Baseline `{baseline['path']}` (config "
                f"{', '.join(baseline['configs'])}, prompt "
                f"{', '.join(baseline['prompt_variants'])}) vs candidate "
                f"`{candidate['path']}` (config "
                f"{', '.join(candidate['configs'])}, prompt "
                f"{', '.join(candidate['prompt_variants'])})."
            ),
        ]
        lines = (
            header
            + [""]
            + _summary_lines("Baseline", baseline)
            + [""]
            + _summary_lines("Candidate", candidate)
            + [""]
            + _comparison_lines(comparison, report)
        )
    lines += ["", "## Definitions", "", report["caveat"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compare truth-item outcomes across prediction artifacts."
    )
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, default=None)
    ap.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = ap.parse_args(argv)

    try:
        baseline_rows = load_artifact(args.baseline)
        candidate_rows = (
            load_artifact(args.candidate) if args.candidate is not None else None
        )
    except ArtifactError as exc:
        print(exc, file=sys.stderr)
        return 2

    report = build_report(
        args.baseline, baseline_rows, args.candidate, candidate_rows
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
