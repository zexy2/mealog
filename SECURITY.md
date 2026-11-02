# Security policy

Mealog processes photos of food, which routinely contain faces, receipts, and
location metadata. Security reports are taken seriously at any size.

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** in this
repository (or <https://github.com/zexy2/mealog/security/advisories/new>).
Please do not open a public issue for anything exploitable.

Useful in a report:

- the request or input that triggers it, with `locale`, `sample_id` or raw text;
- what the service does instead of what it should do;
- whether a production deployment or only a local run is affected.

This is a personal project without a guaranteed response window. Reports are
acknowledged as soon as they are seen, and a fix that needs a disclosure gets a
advisory published alongside it.

## Scope

In scope:

- the HTTP edge in `server/src/app/` (parsing, limits, rate limiting, error
  mapping, `DELETE /v1/users/:id/data`);
- `server/src/pipeline/`: image metadata stripping, PII redaction, prompt-input
  sanitisation, closed-set nutrition;
- the loaders in `server/src/locales/` and `server/src/mealog/locales/`,
  including the licence gate in commercial mode;
- released dependency versions pinned in `server/package-lock.json`.

Out of scope:

- the accuracy of a resolved food or a portion estimate. That is an evaluation
  question, and the honest answer is in [docs/evaluation.md](docs/evaluation.md);
- the contents of installer scripts in `scripts/` when pointed at a source you
  supplied yourself;
- data that a deployment installs separately (`make pack`), which is governed by
  the terms in [docs/licensing.md](docs/licensing.md);
- missing security headers or TLS termination on the demo configuration; this
  repository is the application, not the deployment.

## What is already enforced in the build

| Control | Where | If it fails |
| --- | --- | --- |
| Secret scanning of every diff | `scripts/check_secrets.py` in CI | the `check` job fails |
| Architectural invariants, including that no model output reaches a nutrient field | `scripts/check_invariants.py` | the `check` job fails |
| Licence boundary (no restricted rows in the tree) | `scripts/check_licence_boundary.py` | the `check` job fails |
| Dependency review | `npm audit --omit=dev --audit-level=high` on the server workspace | the `check` job fails |
| Protected `main`, no bypass | repository ruleset | merge is blocked |

`npm audit` covers the **server workspace**, which is the part that parses
untrusted images and text. Mobile findings are reported by Dependabot but do not
fail the build: they are development-time and bundler-time packages, and the
only practical "fix" is a major Expo upgrade (see
[docs/security.md](docs/security.md#dependency-policy)).
