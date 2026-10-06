"""When the GitHub forge repeats a call: a rate limit always, a 5xx or a failed
connection for calls that are safe to repeat, never more than the bound, and
never a wait longer than the transport's own ceiling."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import MAX_DELAY, HostError, RateLimited
from agent_build_kit.settings import settings
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
FILES = ("GET", f"{BASE}/pulls/7/files")
CREATE = ("POST", f"{BASE}/pulls")
RETRIES = 2


@pytest.fixture(autouse=True)
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Retries without the waiting: what each wait would have been."""
    slept: list[float] = []
    monkeypatch.setattr("githubkit.core.time.sleep", slept.append)
    monkeypatch.setattr(settings, "forge_retries", RETRIES)
    return slept


def create(host: GitHubHost) -> int:
    return GitHubForge(http=host).create_pr(REPO, head="h", base="main", title="t", body="b")


def test_a_read_that_failed_with_a_5xx_is_repeated(waits: list[float]) -> None:
    host = GitHubHost(routes={FILES: [refusal(503, "down"), answer([{"filename": "a.py"}])]})

    assert GitHubForge(http=host).pr_files(REPO, 7) == ["a.py"]

    assert len(host.calls(*FILES)) == 2
    assert len(waits) == 1


def test_a_read_is_repeated_only_up_to_the_bound() -> None:
    host = GitHubHost(routes={FILES: refusal(503, "down")})

    with pytest.raises(HostError):
        GitHubForge(http=host).pr_files(REPO, 7)

    assert len(host.calls(*FILES)) == RETRIES + 1


def test_a_read_that_failed_to_connect_is_repeated() -> None:
    host = GitHubHost(
        routes={FILES: [httpx.ConnectError("refused"), answer([{"filename": "a.py"}])]}
    )

    assert GitHubForge(http=host).pr_files(REPO, 7) == ["a.py"]

    assert len(host.calls(*FILES)) == 2


def test_a_create_that_failed_with_a_5xx_is_not_repeated() -> None:
    """A timeout may have created the pull request already."""
    host = GitHubHost(routes={CREATE: [refusal(502, "bad gateway"), answer({"number": 9}, 201)]})

    with pytest.raises(HostError):
        create(host)

    assert len(host.calls(*CREATE)) == 1


def test_a_rate_limited_create_is_repeated(waits: list[float]) -> None:
    """The host refused it before doing anything."""
    limited = httpx.Response(429, json={"message": "slow down"}, headers={"retry-after": "3"})
    host = GitHubHost(routes={CREATE: [limited, answer({"number": 9}, 201)]})

    assert create(host) == 9

    assert len(host.calls(*CREATE)) == 2
    assert waits == [3.0]


def test_a_wait_longer_than_the_ceiling_fails_at_once(waits: list[float]) -> None:
    limited = httpx.Response(
        429, json={"message": "slow down"}, headers={"retry-after": str(int(MAX_DELAY) + 1)}
    )
    host = GitHubHost(routes={CREATE: limited})

    with pytest.raises(RateLimited) as caught:
        create(host)

    assert caught.value.retry_after == MAX_DELAY + 1
    assert len(host.calls(*CREATE)) == 1
    assert waits == []


def test_a_graphql_query_that_failed_with_a_5xx_is_repeated() -> None:
    host = GitHubHost(routes={("POST", "/graphql"): [refusal(502, "bad gateway")]})

    with pytest.raises(HostError):
        GitHubForge(http=host).list_prs(REPO)

    assert len(host.graphql()) == RETRIES + 1
