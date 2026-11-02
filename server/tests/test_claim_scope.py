import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.check_claim_scope import (
    claim_issue_number,
    claim_issue_references,
    declared_scope,
    is_automation,
    missing_scope_message,
)


def test_pr_template_shape_binds_claim_issue() -> None:
    template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
    body = template.replace("**Closes:** #<issue>", "**Closes:** #71")

    assert claim_issue_number(body) == "71"


@pytest.mark.parametrize("body", ["Closes #71", "closes: #71", "Fixes #71"])
def test_plain_keyword_shapes_bind_claim_issue(body: str) -> None:
    assert claim_issue_number(body) == "71"


def test_prose_issue_reference_does_not_bind_claim_issue() -> None:
    assert claim_issue_references("See #123 for context; no claim is declared.") == []
    assert claim_issue_number("See #123 for context; no claim is declared.") is None


def test_multiple_distinct_claims_fail_loudly() -> None:
    with pytest.raises(ValueError, match=r"multiple distinct claim issues: #71, #72"):
        claim_issue_number("Closes #71\nFixes #72")


@pytest.mark.parametrize("declared", [".gitignore", "LICENSE", "Makefile", "docker-compose.yml",
                                      "src/a/b.ts"])
def test_every_declared_path_shape_is_read(declared: str) -> None:
    """An allow-list of suffixes silently dropped real files from a claim."""
    body = f"## Scope\n\n`{declared}`\n"

    assert declared_scope(body) == [declared]


def test_scope_ignores_prose_but_keeps_backticked_paths() -> None:
    body = ("## Scope\n\nSee the `README.md` for why.\n\n"
            "`scripts/a.py` `tests/` `not a path with spaces`\n")

    assert declared_scope(body) == ["README.md", "scripts/a.py", "tests"]


@pytest.mark.parametrize("author", ["dependabot[bot]", "Dependabot[bot]", "renovate[bot]"])
def test_automated_updates_are_exempt_from_the_claim_check(author: str) -> None:
    """A bot cannot open a claim issue, so the check must not demand one."""
    assert is_automation(author)


@pytest.mark.parametrize("author", ["zexy2", "", None, "someone-dependabot"])
def test_humans_still_need_a_claim(author: str | None) -> None:
    """The exemption is a named allow-list, not a pattern that can be spoofed
    by a login that merely contains the word."""
    assert not is_automation(author)


def test_missing_scope_message_says_where_to_put_it() -> None:
    """The message is the only instruction most authors see. It has to name the
    issue body, not the pull request body, and show the heading shape."""
    message = missing_scope_message("424")

    assert "#424" in message
    assert "edit the issue, not the pull" in message
    assert "## Scope" in message
    assert declared_scope("## Scope\n\n`scripts/a.py`") == ["scripts/a.py"], \
        "the shape the message recommends must be the shape the parser reads"


def test_inline_mention_of_scope_does_not_shadow_the_real_section() -> None:
    """Issue #424 described 'the `## Scope` section' in its Why paragraph. The
    parser matched that sentence instead of the heading and reported the issue
    as scopeless, so a correct issue was rejected."""
    body = (
        "## Why\n\n"
        "The check requires a claim issue with a `## Scope` section — a rule that\n"
        "cannot be satisfied by a bot.\n\n"
        "## What\n\n"
        "- exempt bots\n\n"
        "## Scope\n\n"
        "`scripts/check_claim_scope.py`\n"
        "`server/tests/test_claim_scope.py`\n"
    )

    assert declared_scope(body) == ["scripts/check_claim_scope.py",
                                    "server/tests/test_claim_scope.py"]


@pytest.mark.parametrize("heading", ["## Scope", "## scope", "##Scope", "### Scope"])
def test_scope_heading_may_be_any_level_and_case(heading: str) -> None:
    assert declared_scope(f"{heading}\n\n`Makefile`\n") == ["Makefile"]


def test_the_claim_issue_template_actually_parses() -> None:
    """The template is what a claim author fills in. If the parser cannot read
    its heading, every claim made from it is rejected."""
    template = (ROOT / ".github/ISSUE_TEMPLATE/agent-work-claim.md").read_text(
        encoding="utf-8")
    filled = template.replace("- `path/one`\n- `path/two`",
                              "- `server/src/a.ts`\n- `eval/`")

    # Trailing slashes are normalised away; the scope check prefixes them back.
    assert declared_scope(filled) == ["server/src/a.ts", "eval"]


def test_a_link_to_scope_in_another_issue_is_not_the_section() -> None:
    """A cross-reference heading is prose about another issue's scope."""
    body = "## Scope [#71](https://github.com/o/r/issues/71)\n\n`README.md`\n\n## Later\n\n`a.py`\n"

    assert declared_scope(body) == []
