#!/usr/bin/env python3
"""Retrieval-only evaluation.

Measured separately from the end-to-end harness on purpose. The vision fixtures
are still seeded placeholders, so an end-to-end MAPE would be theatre — but
"does this surface form reach the right canonical food" is answerable today, and
it is the question this stage actually owns.

    python eval/retrieval_eval.py
    python eval/retrieval_eval.py --out eval/reports/retrieval.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server" / "src"))

from mealog.domain.models import Candidate            # noqa: E402
from mealog.locales.loader import LocalePack, PackUnavailableError, load  # noqa: E402
from mealog.pipeline.normalize import fold            # noqa: E402
from mealog.pipeline.resolve import resolve           # noqa: E402
from mealog.pipeline.retrieval import search          # noqa: E402

sys.path.insert(0, str(REPO / "eval"))
from locale_scope import evidence_scope, exclusion_note  # noqa: E402

VARIANTS = REPO / "eval" / "golden" / "query_variants.jsonl"


def variant_rows() -> list[dict]:
    """Read the variant set fresh so tests and reports see the same rows."""
    return [json.loads(line) for line in VARIANTS.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def scoped_rows(
    include_restricted: bool = False,
) -> tuple[list[dict], list[str], list[str], dict[str, str]]:
    """Rows this run may score, plus the locales it deliberately leaves out.

    Two different reasons are kept apart because they mean different things: a
    licence decision (the repository cannot publish this market) and a broken
    or missing installation (`--include-restricted` was asked for but the pack
    is not there). Collapsing them would let the second hide as the first.
    """
    rows = variant_rows()
    included, excluded = evidence_scope({row["locale"] for row in rows}, include_restricted)
    reasons = {
        locale: "licence-restricted catalogue; install with `make pack` and pass"
                " --include-restricted to measure it locally"
        for locale in excluded
    }

    # A pack can be in scope but unreadable on this machine; drop it loudly
    # rather than raising halfway through a run.
    usable = []
    for locale in included:
        try:
            load(locale)
        except PackUnavailableError:
            reasons[locale] = "catalogue not installed in this deployment"
            excluded.append(locale)
        else:
            usable.append(locale)
    return ([row for row in rows if row["locale"] in usable], usable,
            sorted(excluded), reasons)


def is_positive(row: dict) -> bool:
    """Only ordinary expected IDs contribute to recall.

    A confusion row names the food we must surface to explain a trap, not the
    food the user actually meant. Counting it as a positive would reward the
    wrong-match behaviour this evaluation exists to catch.
    """
    return row.get("role", "positive") == "positive" and row.get("expected_food_id") is not None


def retrieval_query(row: dict, pack: LocalePack) -> str:
    """Return text at retrieval's input boundary.

    Quantity words belong to the existing normalization boundary. Variants keep
    the full user input in ``query`` and may record the already-separated
    ``retrieval_query`` so this retrieval-only test does not pretend retrieval
    parses portions itself.
    """
    return fold(row.get("retrieval_query", row["query"]), pack)


def baseline_search(query: str, pack: LocalePack, k: int = 5) -> list[Candidate]:
    """The original day-0 implementation, kept here purely as the comparison row.

    Alias containment plus Jaccard token overlap. Preserved verbatim so the
    "before" column is the real previous behaviour and not a strawman.
    """
    q_tokens = set(query.split())
    scored: dict[str, float] = {}

    for food_id, aliases in pack.aliases.items():
        for alias in aliases:
            a = fold(alias, pack)
            if a == query:
                scored[food_id] = max(scored.get(food_id, 0.0), 1.0)
            elif a in query or query in a:
                scored[food_id] = max(scored.get(food_id, 0.0), 0.75)

    for food_id, food in pack.foods.items():
        name_tokens = set(fold(food.name, pack).split())
        if not name_tokens:
            continue
        overlap = len(q_tokens & name_tokens) / len(q_tokens | name_tokens)
        if overlap > 0:
            scored[food_id] = max(scored.get(food_id, 0.0), overlap)

    ranked = sorted(scored.items(), key=lambda kv: -kv[1])[:k]
    return [Candidate(food_id=fid, name=pack.foods[fid].name, score=round(s, 3))
            for fid, s in ranked if fid in pack.foods]


class Tally:
    def __init__(self) -> None:
        self.n = self.hit1 = self.hit5 = self.accepted = 0
        self.rr = 0.0

    def add(self, expected: str, candidates: list[Candidate], query: str) -> None:
        ids = [c.food_id for c in candidates]
        self.n += 1
        if ids[:1] == [expected]:
            self.hit1 += 1
            # Ranking first is not the same as being trusted. `resolve.py` still
            # has to clear its accept threshold, and a correctly-ranked match
            # that lands below it becomes a suggestion rather than a silent log.
            # Reporting only Recall@1 hides that gap — it hid it once already.
            r = resolve(query, candidates, allow_abstain=True)
            if not r.abstained and r.food_id == expected:
                self.accepted += 1
        if expected in ids:
            self.hit5 += 1
            self.rr += 1.0 / (ids.index(expected) + 1)

    def pct(self, v: int) -> float:
        return v / self.n * 100 if self.n else 0.0

    @property
    def r1(self) -> float: return self.pct(self.hit1)
    @property
    def acc(self) -> float: return self.pct(self.accepted)
    @property
    def r5(self) -> float: return self.pct(self.hit5)
    @property
    def mrr(self) -> float: return self.rr / self.n if self.n else 0.0


def run(impl, rows: list[dict]) -> tuple[Tally, dict[str, Tally], dict[str, Tally], list[str]]:
    overall = Tally()
    by_cuisine: dict[str, Tally] = defaultdict(Tally)
    by_kind: dict[str, Tally] = defaultdict(Tally)
    misses: list[str] = []

    for row in rows:
        if not is_positive(row):
            continue  # absent/confusion rows have separate negative checks
        pack = load(row["locale"])
        query = retrieval_query(row, pack)
        cands = impl(query, pack)

        for t in (overall, by_cuisine[pack.cuisine_bucket], by_kind[row["kind"]]):
            t.add(row["expected_food_id"], cands, query)

        if not cands or cands[0].food_id != row["expected_food_id"]:
            got = cands[0].food_id if cands else "(nothing)"
            misses.append(f"{row['locale']:6} '{row['query']}' -> {got} "
                          f"(want {row['expected_food_id']}, kind={row['kind']})")

    return overall, dict(by_cuisine), dict(by_kind), misses


def false_accepts(impl, rows: list[dict]) -> tuple[int, int, list[str]]:
    """How often food we do not carry gets *accepted* anyway.

    This is the counterweight to recall and the reason recall alone is not a
    good enough target. Fuzzy matching buys recall by making everything look a
    little similar to something; if that turns an honest abstention into a
    confident wrong answer, the trade was bad. Closed-set resolution makes a
    hallucinated *identifier* impossible — it does not make a wrong *match*
    impossible, and this is where that shows up.
    """
    total, bad, detail = 0, 0, []
    for row in rows:
        if row.get("expected_food_id") is not None:
            continue
        pack = load(row["locale"])
        query = retrieval_query(row, pack)
        r = resolve(query, impl(query, pack), allow_abstain=True)
        total += 1
        forbidden = set(row.get("forbidden_food_ids", []))
        if not r.abstained or r.food_id in forbidden:
            bad += 1
            detail.append(f"{row['locale']:6} '{row['query']}' -> accepted "
                          f"{r.food_id} (conf {r.confidence}; forbidden={sorted(forbidden)})")
    return bad, total, detail


def confusion_behaviour_ok(rows: list[dict]) -> list[str]:
    """A documented trap must surface the confusable food AND still abstain.

    Getting the right answer for the wrong reason (returning nothing) counts as
    a failure here — that distinction is the whole point of `negative_alias`.
    """
    problems = []
    for row in rows:
        if row.get("role") != "confusion":
            continue
        pack = load(row["locale"])
        query = retrieval_query(row, pack)
        cands = search(query, pack)
        r = resolve(query, cands, allow_abstain=True)
        ids = [c.food_id for c in cands]
        expected = row.get("confusable_food_id", row.get("expected_food_id"))
        if expected not in ids:
            problems.append(f"'{row['query']}': confusable food not surfaced")
        elif not r.abstained:
            problems.append(f"'{row['query']}': accepted instead of asking")
    return problems


def measure(rows: list[dict]) -> dict:
    """Run both implementations once; rendering and JSON share the result."""
    base, base_cu, base_kind, base_miss = run(baseline_search, rows)
    new, new_cu, new_kind, new_miss = run(search, rows)
    base_bad, absent_n, base_detail = false_accepts(baseline_search, rows)
    new_bad, _, new_detail = false_accepts(search, rows)
    positive_n = sum(is_positive(row) for row in rows)
    return {
        "rows": len(rows),
        "positive": positive_n,
        "negative": len(rows) - positive_n,
        "confusion": sum(1 for row in rows if row.get("role") == "confusion"),
        "base": base, "new": new,
        "base_cu": base_cu, "new_cu": new_cu,
        "base_kind": base_kind, "new_kind": new_kind,
        "base_miss": base_miss, "new_miss": new_miss,
        "base_bad": base_bad, "new_bad": new_bad, "absent_n": absent_n,
        "base_detail": base_detail, "new_detail": new_detail,
        "confusion_problems": confusion_behaviour_ok(rows),
    }


def summary(data: dict, included: list[str], excluded: list[str]) -> dict:
    """The numbers the README quotes, in a form a script can compare."""
    return {
        "generator": "eval/retrieval_eval.py",
        "scope": {"included_locales": included, "excluded_locales": excluded},
        "variants": data["rows"],
        "positive_inputs": data["positive"],
        "negative_cases": data["negative"],
        "confusion_cases": data["confusion"],
        "recall_at_1_hits": data["new"].hit1,
        "recall_at_1_pct": round(data["new"].r1, 1),
        "recall_at_5_pct": round(data["new"].r5, 1),
        "mrr": round(data["new"].mrr, 3),
        "accept_at_1_pct": round(data["new"].acc, 1),
        "absent_negative_cases": data["absent_n"],
        "false_accepts_blended": data["new_bad"],
        "false_accepts_baseline": data["base_bad"],
    }


def report(
    data: dict,
    included: list[str],
    excluded: list[str],
    reasons: dict[str, str],
) -> str:
    base, new = data["base"], data["new"]
    base_cu, new_cu = data["base_cu"], data["new_cu"]
    base_kind, new_kind = data["base_kind"], data["new_kind"]

    L = ["# Retrieval scorecard", "",
         (f"{data['rows']} query variants ({data['positive']} positive inputs, "
          f"{data['negative']} negative/confusion cases) over "
          f"{len(included)} locale pack(s): {', '.join(included) or '(none)'}. "
          "Measured independently of the"),
         "vision stage — see the header of `eval/retrieval_eval.py` for why."]
    if excluded:
        L += ["",
              "> **Excluded from every denominator below:** "
              + "; ".join(f"`{locale}` — {reasons.get(locale, 'out of scope')}"
                          for locale in excluded)
              + "."]
    L += ["", "## Overall", "",
          "| Implementation | Recall@1 | Recall@5 | MRR | Accept@1 |",
          "|---|---:|---:|---:|---:|",
          f"| baseline (token overlap) | {base.r1:.1f}% | {base.r5:.1f}% | {base.mrr:.3f} | {base.acc:.1f}% |",
          f"| **coverage, word + char n-gram** | **{new.r1:.1f}%** | **{new.r5:.1f}%** | **{new.mrr:.3f}** | **{new.acc:.1f}%** |",
          "",
          "*Recall@1* = correct food ranked first. *Accept@1* = ranked first **and**",
          "confident enough for `resolve.py` to log it without asking. The gap between",
          "the two is the set of meals that become a one-tap suggestion instead of a",
          "silent entry — by design, not by accident.",
          "", "## Per cuisine", "",
          "| Cuisine | n | Recall@1 before | after | Δ | Accept@1 |",
          "|---|---:|---:|---:|---:|---:|"]

    for cuisine in sorted(new_cu):
        b, a = base_cu.get(cuisine, Tally()), new_cu[cuisine]
        L.append(f"| {cuisine} | {a.n} | {b.r1:.1f}% | {a.r1:.1f}% | "
                 f"{a.r1 - b.r1:+.1f} | {a.acc:.1f}% |")

    L += ["", "## Per query kind", "",
          "| Kind | n | Recall@1 before | after | Recall@5 before | after | MRR before | after |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for kind in sorted(new_kind, key=lambda k: -(new_kind[k].r1 - base_kind.get(k, Tally()).r1)):
        b, a = base_kind.get(kind, Tally()), new_kind[kind]
        L.append(f"| {kind} | {a.n} | {b.r1:.1f}% | {a.r1:.1f}% | "
                 f"{b.r5:.1f}% | {a.r5:.1f}% | {b.mrr:.3f} | {a.mrr:.3f} |")

    L += ["", "## Known-confusion behaviour", "",
          "A documented trap must surface the confusable food *and* still abstain,",
          "so the user gets a targeted question instead of a silent regional mismatch.",
          ""]
    if data["confusion"] == 0:
        L += ["— no confusion cases in this scope; they live in the excluded locale(s)."]
    elif not data["confusion_problems"]:
        L += ["✅ correct for all confusion cases"]
    else:
        L += [f"❌ {p}" for p in data["confusion_problems"]]

    absent_n, new_bad, base_bad = data["absent_n"], data["new_bad"], data["base_bad"]
    rate = (lambda bad: bad / absent_n * 100) if absent_n else (lambda bad: 0.0)
    L += ["", "## False accepts (the counterweight to recall)", "",
          f"{absent_n} negative queries for food that is deliberately **not** a valid match.",
          "Correct behaviour is to abstain. Recall on its own is a metric you can",
          "cheat by matching more loosely, so it is only meaningful read next to this.",
          "",
          "| Implementation | False accepts | Rate |",
          "|---|---:|---:|",
          f"| baseline | {base_bad}/{absent_n} | {rate(base_bad):.1f}% |",
          f"| **blended** | **{new_bad}/{absent_n}** | **{rate(new_bad):.1f}%** |",
          "",
          f"Negative cases held: **{data['negative']}**. Confusion rows must surface the",
          "documented wrong neighbour and still abstain; absent rows must not accept",
          "their nearest catalogue item."]
    if data["new_detail"]:
        L += ["", "```"] + data["new_detail"] + ["```"]

    if data["new_miss"]:
        L += ["", f"## Remaining Recall@1 misses ({len(data['new_miss'])})", "", "```"]
        L += data["new_miss"] + ["```"]

    L += ["", "---", "",
          "> **Read the headline number with suspicion.** This branch evaluates the",
          "> current catalogue. The variants show whether messy surface forms reach",
          "> the closed set; they do not establish accuracy on a larger catalogue,",
          "> where near-neighbour foods compete. Re-run after catalogue growth."]

    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
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

    rows, included, excluded, reasons = scoped_rows(args.include_restricted)
    print(exclusion_note(included, excluded))
    data = measure(rows)
    text = report(data, included, excluded, reasons)

    if args.summary_json:
        path = Path(args.summary_json)
        if not path.is_absolute():
            path = REPO / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(summary(data, included, excluded), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {args.summary_json}")

    if args.out:
        (REPO / args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
