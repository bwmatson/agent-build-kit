"""A cancelled check is neither passing nor failing.

The host cancels a check when a runner never came, a newer run superseded it
or a person stopped it; none of that is a verdict on the commit. A timed-out or
failed check is, and stays a failure.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import FORGE as GITHUB
from agent_build_kit.pipeline.pr_poller import Poller

GITHUB_REPO = RepoId(forge="github", account="example", name="app")
OPEN_PULL = PullRequest(number=16, head="spec/add-marker/1", base="main", state="open")

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


# --- asking the host to run cancelled checks again -------------------------------------


def github_rollup(monkeypatch, result_code: int, stderr: str = "") -> list[list[str]]:
    base = "https://github.com/example/app/actions/runs"
    rollup = [
        {**check("CI", "CANCELLED"), "detailsUrl": f"{base}/123/job/9"},
        {**check("CI", "CANCELLED"), "detailsUrl": f"{base}/123/job/10"},
        {**check("lint", "FAILURE"), "detailsUrl": f"{base}/456/job/3"},
    ]
    sent: list[list[str]] = []
    monkeypatch.setattr(
        "agent_build_kit.forges.github.gh_json", lambda args, **kw: {"statusCheckRollup": rollup}
    )
    monkeypatch.setattr(
        "agent_build_kit.forges.github.gh",
        lambda args, **kw: (
            sent.append(args) or subprocess.CompletedProcess(args, result_code, "", stderr)
        ),
    )
    return sent


def test_github_reruns_each_cancelled_run_once_and_not_a_failed_one(monkeypatch) -> None:
    sent = github_rollup(monkeypatch, 0)

    GITHUB.rerun_checks(GITHUB_REPO, OPEN_PULL)

    assert sent == [["gh", "run", "rerun", "123", "--repo", "example/app", "--failed"]]


def test_github_refusing_a_rerun_raises(monkeypatch) -> None:
    github_rollup(monkeypatch, 1, "resource not accessible")

    with pytest.raises(RuntimeError, match="123.*resource not accessible"):
        GITHUB.rerun_checks(GITHUB_REPO, OPEN_PULL)


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
