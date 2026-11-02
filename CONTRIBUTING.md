# Contributing

Thanks for looking. Mealog is small, opinionated, and its claims are meant to be
checkable, so contribution guidance follows the same pattern.

## Before you start

- **Bug reports** use the [issue form](.github/ISSUE_TEMPLATE/bug_report.md).
  Include the locale and `sample_id` or text; a `503` for `locale: "tr"` on a
  clean clone is expected, not a bug.
- **Anything exploitable** goes through [SECURITY.md](SECURITY.md), not a
  public issue.
- **Questions about the evaluation or the accuracy numbers** belong in
  [Discussions](https://github.com/zexy2/mealog/discussions).

## How a change lands

`main` is protected with no bypass. A change arrives as a pull request that
passes the required `check` job:

| Gate | Command |
| --- | --- |
| Python lint and tests | `make lint`, `make test` (pytest) |
| Architectural invariants | `make invariants` |
| Licence boundary | `make licence` |
| Generated status is current | `make status` then commit |
| Eval regression guard | `make eval` |
| TypeScript build, lint, tests | `cd server && npm run build && npm run lint && npm run test` (`nest build`) |
| Runtime dependency audit | `make audit` (server only; see `docs/security.md` §8) |

`make check` runs the Python half. Run both halves before opening a pull
request.

## Claiming work

Every change starts from an issue whose body has a `## Scope` section listing
the paths it will touch, one backticked path per line. The pull request body
must contain exactly one `**Closes:** #N`. CI fails otherwise: the scope is
enforced against the diff, not just described. The full convention, including
how to widen a scope mid-flight, is in
[docs/submission/AGENTS.md](docs/submission/AGENTS.md).

## Dependency updates

Dependabot opens grouped pull requests weekly. They do not need a claim issue,
and they are not merged because they are green — they are merged when green
*and* the change is one a person would have made. `docs/security.md` §8 says
which advisories are gated (server runtime) and which are reported (mobile
tooling, build tools); the review rule is there too: a red run only proves the
update is wrong when it fails for a reason the update caused. A failing claim
check hides the real result, so rebase first and read the logs.

## Conventions that matter here

- **A locale is data, not code (D2).** Adding a market means adding a pack
  directory and an eval, not a branch in the pipeline. Nothing in `server/src`
  may reference a locale by name.
- **The model never produces a nutrient number (D1).** Vision output is
  observations; nutrition comes from a catalogue `food_id` or the result is
  `ABSTAIN`. A change that lets a model number reach `nutrients` fails
  `make invariants`.
- **Restricted data is installed, not committed (D21).** Do not commit
  `locale_packs/tr/foods.jsonl` and friends; `make licence` fails if you do,
  and it is part of `check`.
- **Generated files are generated.** `docs/submission/STATUS.md` comes from
  `make status`; edit the probe, not the output.
- **Tests skip by name when data is absent.** A test that needs the restricted
  catalogue uses `requires_pack("tr")` (Python) or `pack_installed("tr")`
  (TypeScript) so a clean clone explains itself instead of failing.

## Licence of contributions

By opening a pull request you agree that your contribution is licensed under
the repository's MIT licence for code and documentation. Do not contribute
nutrition data you are not entitled to redistribute; see
[docs/licensing.md](docs/licensing.md).
