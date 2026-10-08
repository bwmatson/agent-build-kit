"""The address GitHub calls go to is `ABK_GITHUB_API_URL`: the forge's client and
`abk doctor`'s credential check both use it, and a trailing slash changes nothing.

Read off the requests that reach the stand-in host (their URLs), with the setting
changed through the settings object the process reads it from.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.settings import settings
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo
from tests.forges.conftest import GH_TOKEN
from tests.forges.github_host import GitHubHost, answer
from tests.forges.mock_host import MockHost, recorded

REPO = RepoId(forge="github", account="example", name="app")
HEAD = "spec/add-marker/1"
OTHER = "https://ghe.example.test/api/v3"


@pytest.fixture(autouse=True)
def token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "gh_token", GH_TOKEN)
    clear_credentials()
    yield
    clear_credentials()


def created() -> httpx.Response:
    return answer({"number": 7, "node_id": "PR_kwDOAAAAAc00000007", "state": "open"}, 201)


def create_pull(host: GitHubHost) -> list[httpx.URL]:
    GitHubForge(http=host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")
    return [call.request.url for call in host.seen]


def doctor_urls(workspace: Path) -> list[httpx.URL]:
    host = MockHost(recorded("user_200"))
    run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all, transport=host)
    return [request.url for request in host.requests]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    config = WorkspaceConfig(repos={"app": RepoConfig(path=app, slug="example/app")})
    (planning / "abk.yaml").write_text(dump(config))
    return planning


def test_with_no_setting_the_forge_calls_github() -> None:
    host = GitHubHost(routes={("POST", "/repos/example/app/pulls"): created()})

    [url] = create_pull(host)

    assert url.host == "api.github.com"
    assert url.path == "/repos/example/app/pulls"


def test_with_no_setting_the_doctor_calls_github(workspace: Path) -> None:
    urls = doctor_urls(workspace)

    assert urls
    assert {url.host for url in urls} == {"api.github.com"}


def test_with_the_setting_the_forge_calls_that_address_and_not_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_api_url", OTHER)
    host = GitHubHost(routes={("POST", "/api/v3/repos/example/app/pulls"): created()})

    [url] = create_pull(host)

    assert url.host == "ghe.example.test"
    assert url.path == "/api/v3/repos/example/app/pulls"
    assert host.unrouted == []


def test_with_the_setting_the_doctor_calls_that_address_and_not_github(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    monkeypatch.setattr(settings, "github_api_url", OTHER)

    urls = doctor_urls(workspace)

    assert urls
    assert {url.host for url in urls} == {"ghe.example.test"}
    assert {url.path for url in urls} == {"/api/v3/user"}


def test_a_trailing_slash_gives_no_doubled_slash_in_the_forge_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "github_api_url", f"{OTHER}/")
    host = GitHubHost(routes={("POST", "/api/v3/repos/example/app/pulls"): created()})

    [url] = create_pull(host)

    assert url.path == "/api/v3/repos/example/app/pulls"
    assert host.unrouted == []


def test_a_trailing_slash_gives_no_doubled_slash_in_the_doctor_path(
    monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    monkeypatch.setattr(settings, "github_api_url", f"{OTHER}/")

    urls = doctor_urls(workspace)

    assert urls
    assert {url.path for url in urls} == {"/api/v3/user"}
