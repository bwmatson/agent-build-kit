"""`retarget_pr` says whether the host reports the wanted base afterwards (spec: merge-landing).

Each host is its own stand-in: the local forge over a temporary state directory, the GitHub and
Azure DevOps REST stand-ins answering the raw documents the real hosts send. A retarget the
host refuses or silently ignores is a False, never an exception and never a quiet True."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.local import LocalForge
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.azure_rest_host import answer as azure_answer
from tests.forges.azure_rest_host import refusal as azure_refusal
from tests.forges.github_host import GitHubHost, answer, refusal

HEAD = "spec/add-marker/1"
NEW_BASE = "spec/other/0"

LOCAL = RepoId(forge="local", account="local", name="app")
GITHUB = RepoId(forge="github", account="example", name="app")
GITHUB_PULL = "/repos/example/app/pulls/7"
AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def github_pull(base: str) -> httpx.Response:
    return answer(
        {
            "number": 7,
            "node_id": "PR_kwDOAAAAAc00000007",
            "state": "open",
            "html_url": "https://github.com/example/app/pull/7",
            "head": {"ref": HEAD},
            "base": {"ref": base},
        }
    )


# --- the local forge ---------------------------------------------------------------


@pytest.fixture
def local(tmp_path: Path) -> LocalForge:
    state = tmp_path / "state"
    state.mkdir()
    return LocalForge(state)


def test_the_local_forge_reports_a_retarget_it_recorded(local: LocalForge) -> None:
    number = local.create_pr(LOCAL, head=HEAD, base="main", title="t", body="b")

    assert local.retarget_pr(LOCAL, number, NEW_BASE) is True
    assert [p.base for p in local.list_prs(LOCAL)] == [NEW_BASE]


def test_the_local_forge_reports_false_for_a_pull_request_it_does_not_hold(
    local: LocalForge,
) -> None:
    assert local.retarget_pr(LOCAL, 99, NEW_BASE) is False


# --- GitHub ------------------------------------------------------------------------


@pytest.mark.usefixtures("github_env")
def test_github_reports_true_when_the_base_read_back_is_the_wanted_one() -> None:
    host = GitHubHost(
        routes={
            ("PATCH", GITHUB_PULL): github_pull(NEW_BASE),
            ("GET", GITHUB_PULL): github_pull(NEW_BASE),
        }
    )

    assert GitHubForge(http=host).retarget_pr(GITHUB, 7, NEW_BASE) is True
    [call] = host.calls("PATCH", GITHUB_PULL)
    assert call.body == {"base": NEW_BASE}


@pytest.mark.usefixtures("github_env")
def test_github_reports_false_when_the_host_refuses_the_retarget() -> None:
    host = GitHubHost(
        routes={
            ("PATCH", GITHUB_PULL): refusal(422, "Validation Failed"),
            ("GET", GITHUB_PULL): github_pull("main"),
        }
    )

    assert GitHubForge(http=host).retarget_pr(GITHUB, 7, NEW_BASE) is False


@pytest.mark.usefixtures("github_env")
def test_github_reports_false_when_the_host_accepts_the_call_but_keeps_the_old_base() -> None:
    host = GitHubHost(
        routes={
            ("PATCH", GITHUB_PULL): github_pull(NEW_BASE),
            ("GET", GITHUB_PULL): github_pull("main"),
        }
    )

    assert GitHubForge(http=host).retarget_pr(GITHUB, 7, NEW_BASE) is False


# --- Azure DevOps ------------------------------------------------------------------


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_true_when_the_target_read_back_is_the_wanted_branch() -> None:
    host = RestHost(azure_answers.OPEN)

    assert AzureDevOpsForge(http=host).retarget_pr(AZURE, 162, NEW_BASE) is True
    [call] = host.writes()
    assert call.body == {"targetRefName": f"refs/heads/{NEW_BASE}"}


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_false_when_the_host_refuses_the_retarget() -> None:
    host = RestHost(
        azure_answers.OPEN,
        refuse={("PATCH", "pullrequests/162"): azure_refusal(400, "cannot retarget")},
    )

    assert AzureDevOpsForge(http=host).retarget_pr(AZURE, 162, NEW_BASE) is False


@pytest.mark.usefixtures("rest_env")
def test_azure_reports_false_when_the_host_accepts_the_call_but_keeps_the_old_target() -> None:
    host = RestHost(
        azure_answers.OPEN,
        refuse={("PATCH", "pullrequests/162"): azure_answer({"pullRequestId": 162})},
    )

    assert AzureDevOpsForge(http=host).retarget_pr(AZURE, 162, NEW_BASE) is False
