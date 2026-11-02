# AGENTS.md — rules for AI agents working in this repository

**This file is the contract. Read it fully before your first write.**

Multiple AI agents and one human (@zexy2, the owner and final arbiter) work in this
repo. GitHub is the only shared memory: if a decision, claim or result is not in a
commit, issue, PR or log entry, **it does not exist** and another agent will
overwrite it.

---

## 1. Startup ritual — mandatory, in this order

Before you write a single line, do all five:

1. Read this file and `docs/decisions.md`. Decisions D1–Dn are binding constraints,
   not suggestions.
2. `git fetch --all && git log --oneline -20` on `main`.
3. List **open issues** labelled `agent-claim` — these are active locks held by
   other agents. Do not touch files inside someone else's claimed scope.
4. List **open pull requests**. Another agent may already be doing your task.
5. Read the 10 most recent files in `log/` (filenames sort chronologically).

If your intended work overlaps an existing claim: comment on that issue and
negotiate. Do not start.

---

## 2. Identity — always declare who you are

Every agent has a stable handle, lowercase, e.g. `gumball`, `claude-code`, `cursor`.

- Branch: `agent/<handle>/<short-topic>` — e.g. `agent/gumball/retrieval-bm25`
- Commit trailer on **every** commit:
  ```
  Agent: <handle>
  Issue: #<number>
  ```
- Never commit under another agent's handle.

---

## 3. Claiming work — issues are locks

There is no other locking mechanism. Respect it or agents will clobber each other.

1. Open an issue using the **Agent work claim** template.
2. Label it `agent-claim`. State your handle, the **scope** (explicit list of files
   or directories you will modify), and your expected finish time.
3. Work only inside your declared scope. Need more? Edit the issue first.
4. Close the issue when the PR merges.

**Claim TTL: 12 hours.** A claim with no commit or comment for 12 hours is stale.
Any agent may label it `stale-claim`, comment saying it is taking over, and proceed.
Do not silently seize a live claim.

**Two agents can claim at the same moment.** Checking for open claims and opening
your own is not atomic, so after you open a claim, **list the claims again**. If an
overlapping claim exists with a *lower issue number*, it wins: comment on yours,
close it, and either pick different work or wait. Lowest number wins is arbitrary,
which is the point — it needs no negotiation.

**Your scope is enforced, not trusted.** `scripts/check_claim_scope.py` runs in CI
on every pull request: it reads the `## Scope` section of the issue you referenced
and fails the build if the PR touches anything outside it. Declare paths in
backticks, one per line, or the parser cannot see them. Widening the scope
mid-flight is fine — edit the issue first, then continue.

**Unclaimable without human sign-off:** `docs/decisions.md` (append-only, see §6),
`AGENTS.md`, `.github/workflows/`, and anything under `eval/golden/`. Golden-set
labels are ground truth; changing them changes every historical number.

---

## 4. Branch and PR discipline

- **Never commit directly to `main`.** Every change is a PR. `main` is protected
  by an active GitHub ruleset (id 21100839) that requires a pull request and the
  `check` status; its bypass list is empty, so there is no bypass. The
  `main-arrived-via-pull-request` job is defence in depth: if the ruleset is ever
  removed, a direct push turns `main` red and names the commit and its author.
- One issue → one branch → one PR. Keep PRs small enough to review in 10 minutes.
- Reference the claim issue in the PR body as `**Closes:** #<issue>`.
- Fill in the PR template completely. A PR that does not state its **eval impact**
  will not be merged.
- Rebase onto `main` before requesting merge. Resolve your own conflicts.
- **Respect ordering.** If an issue says *Blocked by #N*, do not start it until #N
  merges — even if it looks independent. Ordering in this repo usually exists
  because one change fixes an interface the other would be written against.
- **Generated files conflict cheaply.** `STATUS.md` is produced by
  `scripts/status.py`. If it conflicts, do not hand-merge it: take either side,
  re-run `make status`, and commit the result.
- **The whole of `docs/submission/` is exempt from claim scope** (`ALWAYS_ALLOWED`
  in `check_claim_scope.py`), which includes `STATUS.md` and `log/`; no claim
  needs to list them. Adding a test changes the generated status file: run `make status`
  and commit the result before pushing, or CI fails on a stale `STATUS.md` that
  has nothing to do with your change.

---

## 5. Hard rules — violating these is a revert, no discussion

1. **No force push. No history rewrite. No amending another agent's commit.**
2. **Do not delete or rename another agent's branch.**
3. **Do not revert another agent's merged decision.** Disagree in an issue and let
   the human decide.
4. **No secrets in the repo.** No API keys, no `.env`, no user photos. Fixtures only.
5. **Do not weaken a test or an invariant to make your change pass.** If an
   invariant is wrong, change it in a separate PR with its own justification.
6. **Do not add a dependency without a one-line justification in the PR body.**

---

## 6. Append-only artifacts

`docs/decisions.md` is **append-only**. Add at the bottom. Never edit or delete an
existing entry — supersede it with a new one that references the old by number. The
history of reasoning is the point, and a decision quietly rewritten is worse than a
decision reversed loudly.

**End every working session with a log entry**: a new file at
`log/YYYY-MM-DD-HHMM-<handle>-<topic>.md`. One file per session, never a shared
file — several agents appending to one log guarantees a merge conflict on every
pull request, and the log is the one conflict nobody resolves carefully.

Write the `Traps:` line as though the next agent is about to repeat your mistake,
because they are. That line has been the most valuable part of this log so far.

---

## 7. Merge gate

A PR merges only when all of these are green:

```
make test                                  # unit tests
make lint                                  # ruff
python eval/harness.py --check-regression  # no cuisine bucket got worse
python scripts/check_invariants.py         # architectural rules still hold
python scripts/status.py --check           # STATUS.md still matches reality
```

CI runs all five, plus `check_claim_scope.py` on pull requests.

**Verify dependency changes in a throwaway virtualenv, not your own.**
`python -m venv /tmp/x && /tmp/x/bin/pip install -e "server[dev]"`. Every
environment you already have is contaminated by what you installed yesterday;
this repository shipped two undeclared dependencies for a day because of exactly
that, with CI red the whole time.

**Read CI before claiming anything is green.** A guard you do not look at is not
a guard. If you changed pipeline behaviour, also paste the before/after
ablation rows into the PR body. **A number without a diff is not evidence.**

---

## 8. Handoff protocol

Stopping mid-task (out of context, blocked, timed out)? Before you go, comment on
your claim issue with:

```
HANDOFF
State:    <what works right now>
Done:     <what is finished and merged/pushed>
Next:     <the exact next step>
Traps:    <what bit you; what the next agent should not repeat>
Branch:   <branch name and last commit sha>
```

Then either keep the claim (if returning within TTL) or label it `stale-claim`
yourself so another agent can pick it up. Silent abandonment is the worst outcome.

---

## 9. Project invariants — do not break these

These come from `docs/decisions.md`. `scripts/check_invariants.py` enforces them
over the Python reference pipeline (`server/src/mealog/**/*.py`); it does not scan
the served TypeScript backend (`server/src/pipeline/`).

| Invariant | Why |
|---|---|
| Only `pipeline/nutrition.py` produces nutrient numbers | the anti-hallucination guarantee is architectural, not prompt-based |
| No locale name appears as a literal in `pipeline/` or `domain/` | a market is data; hardcoding one makes market N+1 a code change |
| Every locale pack declares a `license` | packs have different legal terms (TURKOMP is restricted) |
| Every golden sample has a matching fixture | `make eval` must run offline for anyone |
| Resolution returns a catalogue `food_id` or `ABSTAIN`, never free text | closed-set is what makes hallucination impossible |

The served TypeScript backend has behavioural tests for the same rules
(`server/test/pipeline.nutrition.test.ts`, `server/test/pipeline.resolve.test.ts`),
but no structural invariant checker: nothing equivalent to `check_invariants.py`
scans `server/src/pipeline/` for a second nutrient producer or a non-closed-set
resolver.

## 10. Bringing a new agent in

Whoever starts an agent on this repository gives it
[`onboarding-prompt.md`](onboarding-prompt.md) verbatim as its first
message. It is short on purpose. An agent that has not read this file will open a
pull request that fails the scope gate and will not understand why.

## 11. Where things live

| Looking for | Go to |
|---|---|
| Why something is the way it is | `docs/decisions.md` |
| How accuracy is measured | `docs/evaluation.md` |
| What was trained and what was not | `docs/finetuning-plan.md` |
| How to add a market | `scripts/build_locale_pack.py`, `locale_packs/` |
| What other agents did | `log/`, closed issues, merged PRs |
| What is done and what is not | `STATUS.md` (generated) |
| Current scores | `make eval` → `eval/reports/scorecard.md` |
