# Status

> **Generated file — do not edit.** Produced by `python scripts/status.py`
> from the working tree, and checked in CI. It cannot quietly go stale the
> way a hand-written status section does.
> It does not certify external state such as device execution, Loom access,
> or email delivery.

## Is this ready to submit?

**The repository package is ready for technical review, not self-certified as submitted.** 4 of 8 rows have repository-verifiable working evidence. Device execution, Loom playback/access, and email delivery require operator confirmation; fine-tuning remains intentionally untrained and optional.

## Deliverables

| Deliverable | State | Evidence |
|---|---|---|
| Mobile app experience (not a web app) | 🚧 partial | Expo app present; CI typechecks and bundles it; current device execution must be confirmed outside the repository |
| Photo ingest (end-to-end flow) | ✅ working | API accepts an image; multipart photo-ingest path verified |
| Real vision provider | ✅ working | 80 recorded non-synthetic provider response(s) |
| Accuracy evaluation (metrics, test set, taxonomy) | ✅ working | harness runs offline; 80 golden samples (77 in the published scope, D23), 0/80 fixtures still synthetic |
| Fine-tuning | 🚧 partial | plan in `docs/finetuning-plan.md`; nothing trained (the brief marks implementation optional) |
| Technical write-up | ✅ working | README + 17 documents; 0 section group(s) still TODO |
| Loom walkthrough | ⬜ not started | no Loom share URL recorded in README |
| Email summary | 🚧 partial | kept outside the public repository; composition, sending, and receipt require operator confirmation |

## Measured

| | |
|---|---:|
| Locale packs | 3 (en_US, ja_JP, tr) |
| Canonical foods (committed) | 46 |
| Packs installed separately | tr (licence-restricted; `make pack`) |
| Golden-set samples | 80 (77 published) |

## Verification boundary

- `make test` and `make lint` verify the repository test and lint suites.
- `python eval/harness.py --check-regression` verifies the committed
  offline evaluation boundary.
- `make claims` verifies that the README's published numbers match the
  evaluation on this checkout.
- `python scripts/check_invariants.py` and `python scripts/status.py --check`
  verify architectural constraints and this generated file.
- Hosted CI proves those jobs ran on the committed revision. It does not
  prove current device execution, Loom access, email delivery, or a public
  backend deployment.
