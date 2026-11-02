#!/usr/bin/env python3
"""Fail when the README's evidence snapshot and the evaluation disagree.

The README publishes the project's least flattering numbers, which only means
something if they are true. Hand-typed prose has no such guarantee: changing the
harness or the golden set left the paragraph claiming the old result while CI
stayed green. This check makes the paragraph and the measured summary two halves
of one contract.

It also enforces the property that makes the numbers worth quoting: they must be
what a **clean clone** gets. Both evaluations run with the published scope
(redistributable locale packs only), so a machine with the licence-restricted
catalogue installed cannot quietly publish a different snapshot, and a claim
about rows that were excluded is checked against the manifest rather than taken
on trust.

    python scripts/check_readme_claims.py
    python scripts/check_readme_claims.py --readme /tmp/candidate.md
    python scripts/check_readme_claims.py --from /tmp/summaries   # no eval run

Exit code 0 means the README states what the evaluation measured. Exit code 1
means it does not, and the output is the text to write instead.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
MANIFEST = ROOT / "eval" / "golden" / "manifest.jsonl"
VARIANTS = ROOT / "eval" / "golden" / "query_variants.jsonl"

#: Each pattern is anchored on wording that carries meaning, not only on a
#: number, so a reworded claim fails here instead of drifting unchecked.
PATTERNS = {
    # "commit" was the wrong word: every one of these rows routes to review,
    # never to auto_accept, so the claim now names what actually happens.
    "commit": re.compile(
        r"\*\*(?P<commit>\d+)/(?P<rows>\d+)\s+proposed\s+for\s+review,\s+"
        r"(?P<ask>\d+)/(?P<rows_again>\d+)\s+ask:\*\*"
    ),
    "coverage": re.compile(
        r"(?P<coverage>\d+)%\s+grounded\s+coverage\s+in\s+the\s+V3\s+configuration"
    ),
    "identity": re.compile(
        r"\*\*Item\s+F1\s+(?P<f1>\d+\.\d+);\s+FP\s+rate\s+(?P<fp>\d+\.\d+)%:\*\*"
    ),
    "calorie": re.compile(
        r"\*\*Calorie\s+MAPE\s+(?P<mape>\d+\.\d+)%\s+on\s+"
        r"(?P<scored>\d+)/(?P<eligible>\d+)\s+rows:\*\*"
    ),
    "retrieval": re.compile(
        r"(?P<variants>\d+)\s+variants,\s*"
        r"(?P<recall_hit>\d+)/(?P<recall_n>\d+)\s+positive\s+Recall@1,\s+"
        r"MRR\s+(?P<mrr>\d+\.\d+),\s+"
        r"(?P<false_accepts>\d+)/(?P<absent>\d+)\s+absent-food\s+false\s+accepts"
    ),
    "excluded": re.compile(
        r"adds\s+(?P<golden>\d+)\s+golden\s+rows\s+and\s+"
        r"(?P<variants>\d+)\s+retrieval\s+variants"
    ),
}

LABELS = {
    "commit.commit": "V3 samples proposed for review",
    "commit.rows": "golden rows",
    "commit.ask": "V3 samples that asked a question",
    "commit.rows_again": "golden rows (second mention)",
    "coverage.coverage": "V3 coverage percent",
    "identity.f1": "Item F1",
    "identity.fp": "false-positive rate",
    "calorie.mape": "calorie MAPE",
    "calorie.scored": "scored calorie rows",
    "calorie.eligible": "calorie-eligible rows",
    "retrieval.variants": "retrieval variants",
    "retrieval.recall_hit": "Recall@1 hits",
    "retrieval.recall_n": "positive retrieval inputs",
    "retrieval.mrr": "MRR",
    "retrieval.false_accepts": "absent-food false accepts",
    "retrieval.absent": "absent-food negatives",
    "excluded.golden": "golden rows excluded by licence",
    "excluded.variants": "retrieval variants excluded by licence",
}

#: The section of the README this check owns. A claim outside it is not checked,
#: so the boundary has to be explicit rather than "search the whole file".
SNAPSHOT_START = "## Evidence snapshot"
SNAPSHOT_END = "## Measured failures"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_eval(python: str, script: str, summary: Path, *extra: str) -> dict:
    """Run one evaluation with the published scope and read its summary."""
    command = [python, str(ROOT / script), *extra, "--summary-json", str(summary)]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-12:]
        raise SystemExit(
            f"{script} failed, so the README cannot be checked:\n"
            + "\n".join(f"  {line}" for line in tail)
        )
    return _read_json(summary)


def load_summaries(python: str, from_dir: Path | None = None) -> tuple[dict, dict]:
    """The measured numbers, either recomputed or read from a fixture directory.

    Deliberately no `--include-restricted`: the published snapshot is the one a
    clean clone reproduces, so the checker that guards it must use that scope.
    """
    if from_dir is not None:
        return _read_json(from_dir / "harness.json"), _read_json(from_dir / "retrieval.json")
    with tempfile.TemporaryDirectory(prefix="mealog-claims-") as tmp:
        harness = _run_eval(
            python, "eval/harness.py", Path(tmp) / "harness.json",
            "--configs", "V0,V1,V2,V3",
        )
        retrieval = _run_eval(
            python, "eval/retrieval_eval.py", Path(tmp) / "retrieval.json",
        )
    return harness, retrieval


def snapshot_text(readme: str) -> str:
    start = readme.find(SNAPSHOT_START)
    end = readme.find(SNAPSHOT_END, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        raise SystemExit(
            f"README no longer has a '{SNAPSHOT_START}' section ending at "
            f"'{SNAPSHOT_END}'; the published claims cannot be located. Restore "
            "the headings or update this checker in the same change."
        )
    return readme[start:end]


def parse_snapshot(text: str) -> tuple[dict[str, str], list[str]]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for name, pattern in PATTERNS.items():
        match = pattern.search(text)
        if match is None:
            missing.append(
                f"the README no longer states the {name} claim in a form this "
                "check understands"
            )
            continue
        found.update({f"{name}.{key}": value for key, value in match.groupdict().items()})
    return found, missing


def _dec(value: object, places: int) -> str:
    return f"{float(value):.{places}f}"


def manifest_counts(excluded_locales: list[str]) -> dict[str, int]:
    """How much evidence the licence-restricted locales contribute.

    Counted from the manifests, which do ship, so the README can name the size
    of what is excluded without installing the catalogue that is excluded.
    """
    excluded = set(excluded_locales)

    def count(path: Path) -> int:
        return sum(
            1 for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["locale"] in excluded
        )

    return {"golden_rows": count(MANIFEST), "variants": count(VARIANTS)}


def expected_tokens(harness: dict, retrieval: dict, excluded: dict[str, int]) -> dict[str, str]:
    v3 = harness["configs"]["V3"]
    rows = str(v3["rows"])
    return {
        "commit.commit": str(v3["committed"]),
        "commit.rows": rows,
        "commit.ask": str(v3["asked"]),
        "commit.rows_again": rows,
        "coverage.coverage": _dec(v3["coverage_pct"], 0),
        "identity.f1": _dec(v3["item_f1"], 2),
        "identity.fp": _dec(v3["fp_rate_pct"], 1),
        "calorie.mape": _dec(v3["mape_pct"], 1),
        "calorie.scored": str(v3["calorie_scored"]),
        "calorie.eligible": str(v3["calorie_eligible"]),
        "retrieval.variants": str(retrieval["variants"]),
        "retrieval.recall_hit": str(retrieval["recall_at_1_hits"]),
        "retrieval.recall_n": str(retrieval["positive_inputs"]),
        "retrieval.mrr": _dec(retrieval["mrr"], 3),
        "retrieval.false_accepts": str(retrieval["false_accepts_blended"]),
        "retrieval.absent": str(retrieval["absent_negative_cases"]),
        "excluded.golden": str(excluded["golden_rows"]),
        "excluded.variants": str(excluded["variants"]),
    }


def summary_problems(harness: dict, retrieval: dict) -> list[str]:
    """Reject a measurement that contradicts itself before comparing prose.

    Without this, a broken summary and a README edited to match it would agree
    with each other and the check would pass.
    """
    problems: list[str] = []
    for name, cfg in harness["configs"].items():
        if cfg["committed"] < 0 or cfg["asked"] < 0:
            problems.append(f"{name}: negative sample count")
        if cfg["committed"] + cfg["asked"] > cfg["rows"]:
            problems.append(
                f"{name}: {cfg['committed']} committed + {cfg['asked']} asked "
                f"exceeds {cfg['rows']} rows"
            )
        if cfg["calorie_scored"] > cfg["calorie_eligible"]:
            problems.append(
                f"{name}: {cfg['calorie_scored']} scored calorie rows but only "
                f"{cfg['calorie_eligible']} eligible"
            )
    if retrieval["recall_at_1_hits"] > retrieval["positive_inputs"]:
        problems.append("retrieval: Recall@1 hits exceed positive inputs")
    if retrieval["false_accepts_blended"] > retrieval["absent_negative_cases"]:
        problems.append("retrieval: more false accepts than absent-food negatives")
    return problems


def render_expected(measured: dict[str, str]) -> str:
    commit = (
        f"- **{measured['commit.commit']}/{measured['commit.rows']} commit, "
        f"{measured['commit.ask']}/{measured['commit.rows']} ask:** "
        f"{measured['coverage.coverage']}% grounded coverage in the V3 configuration."
    )
    identity = (
        f"- **Item F1 {measured['identity.f1']}; "
        f"FP rate {measured['identity.fp']}%:**"
    )
    calorie = (
        f"- **Calorie MAPE {measured['calorie.mape']}% on "
        f"{measured['calorie.scored']}/{measured['calorie.eligible']} rows:**"
    )
    retrieval = (
        f"{measured['retrieval.variants']} variants, "
        f"{measured['retrieval.recall_hit']}/{measured['retrieval.recall_n']} "
        f"positive Recall@1, MRR {measured['retrieval.mrr']}, "
        f"{measured['retrieval.false_accepts']}/{measured['retrieval.absent']} "
        "absent-food false accepts"
    )
    excluded = (
        f"adds {measured['excluded.golden']} golden rows and "
        f"{measured['excluded.variants']} retrieval variants"
    )
    return f"{commit}\n{identity}\n{calorie}\n{retrieval}\n{excluded}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default=str(README))
    parser.add_argument(
        "--from",
        dest="from_dir",
        default=None,
        help="read harness.json and retrieval.json from this directory instead of running the evaluations",
    )
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args(argv)

    harness, retrieval = load_summaries(args.python, Path(args.from_dir) if args.from_dir else None)

    problems = summary_problems(harness, retrieval)
    if problems:
        print("the evaluation summary is internally inconsistent, so nothing can be checked:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    excluded_counts = manifest_counts(harness["scope"]["excluded_locales"])
    measured = expected_tokens(harness, retrieval, excluded_counts)

    try:
        text = Path(args.readme).read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read {args.readme}: {error}")
        return 1

    stated, missing = parse_snapshot(snapshot_text(text))
    mismatches = [
        (key, stated[key], measured[key])
        for key in measured
        if key in stated and stated[key] != measured[key]
    ]

    if missing or mismatches:
        print(f"{args.readme} disagrees with the evaluation:")
        for key, actual, wanted in mismatches:
            print(f"  - {LABELS.get(key, key)}: README says '{actual}', measured '{wanted}'")
        for problem in missing:
            print(f"  - {problem}")
        print("\nWrite this:\n")
        print(render_expected(measured))
        return 1

    scope = harness["scope"]
    print(
        "README evidence snapshot matches the evaluation: "
        f"{harness['configs']['V3']['rows']} rows over "
        f"{', '.join(scope['included_locales']) or '(none)'}"
        + (f" (excluded: {', '.join(scope['excluded_locales'])})"
           if scope["excluded_locales"] else "")
        + f"; {retrieval['variants']} retrieval variants."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
