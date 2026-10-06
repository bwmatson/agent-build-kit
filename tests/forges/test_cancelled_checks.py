"""A cancelled check is neither passing nor failing.

The host cancels a check when a runner never came, a newer run superseded it
or a person stopped it; none of that is a verdict on the commit. A timed-out or
failed check is, and stays a failure.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.pr_poller import Poller
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost

pytestmark = pytest.mark.usefixtures("github_env")

GITHUB_REPO = RepoId(forge="github", account="example", name="app")


def github_pull(*rollup: dict) -> PullRequest:
    host = GitHubHost(gh.pull(16, checks=list(rollup)))
    [pull] = GitHubForge(http=host).list_prs(GITHUB_REPO)
    return pull


# --- a re-run check that then fails is an ordinary failure -------------------------


def test_a_check_cancelled_then_failing_is_reworked_through_the_failing_path(tmp_path) -> None:
    pages = iter(
        [
            [gh.check_run("CI", "SUCCESS")],
            [gh.check_run("CI", "CANCELLED")],
            [gh.check_run("CI", "FAILURE")],
        ]
    )
    seen: list[tuple] = []
    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=lambda: [github_pull(*next(pages))],
        dispatch=lambda action, number, **kw: seen.append((action, kw.get("reason"))),
    )

    for _ in range(3):
        poller.poll()

    assert seen == [("rerun_checks", None), ("rework", "failing checks: CI")]
