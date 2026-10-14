"""A failed pull request's job log as the forge reports it: the host, the run, the job."""

from __future__ import annotations

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.check_lists import failed_list
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost

REPO = RepoId(forge="github", account="example", name="app")

RUN = 36892939541
JOB = 110472774948


def failing_pull(failing: tuple[str, ...] = ("pre-commit",)) -> PullRequest:
    return PullRequest(
        number=50, head="spec/x/1", base="main", state="open", checks=failed_list(*failing)
    )


def logs_host(*, job_log: str | None = gh.JOB_LOG, jobs: list[dict] | None = None) -> GitHubHost:
    rollup = [
        gh.check_run("pre-commit", "FAILURE", run=RUN, job=JOB),
        gh.check_run("test", "SUCCESS", run=RUN, job=2),
    ]
    return GitHubHost(
        gh.pull(50, checks=rollup),
        jobs={
            RUN: jobs
            or [gh.job(JOB, "pre-commit", "failure", RUN), gh.job(2, "test", "success", RUN)]
        },
        job_logs={} if job_log is None else {JOB: job_log, 2: "2026-10-01T16:30:00.0Z all fine"},
    )


def report(host: GitHubHost) -> str:
    return GitHubForge(http=host).failed_check_logs(REPO, failing_pull())
