"""GitHub check runs become checks, each with one of the four statuses.

The documents are the rollup as the host sends it: a check run with no
conclusion is one that has not finished, whatever its `status` says, and a
conclusion the forge does not know is waiting rather than a verdict.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import Check, CheckStatus, PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")


def one(*rollup: dict) -> PullRequest:
    [pull] = GitHubForge(http=GitHubHost(gh.pull(16, checks=list(rollup)))).list_prs(REPO)
    return pull


def statuses(pull: PullRequest) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in pull.checks}


@pytest.mark.parametrize(
    ("conclusion", "status"),
    [
        ("SUCCESS", CheckStatus.PASSED),
        ("NEUTRAL", CheckStatus.PASSED),
        ("SKIPPED", CheckStatus.PASSED),
        ("FAILURE", CheckStatus.FAILED),
        ("TIMED_OUT", CheckStatus.FAILED),
        ("CANCELLED", CheckStatus.CANCELLED),
    ],
)
def test_a_conclusion_maps_to_its_status(conclusion: str, status: CheckStatus) -> None:
    assert statuses(one(gh.check_run("CI", conclusion))) == {"CI": status}


@pytest.mark.parametrize("running", ["QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "PENDING"])
def test_a_check_with_no_conclusion_is_pending(running: str) -> None:
    pull = one(gh.check_run("CI", None, status=running))

    assert statuses(pull) == {"CI": CheckStatus.PENDING}


@pytest.mark.parametrize("conclusion", ["ACTION_REQUIRED", "SOMETHING_NEW"])
def test_a_conclusion_the_forge_does_not_know_is_pending_not_failed(conclusion: str) -> None:
    pull = one(gh.check_run("CI", conclusion))

    assert statuses(pull) == {"CI": CheckStatus.PENDING}


def test_a_passing_a_failing_a_cancelled_and_a_running_check_are_one_each() -> None:
    pull = one(
        gh.check_run("test", "SUCCESS"),
        gh.check_run("lint", "FAILURE"),
        gh.check_run("build", "CANCELLED"),
        gh.check_run("deploy", None, status="IN_PROGRESS"),
    )

    assert statuses(pull) == {
        "test": CheckStatus.PASSED,
        "lint": CheckStatus.FAILED,
        "build": CheckStatus.CANCELLED,
        "deploy": CheckStatus.PENDING,
    }
    assert len(pull.checks) == 4


def test_a_check_carries_the_details_link() -> None:
    [check] = one(gh.check_run("CI", "FAILURE", run=7, job=9)).checks

    assert check == Check(
        name="CI",
        status=CheckStatus.FAILED,
        url=f"{gh.WEB}/actions/runs/7/job/9",
    )


def test_a_commit_status_in_the_rollup_is_not_a_check() -> None:
    pull = one(gh.check_run("CI", "SUCCESS"), gh.STATUS_CONTEXT)

    assert statuses(pull) == {"CI": CheckStatus.PASSED}


def test_a_commit_with_no_checks_has_an_empty_list() -> None:
    [pull] = GitHubForge(http=GitHubHost(gh.pull(16, checks=None))).list_prs(REPO)

    assert pull.checks == ()
