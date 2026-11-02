"""Enforce that a pull request stays inside the scope its claim issue declared.

docs/submission/AGENTS.md section 3 makes issues the only lock between agents. A lock nobody
checks is a convention, and conventions lose to a model in a hurry — so this
turns the declared scope into a build failure.

Runs in CI on pull_request events: reads the claim issue linked from the PR
body, parses its `## Scope` section, and fails if the PR touches anything
outside it.

    python scripts/check_claim_scope.py            # GitHub Actions
    python scripts/check_claim_scope.py --pr 12    # locally, needs GITHUB_TOKEN
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

API = "https://api.github.com"

#: Process files every agent is expected to touch. Requiring them in each claim
#: would be noise, and forgetting them is not the failure this guards against.
# Every agent gets its own session file. The old AGENT_LOG.md is only a pointer
# and should not be silently changed outside a declared scope.
ALWAYS_ALLOWED = ("docs/submission/",)

# Claim references stay keyword-anchored. The optional emphasis covers the
# repository's Markdown template (`**Closes:** #N`) without treating prose
# such as `see #123` as a lock.
ISSUE_REF = re.compile(
    r"(?<!\w)[*_]*(?:closes|fixes|resolves|issue)"
    r"(?:[*_]*\s*:?[ \t]*[*_]*)\s*#(\d+)",
    re.IGNORECASE,
)
SCOPE_BLOCK = re.compile(r"##\s*Scope.*?\n(.*?)(?=\n##\s|\Z)", re.DOTALL | re.IGNORECASE)
PATHS = re.compile(r"`([^`]+)`")
# Root-level files that carry no extension but are still real paths. Without
# this, `- \`Makefile\`` was silently dropped from a claim, and the gate then
# reported a file the author had declared.
ROOT_FILES = frozenset({"Makefile", "Dockerfile", "LICENSE", "NOTICE"})


def claim_issue_references(body: str) -> list[str]:
    """Return distinct keyword-anchored claim issue numbers, in body order."""
    return list(dict.fromkeys(ISSUE_REF.findall(body or "")))


def claim_issue_number(body: str) -> str | None:
    """Return one claim issue number, rejecting ambiguous PR bodies."""
    references = claim_issue_references(body)
    if len(references) > 1:
        formatted = ", ".join(f"#{number}" for number in references)
        raise ValueError(f"multiple distinct claim issues: {formatted}")
    return references[0] if references else None


def gh(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "mealog-claim-scope"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def changed_files(base: str) -> list[str]:
    subprocess.run(["git", "fetch", "--quiet", "origin", base], check=False)
    out = subprocess.run(["git", "diff", "--name-only", f"origin/{base}...HEAD"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\n") if f.strip()]


def declared_scope(body: str) -> list[str]:
    """Backticked paths inside the `## Scope` section.

    Prose in that section is for humans; the lock itself has to be unambiguous
    or agents will reason their way around it.
    """
    block = SCOPE_BLOCK.search(body or "")
    if not block:
        return []
    # Backticked paths only, but tolerate the common `a.md`, `b.md` grouping and
    # a path wrapped in a directory prefix, so one declaration cannot be read
    # two ways.
    #
    # "Looks like a path" is decided by shape, not by a list of known suffixes:
    # an allow-list silently dropped extension-less files such as `.gitignore`,
    # and the gate then reported a file its author had declared.
    return [p.strip().rstrip("/") for p in PATHS.findall(block.group(1))
            if _looks_like_path(p.strip())]


def _looks_like_path(candidate: str) -> bool:
    if "/" in candidate or candidate in ROOT_FILES:
        return True
    # A bare filename: dots are fine (`.gitignore`, `a.yml`), whitespace and
    # prose punctuation are not.
    return bool(re.fullmatch(r"[\w.\-+@]+", candidate))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--base", default="main")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("no GITHUB_TOKEN/GITHUB_REPOSITORY — skipping (local run)")
        return 0

    pr_number = args.pr
    if pr_number is None:
        event_path = os.environ.get("GITHUB_EVENT_PATH", "")
        if not event_path or not os.path.exists(event_path):
            print("not a pull_request event — nothing to check")
            return 0
        with open(event_path) as fh:
            pr_number = json.load(fh).get("pull_request", {}).get("number")
        if not pr_number:
            print("not a pull_request event — nothing to check")
            return 0

    try:
        pr = gh(f"/repos/{repo}/pulls/{pr_number}", token)
    except urllib.error.HTTPError as exc:
        # 403 here almost always means the workflow did not request
        # `pull-requests: read`. The default token is contents-only.
        print(f"FAIL: cannot read pull request #{pr_number}: {exc.code} {exc.reason}\n\n"
              "If this is 403, the workflow is missing a permissions block:\n"
              "  permissions:\n    contents: read\n    pull-requests: read\n    issues: read")
        return 1

    try:
        issue_number = claim_issue_number(pr.get("body") or "")
    except ValueError as exc:
        print(f"FAIL: this pull request references {exc}. "
              "Use exactly one '**Closes:** #N' reference.")
        return 1

    if not issue_number:
        print("FAIL: this pull request references no claim issue.\n\n"
              "docs/submission/AGENTS.md section 3: open a claim issue declaring the files you\n"
              "will touch, then reference it here as '**Closes:** #N'. That claim is\n"
              "the only thing stopping two agents editing the same file.")
        return 1
    try:
        issue = gh(f"/repos/{repo}/issues/{issue_number}", token)
    except urllib.error.HTTPError as exc:
        print(f"FAIL: cannot read claim issue #{issue_number}: {exc}")
        return 1

    scope = declared_scope(issue.get("body") or "")
    if not scope:
        print(f"FAIL: issue #{issue_number} declares no machine-readable scope.\n\n"
              "Add a '## Scope' section listing each path in backticks:\n"
              "  - `server/src/mealog/pipeline/retrieval.py`\n"
              "  - `eval/`")
        return 1

    violations = [p for p in changed_files(args.base)
                  if not p.startswith(ALWAYS_ALLOWED)
                  and not any(p == s or p.startswith(s.rstrip("/") + "/") for s in scope)]

    if violations:
        print(f"FAIL: {len(violations)} file(s) outside the scope declared on "
              f"issue #{issue_number}.\n")
        for v in violations:
            print(f"  {v}")
        print("\nDeclared scope:")
        for s in scope:
            print(f"  {s}")
        print("\nEither revert these files, or widen the scope on the claim issue\n"
              "*before* continuing — docs/submission/AGENTS.md section 3, step 3. Widening it is\n"
              "fine. Widening it silently is not.")
        return 1

    print(f"scope OK — all changes within issue #{issue_number} "
          f"({len(scope)} declared path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
