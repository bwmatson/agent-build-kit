"""A real reviewer blocks a seeded duplicate and does not block a clean change.

The scratch app gets a local branch `spec/<change>/1` holding a tests commit and an
implementation commit, so the build agent never runs and the one agent call that matters is
the reviewer's. One branch re-implements the existing helper under a new name; the other calls
it. The tests read the review's findings from the unit's thread. The clean branch is not asked
to draw no required finding at all: an unrelated one would be a flake that has nothing to do
with duplication, so the failure message shows every finding instead.

Needs an agent speaking the protocol, node for the OpenSpec CLI and uv. Bills on demand, so it
is marked e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator

import pytest

from tests.dry_checks import session_prompts
from tests.dry_scratch import (
    DryRun,
    evidence,
    fake_host,
    review_findings,
    ticked_case,
)
from tests.forges.github_server import FakeGitHub
from tests.prompt_text import flat

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.runtime_acp,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

EXISTING = ("slugify", "text.py")
PRIOR_ART_CLAUSE = ("Search for prior art", "two copies must change together")


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    with fake_host() as server:
        yield server


@pytest.fixture(scope="module")
def duplicate(tmp_path_factory, github_host) -> Iterator[DryRun]:
    with ticked_case(tmp_path_factory, github_host, "duplicate") as run:
        yield run


@pytest.fixture(scope="module")
def clean(tmp_path_factory, github_host) -> Iterator[DryRun]:
    with ticked_case(tmp_path_factory, github_host, "clean") as run:
        yield run


def names_existing(finding: dict) -> bool:
    text = f"{finding.get('file', '')} {finding.get('summary', '')}"
    return any(name in text for name in EXISTING)


def shown(run: DryRun) -> str:
    return f"{evidence(run)}\nfindings: {json.dumps(review_findings(run), indent=2, default=str)}"


def test_a_review_of_a_seeded_duplicate_returns_a_required_finding_naming_the_existing_function(
    duplicate: DryRun,
) -> None:
    findings = review_findings(duplicate)

    required = [f for f in findings if f.get("required") and names_existing(f)]

    assert required, shown(duplicate)


def test_a_review_of_a_clean_branch_returns_no_required_finding_naming_the_existing_function(
    clean: DryRun,
) -> None:
    findings = review_findings(clean)

    required = [f for f in findings if f.get("required") and names_existing(f)]

    assert required == [], shown(clean)


@pytest.mark.parametrize("run_name", ["duplicate", "clean"])
def test_the_review_prompt_the_reviewer_was_sent_holds_the_prior_art_clause(
    request: pytest.FixtureRequest, run_name: str
) -> None:
    run: DryRun = request.getfixturevalue(run_name)

    prompts = [flat(p) for p in session_prompts(run.record)]

    assert any(all(part in p for part in PRIOR_ART_CLAUSE) for p in prompts), shown(run)


# The prompts are recorded at the protocol by a wrapper around the agent command, which only
# an ACP agent speaks, so no scenario here has a Claude Code variant.
ACP_ONLY_REASONS = {
    name: "the prompts are recorded at the ACP wire by a wrapper around the agent command"
    for name in list(globals())
    if name.startswith("test_")
}
