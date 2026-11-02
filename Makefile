PYTHON ?= $(shell if [ -f $(CURDIR)/server/.venv/bin/python ]; then echo "$(CURDIR)/server/.venv/bin/python"; elif which python3 >/dev/null 2>&1; then echo "python3"; else echo "python"; fi)

.PHONY: install eval eval-live eval-restricted record claims diagnose test lint invariants licence pack audit status check api db clean

install:
	cd server && $(PYTHON) -m pip install -e ".[dev]" -q

# Offline: replays recorded vision responses. No API key, no network.
eval:
	$(PYTHON) eval/harness.py --configs V0,V1,V2,V3 --out eval/reports/scorecard.md

# Live: calls the real vision provider and measures only. Requires GEMINI_API_KEY.
eval-live:
	$(PYTHON) eval/harness.py --configs V3 --live --out eval/reports/scorecard-live.md

# Rewrites eval/fixtures from live provider responses. Requires the fetched
# golden images (scripts/fetch_golden_images.py) and GEMINI_API_KEY.
record:
	$(PYTHON) scripts/record_golden_fixtures.py

# Full set, including the licence-restricted catalogue (install it with
# `make pack`). A local measurement: a clean clone cannot reproduce it, so it is
# not what the README publishes. See docs/evaluation.md.
eval-restricted:
	$(PYTHON) eval/harness.py --configs V0,V1,V2,V3 --include-restricted --out eval/reports/scorecard-restricted.md
	$(PYTHON) eval/retrieval_eval.py --include-restricted --out eval/reports/retrieval-restricted.md

# The README publishes numbers; this fails when they stop being the numbers the
# evaluation measures. Both sides of the contract, checked mechanically.
claims:
	$(PYTHON) scripts/check_readme_claims.py

# Where the identity errors come from. Regenerates the committed report; the
# check in `make check` fails when it no longer matches the fixtures.
diagnose:
	$(PYTHON) eval/identity_diagnosis.py --out docs/identity-diagnosis.md

test:
	cd server && $(PYTHON) -m pytest -q

lint:
	cd server && $(PYTHON) -m ruff check src tests

invariants:
	$(PYTHON) scripts/check_invariants.py

# The Turkish catalogue is installed from a licence-gated source; this fails
# if it ever returns to the tracked tree. See docs/licensing.md.
licence:
	$(PYTHON) scripts/check_licence_boundary.py

# Obtain the restricted Turkish catalogue into locale_packs/tr/.
pack:
	$(PYTHON) scripts/install_restricted_pack.py --source "$${TR_PACK_SOURCE:?set TR_PACK_SOURCE to a directory, zip, or URL}"

# Runtime dependencies only: the server workspace parses untrusted input, so a
# high advisory there fails the build. See docs/security.md section 8.
audit:
	cd server && npm audit --omit=dev --audit-level=high

status:
	$(PYTHON) scripts/status.py

# What CI runs. Run this before opening a PR (docs/submission/AGENTS.md §7).
check: lint test invariants licence
	$(PYTHON) scripts/status.py --check
	$(PYTHON) eval/harness.py --configs V0,V1,V2,V3 --check-regression
	$(PYTHON) scripts/check_readme_claims.py
	$(PYTHON) eval/identity_diagnosis.py --check

db:
	docker compose up -d db

# Delivered HTTP backend: Node.js/TypeScript NestJS. Python remains evaluation/reference tooling.
api:
	cd server && npm run build && npm start

clean:
	rm -rf eval/reports/*.md
