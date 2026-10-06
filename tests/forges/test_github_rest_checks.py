"""The draft toggle, rerunning cancelled checks and the failed-job log report,
through the typed client.

Draft goes through the GraphQL mutations, and the host changes what the next
read says. Logs come from the run's jobs and the job-log endpoint, which answers
with a redirect to storage as GitHub does; the extraction over the text (what a
line's timestamp is, where the error ends the useful part, the length cap) is
the forge's own and is checked on whole recorded logs.
"""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import github_answers as gh
from tests.forges.github_host import STORAGE, GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"

# --- draft ------------------------------------------------------------------------


def draft_host(*, draft: bool, refusal_text: str = "") -> GitHubHost:
    return GitHubHost(gh.pull(7, draft=draft), draft_refusal=refusal_text)


def mutations(host: GitHubHost) -> list[str]:
    return [
        name
        for call in host.graphql("mutation")
        for name in ("convertPullRequestToDraft", "markPullRequestReadyForReview")
        if name in call.query
    ]


def test_a_ready_pull_request_is_made_a_draft() -> None:
    host = draft_host(draft=False)

    GitHubForge(http=host).set_draft(REPO, 7, True)

    assert mutations(host) == ["convertPullRequestToDraft"]
    assert host.pull(7)["isDraft"] is True


def test_a_draft_is_published() -> None:
    host = draft_host(draft=True)

    GitHubForge(http=host).set_draft(REPO, 7, False)

    assert mutations(host) == ["markPullRequestReadyForReview"]
    assert host.pull(7)["isDraft"] is False


def test_made_a_draft_and_then_published_sends_both_in_order() -> None:
    host = draft_host(draft=False)
    forge = GitHubForge(http=host)

    forge.set_draft(REPO, 7, True)
    forge.set_draft(REPO, 7, False)

    assert mutations(host) == ["convertPullRequestToDraft", "markPullRequestReadyForReview"]


@pytest.mark.parametrize("draft", [True, False])
def test_a_pull_request_already_in_the_asked_for_state_is_not_written_to(draft: bool) -> None:
    host = draft_host(draft=draft)

    GitHubForge(http=host).set_draft(REPO, 7, draft)

    assert mutations(host) == []
    assert host.seen, "the current state is read before deciding"


def test_a_draft_refusal_raises_with_the_hosts_message() -> None:
    host = draft_host(draft=False, refusal_text="Draft pull requests are not supported here")

    with pytest.raises(RuntimeError, match="Draft pull requests are not supported"):
        GitHubForge(http=host).set_draft(REPO, 7, True)


# --- rerunning cancelled checks ---------------------------------------------------

RUNS = "https://github.com/example/app/actions/runs"


def rerun_host(reply: httpx.Response | None = None) -> GitHubHost:
    rollup = [
        gh.check_run("CI", "CANCELLED", run=123, job=9),
        gh.check_run("CI", "CANCELLED", run=123, job=10),
        gh.check_run("lint", "FAILURE", run=456, job=3),
    ]
    route = ("POST", f"{BASE}/actions/runs/123/rerun-failed-jobs")
    return GitHubHost(gh.pull(16, checks=rollup), routes={route: reply or answer({}, 201)})


OPEN_PULL = PullRequest(number=16, head="spec/add-marker/1", base="main", state="open")


def test_each_cancelled_run_is_rerun_once_and_a_failed_one_is_not() -> None:
    host = rerun_host()

    GitHubForge(http=host).rerun_checks(REPO, OPEN_PULL)

    assert [c.path for c in host.seen if c.method == "POST" and "/actions/" in c.path] == [
        f"{BASE}/actions/runs/123/rerun-failed-jobs"
    ]


def test_a_rerun_the_host_refuses_raises_naming_the_run() -> None:
    host = rerun_host(refusal(403, "Resource not accessible by integration"))

    with pytest.raises(RuntimeError, match="123.*[Rr]esource not accessible"):
        GitHubForge(http=host).rerun_checks(REPO, OPEN_PULL)


def test_no_cancelled_check_means_no_rerun() -> None:
    host = GitHubHost(gh.pull(16, checks=[gh.check_run("CI", "FAILURE")]))

    GitHubForge(http=host).rerun_checks(REPO, OPEN_PULL)

    assert not [c for c in host.seen if c.method == "POST" and "/actions/" in c.path]


# --- the failed-job log report ----------------------------------------------------

RUN = 36892939541
JOB = 110472774948


def failing_pull(failing: tuple[str, ...] = ("pre-commit",)) -> PullRequest:
    return PullRequest(
        number=50, head="spec/x/1", base="main", state="open", failing_checks=failing
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


def test_the_failed_job_s_log_is_what_the_rework_is_told() -> None:
    text = report(logs_host())

    assert "tests/runtimes/acp_agent.py:641:24" in text
    assert "pre-commit" in text
    assert str(RUN) in text
    assert "all fine" not in text, "a job that passed has nothing to say"


def test_the_log_is_fetched_from_the_run_s_jobs_and_the_job_log_endpoint() -> None:
    host = logs_host()

    report(host)

    assert host.calls("GET", f"{BASE}/actions/runs/{RUN}/jobs")
    assert host.calls("GET", f"{BASE}/actions/jobs/{JOB}/logs")
    assert not host.calls("GET", f"{BASE}/actions/jobs/2/logs")


def test_a_job_log_stops_at_the_error_not_in_the_runners_clean_up() -> None:
    text = report(logs_host())

    assert "Process completed with exit code 1" in text
    assert "Cleaning up orphan processes" not in text
    assert "Node.js 20 is deprecated" not in text


def test_a_job_log_loses_its_timestamps_and_byte_order_mark() -> None:
    text = report(logs_host())

    assert "2026-10-01T" not in text, "timestamps are noise to the reader"
    assert "\N{BYTE ORDER MARK}" not in text


def test_escape_sequences_in_the_log_are_kept() -> None:
    assert "\x1b[31mERROR\x1b[0m" in report(logs_host())


def test_a_log_longer_than_the_cap_keeps_its_end() -> None:
    lines = [f"2026-10-01T16:34:21.1000000Z filler line {i:05d}" for i in range(2000)]
    long_log = "\n".join([*lines, "2026-10-01T16:34:22.0000000Z ##[error]the real failure"])

    text = report(logs_host(job_log=long_log))

    assert "the real failure" in text
    assert "filler line 00000" not in text
    assert len(text) < 7000


def test_a_run_still_in_progress_reports_its_finished_failed_job() -> None:
    """The check fails in a minute and the slowest job takes several: the job
    that has finished has its log whatever the run is doing, and the one that
    has not has none."""
    host = logs_host(jobs=[gh.job(JOB, "pre-commit", "failure", RUN), gh.job(3, "slow", None, RUN)])

    text = report(host)

    assert "not assignable" in text


def test_a_failure_with_no_log_at_all_says_so() -> None:
    text = report(logs_host(job_log=None))

    assert "could not be fetched" in text
    assert "```" not in text, "an empty block reads as an empty log"


def test_the_signed_storage_link_is_fetched_without_the_credential() -> None:
    host = logs_host()

    report(host)

    [stored] = [call for call in host.seen if call.host == httpx.URL(STORAGE).host]
    assert "authorization" not in stored.headers, "the token belongs to GitHub, not to its storage"
    assert "sig=abc" in str(stored.request.url), "the signed link is fetched whole"
    for call in host.seen:
        if call is not stored:
            assert "authorization" in call.headers
