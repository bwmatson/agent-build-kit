"""What a rework is told about a failing CI check.

The poller reports a check as failed the moment it does, and a run's other
jobs are often still going: `gh run view --log-failed` has nothing to show
for a run in progress, so the rework was handed an empty block and could only
say it had been. A job that has finished has its log whatever the run is
doing, and that is the fallback; when there is nothing at all the rework is
told so, and what to run instead.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import FORGE

REPO = RepoId(forge="github", account="example", name="app")
RUN = "36892939541"
JOB = "110472774948"
DETAILS = f"https://github.com/example/app/actions/runs/{RUN}/job/{JOB}"

ROLLUP = {
    "statusCheckRollup": [
        {"name": "pre-commit", "conclusion": "FAILURE", "detailsUrl": DETAILS},
        {"name": "test", "conclusion": "SUCCESS", "detailsUrl": DETAILS.replace(JOB, "2")},
    ]
}

JOB_LOG = "\n".join(
    [
        "2026-10-01T16:34:04.0987227Z ##[group]Run uv run pre-commit run --all-files",
        "2026-10-01T16:34:21.1000000Z pyrefly check....Failed",
        "2026-10-01T16:34:21.2000000Z ERROR Argument `str` is not assignable [bad-argument-type]",
        "2026-10-01T16:34:21.3000000Z    --> tests/runtimes/acp_agent.py:641:24",
        "2026-10-01T16:34:21.4000000Z ##[error]Process completed with exit code 1.",
        "2026-10-01T16:34:22.5554669Z Cleaning up orphan processes",
        "2026-10-01T16:34:22.5861981Z ##[warning]Node.js 20 is deprecated.",
    ]
)

RUN_LOG = "pre-commit\tRun pre-commit\t2026-10-01T16:34:21.2Z ERROR the run-level failure"


class Host:
    """`gh`, answering only what a log fetch asks, and recording each call."""

    def __init__(self, *, run_log: str = RUN_LOG, job_log: str = JOB_LOG) -> None:
        self.run_log, self.job_log = run_log, job_log
        self.calls: list[list[str]] = []

    def gh(self, args, **kwargs):
        self.calls.append(list(args))
        text = self.job_log if args[:2] == ["gh", "api"] else self.run_log
        return subprocess.CompletedProcess(args, 0, text, "")


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> Host:
    fake = Host()
    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", lambda *a, **k: ROLLUP)
    monkeypatch.setattr("agent_build_kit.forges.github.gh", fake.gh)
    return fake


def pull() -> PullRequest:
    return PullRequest(
        number=50, head="spec/x/1", base="main", state="open", failing_checks=("pre-commit",)
    )


def test_a_finished_run_gives_its_failed_log_as_before(host: Host) -> None:
    report = FORGE.failed_check_logs(REPO, pull())

    assert "the run-level failure" in report
    assert not any(call[:2] == ["gh", "api"] for call in host.calls)


def test_a_run_with_no_log_yet_falls_back_to_the_failed_job(host: Host) -> None:
    host.run_log = ""

    report = FORGE.failed_check_logs(REPO, pull())

    assert "bad-argument-type" in report
    assert "tests/runtimes/acp_agent.py:641:24" in report
    assert [
        "gh",
        "api",
        f"repos/example/app/actions/jobs/{JOB}/logs",
        "--allow-escape-sequences",
    ] in host.calls


def test_a_job_log_stops_at_the_error_not_in_the_runners_clean_up(host: Host) -> None:
    host.run_log = ""

    report = FORGE.failed_check_logs(REPO, pull())

    assert "Process completed with exit code 1" in report
    assert "Cleaning up orphan processes" not in report
    assert "2026-10-01T" not in report, "timestamps are noise to the reader"


def test_a_failure_with_no_log_at_all_says_so(host: Host) -> None:
    host.run_log, host.job_log = "", ""

    report = FORGE.failed_check_logs(REPO, pull())

    assert "could not be fetched" in report
    assert "```" not in report, "an empty block reads as an empty log"


def test_no_failing_check_means_no_report(host: Host) -> None:
    quiet = PullRequest(number=50, head="spec/x/1", base="main", state="open")

    assert FORGE.failed_check_logs(REPO, quiet) == ""
    assert host.calls == []
