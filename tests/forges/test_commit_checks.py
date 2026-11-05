"""A forge reports the checks of a commit (spec: forge-pr-state): each check's name and status in
the pipeline's words, and one outcome for the commit as a whole: passed, failed, running, none
(the host lists no check for it) or unknown (the host could not be asked). Neither none nor
unknown is a pass. GitHub reads the commit's check runs, Azure DevOps the builds of the commit,
and the local forge answers from its own records, which hold no checks."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import CheckStatus, CommitOutcome, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.local import LocalForge
from tests.conftest import make_installation
from tests.factories import init_repo
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, refusal
from tests.forges.github_host import GitHubHost, answer
from tests.forges.github_routes import refusal as github_refusal

SHA = "c" * 40
OTHER = "d" * 40

# --- GitHub -----------------------------------------------------------------------------

GITHUB = RepoId(forge="github", account="example", name="app")
CHECK_RUNS = f"/repos/example/app/commits/{SHA}/check-runs"


def check_run(name: str, conclusion: str | None, *, status: str = "completed") -> dict:
    """One check run as the REST API lists it, with fields the forge does not read."""
    return {
        "id": abs(hash(name)) % 10**9,
        "head_sha": SHA,
        "node_id": "CR_kwDOAAAAAc8AAAAB",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/example/app/runs/{abs(hash(name)) % 10**9}",
        "details_url": "https://github.com/example/app/actions/runs/1/job/2",
        "started_at": "2026-09-28T09:18:40Z",
        "completed_at": "2026-09-28T09:20:01Z" if conclusion else None,
    }


def listed(*runs: dict) -> httpx.Response:
    return answer({"total_count": len(runs), "check_runs": list(runs)})


def github(reply: httpx.Response) -> GitHubHost:
    return GitHubHost(routes={("GET", CHECK_RUNS): reply})


@pytest.mark.usefixtures("github_env")
def test_github_reports_every_check_of_a_commit_whose_checks_all_passed() -> None:
    names = ("lint", "test", "types", "integration")
    host = github(listed(*(check_run(name, "success") for name in names)))

    found = GitHubForge(http=host).commit_checks(GITHUB, SHA)

    assert found.outcome == CommitOutcome.PASSED
    assert sorted(check.name for check in found.checks) == sorted(names)
    assert {check.status for check in found.checks} == {CheckStatus.PASSED}
    assert [call.path for call in host.seen] == [CHECK_RUNS]


@pytest.mark.usefixtures("github_env")
def test_github_reports_a_failed_check_as_failed() -> None:
    host = github(listed(check_run("lint", "success"), check_run("test", "failure")))

    found = GitHubForge(http=host).commit_checks(GITHUB, SHA)

    assert found.outcome == CommitOutcome.FAILED
    assert {check.name: check.status for check in found.checks}["test"] == CheckStatus.FAILED


@pytest.mark.usefixtures("github_env")
@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_github_reports_a_check_not_completed_as_running(status: str) -> None:
    host = github(listed(check_run("lint", "success"), check_run("test", None, status=status)))

    found = GitHubForge(http=host).commit_checks(GITHUB, SHA)

    assert found.outcome == CommitOutcome.RUNNING
    assert {check.name: check.status for check in found.checks}["test"] == CheckStatus.PENDING


@pytest.mark.usefixtures("github_env")
def test_github_reports_a_commit_with_no_check_runs_as_none_not_passed() -> None:
    found = GitHubForge(http=github(listed())).commit_checks(GITHUB, SHA)

    assert found.outcome == CommitOutcome.NONE
    assert found.checks == ()


@pytest.mark.usefixtures("github_env")
@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(github_refusal(500, "Server Error"), id="host-error"),
        pytest.param(github_refusal(404, "Not Found"), id="not-found"),
        pytest.param(github_refusal(403, "Resource not accessible"), id="refused"),
        pytest.param(answer({"unexpected": True}), id="not-the-document"),
    ],
)
def test_github_reports_a_request_that_errors_as_unknown_not_passed(
    reply: httpx.Response,
) -> None:
    host = github(reply)

    found = GitHubForge(http=host).commit_checks(GITHUB, SHA)

    assert found.outcome == CommitOutcome.UNKNOWN
    assert len(host.seen) == 1, "the forge asks once; it does not retry on its own"


@pytest.mark.usefixtures("github_env")
def test_github_reports_a_host_that_does_not_answer_as_unknown() -> None:
    host = github(httpx.ConnectError("no route to host"))

    assert GitHubForge(http=host).commit_checks(GITHUB, SHA).outcome == CommitOutcome.UNKNOWN


# --- Azure DevOps -----------------------------------------------------------------------

AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def build(
    number: int,
    name: str,
    result: str | None,
    *,
    status: str = "completed",
    commit: str = SHA,
) -> dict:
    """One build as the build list answers it."""
    return {
        "id": number,
        "buildNumber": f"2026.{number}",
        "status": status,
        "result": result,
        "sourceVersion": commit,
        "sourceBranch": "refs/heads/main",
        "definition": {"id": 10 + len(name), "name": name},
        "repository": {"id": azure_answers.GUID, "type": "TfsGit"},
        "queueTime": "2026-09-24T18:02:11.483Z",
    }


def azure(*builds: dict, **host: object) -> RestHost:
    return RestHost(commit_builds=list(builds), **host)  # type: ignore[arg-type]


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_the_builds_of_a_commit_that_all_succeeded_as_passed() -> None:
    host = azure(build(1, "CI", "succeeded"), build(2, "lint", "succeeded"))

    found = AzureDevOpsForge(http=host).commit_checks(AZURE, SHA)

    assert found.outcome == CommitOutcome.PASSED
    assert sorted(check.name for check in found.checks) == ["CI", "lint"]


@pytest.mark.usefixtures("rest_env")
@pytest.mark.parametrize("result", ["failed", "partiallySucceeded"])
def test_azure_reports_a_failed_build_as_failed(result: str) -> None:
    host = azure(build(1, "CI", result), build(2, "lint", "succeeded"))

    assert AzureDevOpsForge(http=host).commit_checks(AZURE, SHA).outcome == CommitOutcome.FAILED


@pytest.mark.usefixtures("rest_env")
@pytest.mark.parametrize("status", ["inProgress", "notStarted"])
def test_azure_reports_a_build_not_completed_as_running(status: str) -> None:
    host = azure(build(1, "CI", None, status=status), build(2, "lint", "succeeded"))

    assert AzureDevOpsForge(http=host).commit_checks(AZURE, SHA).outcome == CommitOutcome.RUNNING


@pytest.mark.usefixtures("rest_env")
def test_azure_reads_only_the_builds_of_the_commit_asked_about() -> None:
    host = azure(build(1, "CI", "failed", commit=OTHER), build(2, "CI", "succeeded"))

    found = AzureDevOpsForge(http=host).commit_checks(AZURE, SHA)

    assert found.outcome == CommitOutcome.PASSED
    assert [check.name for check in found.checks] == ["CI"]


@pytest.mark.usefixtures("rest_env")
def test_azure_takes_the_newest_build_of_each_definition() -> None:
    host = azure(build(3, "CI", "succeeded"), build(1, "CI", "failed"))

    assert AzureDevOpsForge(http=host).commit_checks(AZURE, SHA).outcome == CommitOutcome.PASSED


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_a_commit_with_no_builds_as_none_not_passed() -> None:
    host = azure(build(1, "CI", "succeeded", commit=OTHER))

    found = AzureDevOpsForge(http=host).commit_checks(AZURE, SHA)

    assert found.outcome == CommitOutcome.NONE
    assert found.checks == ()


@pytest.mark.usefixtures("rest_env")
@pytest.mark.parametrize("status", [401, 404])
def test_azure_reports_a_request_that_errors_as_unknown_not_passed(status: int) -> None:
    host = azure(
        build(1, "CI", "succeeded"),
        refuse={("GET", "build/builds"): refusal(status, "TF400813: refused")},
    )

    assert AzureDevOpsForge(http=host).commit_checks(AZURE, SHA).outcome == CommitOutcome.UNKNOWN


# --- local ------------------------------------------------------------------------------


def test_the_local_forge_answers_none_from_its_records_which_hold_no_checks(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "app")
    installation = make_installation(
        tmp_path / "planning", repos={"app": {"path": str(repo), "forge": "local"}}
    )
    forge = LocalForge(installation.state_dir)
    repo_id = forge.identity(installation.repo("app"))

    found = forge.commit_checks(repo_id, SHA)

    assert found.outcome == CommitOutcome.NONE
    assert found.checks == ()
