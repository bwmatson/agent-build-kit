"""A cancelled check is neither passing nor failing, on either host.

The host cancels a check when a runner never came, a newer run superseded it
or a person stopped it; none of that is a verdict on the commit. A timed-out or
failed check is, and stays a failure.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_build_kit.forges.azure_devops import FORGE as AZURE
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import FORGE as GITHUB
from agent_build_kit.pipeline.pr_poller import Poller
from tests.forges import azure_answers

AZURE_REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
GITHUB_REPO = RepoId(forge="github", account="o", name="r")

PULL = {
    "number": 16,
    "headRefName": "spec/add-marker/1",
    "baseRefName": "main",
    "state": "OPEN",
    "isDraft": False,
    "mergedAt": None,
    "labels": [],
    "comments": [],
    "reviewDecision": "",
    "reviews": [],
}


def github_pull(*rollup: dict) -> PullRequest:
    raw = json.dumps([{**PULL, "statusCheckRollup": list(rollup)}])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("agent_build_kit.forges.github.gh_out", lambda args: raw)
        [pull] = GITHUB.list_prs(GITHUB_REPO)
    return pull


def check(name: str, conclusion: str) -> dict:
    """A check run as `gh pr list --json statusCheckRollup` reports it."""
    return {
        "__typename": "CheckRun",
        "completedAt": "2026-09-28T09:20:01Z",
        "conclusion": conclusion,
        "detailsUrl": "https://github.com/example/app/actions/runs/1/job/2",
        "name": name,
        "startedAt": "2026-09-28T09:18:40Z",
        "status": "COMPLETED",
        "workflowName": "CI",
    }


def test_a_cancelled_github_check_is_cancelled_and_not_failing() -> None:
    pull = github_pull(check("CI", "CANCELLED"), check("lint", "SUCCESS"))

    assert pull.cancelled_checks == ("CI",)
    assert pull.failing_checks == ()


def test_a_failed_or_timed_out_github_check_stays_failing() -> None:
    pull = github_pull(
        check("CI", "FAILURE"), check("slow", "TIMED_OUT"), check("lint", "CANCELLED")
    )

    assert pull.failing_checks == ("CI", "slow")
    assert pull.cancelled_checks == ("lint",)


def test_a_github_check_with_no_conclusion_is_neither() -> None:
    pull = github_pull({"__typename": "CheckRun", "name": "CI", "status": "IN_PROGRESS"})

    assert pull.failing_checks == ()
    assert pull.cancelled_checks == ()


# --- Azure DevOps ----------------------------------------------------------------
#
# A build policy evaluation reports `rejected` for a build that did not pass; the
# build itself says how it ended, `failed` or `canceled`, in its `result`.


def build(build_id: int, result: str) -> dict:
    """A build as `az pipelines runs show` answers."""
    return {
        "id": build_id,
        "buildNumber": f"2026.{build_id}",
        "status": "completed",
        "result": result,
        "reason": "pullRequest",
        "queueTime": "2026-09-24T18:02:11.483Z",
        "finishTime": "2026-09-24T18:09:00.000Z",
    }


def evaluated(status: str, name: str, build_id: int) -> dict:
    document = azure_answers.evaluation(status, name)
    document["context"] = {"buildId": build_id, "isExpired": False}
    return document


def azure_pull(*evaluations: dict, builds: dict[int, str]) -> PullRequest:
    def run(args, **kwargs):
        payload: object
        if "pullRequestThreads" in args:
            payload = azure_answers.threads()
        elif "pullRequestStatuses" in args:
            payload = {"value": []}
        elif "policy" in args:
            payload = list(evaluations)
        elif "list" in args and "pr" in args:
            payload = [azure_answers.OPEN]
        else:
            # Whatever else is asked is the build behind an evaluation.
            asked = [i for i in builds if any(str(i) in str(arg) for arg in args)]
            payload = build(asked[0], builds[asked[0]]) if asked else {}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    [pull] = AZURE.list_prs(AZURE_REPO, run=run)
    return pull


def test_a_canceled_azure_build_is_cancelled_and_not_failing() -> None:
    pull = azure_pull(evaluated("rejected", "CI build", 41), builds={41: "canceled"})

    assert pull.cancelled_checks == ("CI build",)
    assert pull.failing_checks == ()


def test_a_failed_azure_build_stays_failing() -> None:
    pull = azure_pull(evaluated("rejected", "CI build", 41), builds={41: "failed"})

    assert pull.failing_checks == ("CI build",)
    assert pull.cancelled_checks == ()


def test_azure_reports_a_mixed_outcome_in_both_lists() -> None:
    pull = azure_pull(
        evaluated("rejected", "CI build", 41),
        evaluated("rejected", "lint build", 42),
        builds={41: "canceled", 42: "failed"},
    )

    assert pull.cancelled_checks == ("CI build",)
    assert pull.failing_checks == ("lint build",)


# --- a re-run check that then fails is an ordinary failure -------------------------


def test_a_check_cancelled_then_failing_is_reworked_through_the_failing_path(tmp_path) -> None:
    pages = iter(
        [
            [check("CI", "SUCCESS")],
            [check("CI", "CANCELLED")],
            [check("CI", "FAILURE")],
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
