# Project tour

For a reviewer with ten minutes and this link. The claim the project makes is
narrow, so the tour is narrow too: **the system knows when it does not know, and
the repository can prove where that boundary is.**

Every section below points at something you can open, run, or read a number
from. Nothing here asks to be taken on trust.

---

## 1. The claim, in one paragraph

A photo or a messy sentence ("bi simit bi ayran") becomes **canonical foods from
a closed catalogue**, an **explicit portion range**, and **catalogue-derived
nutrition** — or it becomes a question, or an abstention. A language model is
never allowed to produce a calorie. The interesting engineering is not the happy
path; it is that `ask` and `abstain` are first-class, measurable outcomes, and
that every place they could be faked is guarded by a test or a build check.

Start with [README → The problem it solves](../README.md#the-problem-it-solves)
and [D1](decisions.md#d1--the-model-never-produces-a-nutrient-number).

---

## 2. Read these five things, in this order

| # | What | Why it matters | Time |
| --- | --- | --- | --- |
| 1 | [`docs/decisions.md`](decisions.md) | 25 decisions, each with the alternative rejected and the cost paid. Read D1, D2, D21, D22, D23, D24, D25. | 8 min |
| 2 | [`docs/evaluation.md`](evaluation.md) | What the numbers mean, what they do not, and the tier system behind them. | 6 min |
| 3 | [`docs/assumptions.md`](assumptions.md) | The claims checked before they were written down, including one that was wrong. | 5 min |
| 4 | [`docs/architecture.md`](architecture.md) | Topology and the seven grounded stages. | 4 min |
| 5 | [`docs/submission/STATUS.md`](submission/STATUS.md) | Generated, not written: what the tree can prove, and what it cannot. | 2 min |

If you read only one: the decision log, because it shows how the rest was
chosen rather than asserted.

---

## 3. Watch the boundary hold

Three things are worth seeing actually happen. Each is a command that produces
the evidence, not a claim about it.

**The model cannot reach a nutrient field.**

```sh
make invariants   # fails if any model output can become a nutrient number
```

**A locale that cannot be loaded says so, and nothing else breaks.**

```sh
curl -s -H 'Content-Type: application/json' \
  -d '{"idempotency_key":"tour","sample_id":"tr_0001","locale":"tr","config":"V3"}' \
  http://localhost:3000/v1/meals
# {"detail":"locale catalogue is not installed in this deployment","locale":"tr",...}
# while locale "en_US" keeps answering 200
```

`tr` is defined but not distributed: its rows are `restricted-noncommercial`
(D21). The repository ships the definition, installs the data with
`make pack`, and refuses to let the data back into Git. A guard you can watch
fail is worth more than a policy paragraph — after `make pack`, `cp` one
`locale_packs/tr/*.jsonl` out and back in, and run `make licence`.

**The evaluation refuses to flatter itself.**

```sh
make eval    # writes the scorecard: worst-cuisine MAPE and coverage
make claims  # fails if README's numbers differ from this checkout's results
make record  # the only command that rewrites eval/fixtures (D24)
```

The scorecard's honest headline is that grounded coverage is **9%** in the
configuration with the most safeguards, and that perception is the weak layer,
not retrieval. The published numbers are deliberately the ones a clean clone
reproduces: the licence-restricted Turkish catalogue is excluded and named
(D23). [README → Evidence snapshot](../README.md#evidence-snapshot) states the
same numbers, and `make claims` checks that it still does.

---

## 4. What I would defend in an interview

- **Trading hallucination for a visible miss.** D1 makes `E3` (invented food)
  structurally impossible at the cost of `E4` (a food outside the catalogue
  cannot be logged). The miss is visible to the user; the hallucination is not.
- **A licence boundary that is a build check.** The Turkish data drove the
  project's deepest evaluations, and committing it under an MIT grant said two
  contradictory things. D21 moves it behind an install step, and `make licence`
  fails if it returns. The check lives in the build because a deleted blob stays
  reachable in history.
- **Metrics chosen to be unflattering.** Worst-cuisine MAPE rather than the mean,
  FP rate rather than precision, coverage printed next to every score. A
  metric you cannot lose on is not a metric.
- **Three current packs, not one.** Two implementations prove a seam; three
  prove the abstraction survives contact with a second language, a different
  script, and a different licence.

---

## 5. What is not finished, stated plainly

- **Live-provider accuracy has dated observations, not a measurement.** The
  scorecard replays fixtures recorded with a different Gemini model from the
  live adapter default; two live runs on 2026-11-02 answered 4/74 and 3/12
  without deferring.
- **Perception, not retrieval, is the ceiling.** Retrieval is 30/30
  Recall@1 in the published (redistributable) scope; identity over photographed
  plates is 0.38 Item F1, and most of that is a corrected annotation, not a
  better model (D25). The [diagnosis](identity-diagnosis.md) is generated from
  the fixtures: 177 of 331 truth items were never named by the model, so a
  perfect resolver would still cap at 0.64.
- **Mobile advisories are open** and need an Expo-aware upgrade, not a lockfile
  rewrite ([why](security.md#8-dependency-policy)).
- **Demo mode resolves names locally** from a small fixed demo catalogue
  labelled `DEMO`; the live client never does (D22).
- **Correction telemetry is a process-local prototype**, and no fine-tuning run
  exists. The fine-tuning plan is a plan.
- **The Turkish demo needs one install step** (`TR_PACK_SOURCE=… make pack`) and 164 Python /
  73 TypeScript tests skip, by name, without it.

[README → Remaining limitations](../README.md#remaining-limitations) keeps the
same list. If these two ever disagree, that is a bug.

---

## 6. If you only have two minutes

1. [README](../README.md) headline and evidence snapshot.
2. `make invariants && make licence && make eval | tail -20 && make claims`.
3. This section, again: *9% grounded coverage, perception is the ceiling, and
   the build will not let me pretend otherwise.*
