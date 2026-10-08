"""Where the GitHub forge's calls are repeated: only in the retry layer above it. The
forge makes each call once and raises on the first failure; wrapped, the cases the
client's own loop used to cover (a 5xx once, a host that stays down, a rate limit with
and without a hint over the ceiling, GraphQL, creates) behave as the layer decides."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import MAX_DELAY, HostError, HostUnavailable, RateLimited
from tests.fake_clock import FakeClock
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
FILES = ("GET", f"{BASE}/pulls/7/files")
CREATE = ("POST", f"{BASE}/pulls")
ATTEMPTS = 3


@pytest.fixture(autouse=True)
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """What each wait would have been, from the client library and from the layer."""
    slept: list[float] = []
    monkeypatch.setattr("githubkit.core.time.sleep", slept.append)
    return slept


def wrapped(host: GitHubHost, slept: list[float]) -> ResilientForge:
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    return ResilientForge(
        GitHubForge(http=host),
        RetryPolicy(attempts=ATTEMPTS, deadline_seconds=1000.0),
        clock,
        sleep,
    )


# --- the forge on its own makes each call once -------------------------------------


def test_the_forge_does_not_repeat_a_read_that_failed_with_a_5xx(waits: list[float]) -> None:
    host = GitHubHost(routes={FILES: [refusal(503, "down"), answer([{"filename": "a.py"}])]})

    with pytest.raises(HostError):
        GitHubForge(http=host).pr_files(REPO, 7)

    assert len(host.calls(*FILES)) == 1
    assert waits == []


def test_the_forge_does_not_repeat_a_read_that_failed_to_connect(waits: list[float]) -> None:
    host = GitHubHost(
        routes={FILES: [httpx.ConnectError("refused"), answer([{"filename": "a.py"}])]}
    )

    with pytest.raises(HostError):
        GitHubForge(http=host).pr_files(REPO, 7)

    assert len(host.calls(*FILES)) == 1
    assert waits == []


def test_the_forge_does_not_wait_out_a_rate_limit(waits: list[float]) -> None:
    limited = httpx.Response(429, json={"message": "slow down"}, headers={"retry-after": "3"})
    host = GitHubHost(routes={CREATE: [limited, answer({"number": 9}, 201)]})

    with pytest.raises(RateLimited) as caught:
        GitHubForge(http=host).create_pr(REPO, head="h", base="main", title="t", body="b")

    assert caught.value.retry_after == 3
    assert len(host.calls(*CREATE)) == 1
    assert waits == []


def test_the_forge_does_not_repeat_a_graphql_query(waits: list[float]) -> None:
    host = GitHubHost(routes={("POST", "/graphql"): [refusal(502, "bad gateway")]})

    with pytest.raises(HostError):
        GitHubForge(http=host).list_prs(REPO)

    assert len(host.graphql()) == 1
    assert waits == []


# --- wrapped, the layer repeats what its table allows ------------------------------


def test_a_wrapped_read_that_failed_with_a_5xx_is_repeated(waits: list[float]) -> None:
    host = GitHubHost(routes={FILES: [refusal(503, "down"), answer([{"filename": "a.py"}])]})

    assert wrapped(host, waits).pr_files(REPO, 7) == ["a.py"]

    assert len(host.calls(*FILES)) == 2
    assert len(waits) == 1


def test_a_wrapped_read_is_repeated_only_up_to_the_bound(waits: list[float]) -> None:
    host = GitHubHost(routes={FILES: refusal(503, "down")})

    with pytest.raises(HostUnavailable):
        wrapped(host, waits).pr_files(REPO, 7)

    assert len(host.calls(*FILES)) == ATTEMPTS


def test_a_wrapped_graphql_query_that_failed_with_a_5xx_is_repeated(waits: list[float]) -> None:
    host = GitHubHost(routes={("POST", "/graphql"): [refusal(502, "bad gateway")]})

    with pytest.raises(HostUnavailable):
        wrapped(host, waits).list_prs(REPO)

    assert len(host.graphql()) == ATTEMPTS


def test_a_wrapped_rate_limited_create_waits_the_hint_and_is_repeated(waits: list[float]) -> None:
    limited = httpx.Response(429, json={"message": "slow down"}, headers={"retry-after": "3"})
    host = GitHubHost(routes={CREATE: [limited, answer({"number": 9}, 201)]})

    forge = wrapped(host, waits)

    assert forge.create_pr(REPO, head="h", base="main", title="t", body="b") == 9
    assert len(host.calls(*CREATE)) == 2
    assert waits == [3.0]


def test_a_wrapped_wait_longer_than_the_ceiling_fails_at_once(waits: list[float]) -> None:
    limited = httpx.Response(
        429, json={"message": "slow down"}, headers={"retry-after": str(int(MAX_DELAY) + 1)}
    )
    host = GitHubHost(routes={CREATE: limited})

    with pytest.raises(RateLimited) as caught:
        wrapped(host, waits).create_pr(REPO, head="h", base="main", title="t", body="b")

    assert caught.value.retry_after == MAX_DELAY + 1
    assert len(host.calls(*CREATE)) == 1
    assert waits == []
