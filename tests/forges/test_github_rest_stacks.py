"""The GitHub forge registers a chain of pull requests as a stack, through the
stack endpoints.

GitHub's stacks are an explicit object, so the forge says, in three calls, which
stack a pull request is in, creates one from an ordered list, and appends to
one. The host sends what the REST reference documents for pull request stacks:
every field, nulls included.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agent_build_kit.forges.base import RepoId, Stack, StackRefused
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import HostError
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
STACKS = "/repos/example/app/stacks"
# The hosts the API's own links point at, kept apart from the path so the
# no-installation-leaks check does not read a link as a repo slug.
API = "https://api.github.com"


def pull(number: int, ref: str, *, merged_at: str | None = None) -> dict[str, Any]:
    return {
        "number": number,
        "state": "closed" if merged_at else "open",
        "draft": False,
        "merged_at": merged_at,
        "head": {"ref": ref, "sha": f"{number:040x}"},
    }


def stack(number: int, *pulls: dict[str, Any], open_: bool = True) -> dict[str, Any]:
    return {
        "id": 4200 + number,
        "number": number,
        "node_id": f"PRS_kwDOAAAAAc4AAB{number:03d}",
        "url": f"{API}{STACKS}/{number}",
        "base": {"ref": "main"},
        "open": open_,
        "created_at": "2026-09-28T14:02:11Z",
        "pull_requests": list(pulls),
    }


def forge(host: GitHubHost) -> GitHubForge:
    return GitHubForge(http=host)


def test_the_stack_a_pull_request_is_in_is_asked_of_the_host() -> None:
    """Asked, not remembered: the host is the only one that knows whether a
    person has restructured or merged the stack since."""
    host = GitHubHost(
        routes={
            ("GET", STACKS): answer(
                [stack(3, pull(11, "spec/feature/1"), pull(12, "spec/feature/2"))]
            )
        }
    )

    found = forge(host).stack_of(REPO, 12)

    assert found == Stack(number=3, open=True, pulls=(11, 12))
    [call] = host.calls("GET", STACKS)
    assert call.params["pull_request"] == "12"


def test_a_pull_request_in_no_stack_is_in_none() -> None:
    host = GitHubHost(routes={("GET", STACKS): answer([])})

    assert forge(host).stack_of(REPO, 11) is None


def test_a_stack_whose_pull_requests_have_all_merged_reads_as_closed() -> None:
    merged = "2026-09-27T09:15:40Z"
    host = GitHubHost(
        routes={
            ("GET", STACKS): answer(
                [
                    stack(
                        2,
                        pull(8, "spec/feature/1", merged_at=merged),
                        pull(9, "spec/feature/2", merged_at=merged),
                        open_=False,
                    )
                ]
            )
        }
    )

    found = forge(host).stack_of(REPO, 9)

    assert found is not None
    assert found.open is False
    assert found.pulls == (8, 9)


def test_a_stack_is_created_bottom_first() -> None:
    """The host checks each pull request's base against the head below it, so
    the order is the chain's, bottom to top."""
    created = stack(4, pull(11, "spec/feature/1"), pull(12, "spec/feature/2"))
    host = GitHubHost(routes={("POST", STACKS): answer(created, 201)})

    made = forge(host).create_stack(REPO, [11, 12])

    [call] = host.calls("POST", STACKS)
    assert call.body == {"pull_requests": [11, 12]}
    assert made == Stack(number=4, open=True, pulls=(11, 12))


def test_a_pull_request_is_appended_to_the_stack_it_names() -> None:
    longer = stack(
        4,
        pull(11, "spec/feature/1"),
        pull(12, "spec/feature/2"),
        pull(13, "spec/feature/3"),
    )
    host = GitHubHost(routes={("POST", f"{STACKS}/4/add"): answer(longer)})

    made = forge(host).add_to_stack(REPO, 4, [13])

    [call] = host.calls("POST", f"{STACKS}/4/add")
    assert call.body == {"pull_requests": [13]}
    assert made.pulls == (11, 12, 13)


def invalid(message: str, field: str | None = None) -> list[dict]:
    error: dict[str, Any] = {"resource": "PullRequestStack", "code": "invalid", "message": message}
    if field:
        error["field"] = field
    return [error]


@pytest.mark.parametrize(
    ("status", "message", "errors"),
    [
        pytest.param(404, "Not Found", None, id="feature-unavailable"),
        pytest.param(
            422,
            "Validation Failed",
            invalid("Stacks are not enabled for this repository"),
            id="repository-ineligible",
        ),
        pytest.param(
            422,
            "Validation Failed",
            invalid("Pull request #12 base ref does not match #11 head ref", "pull_requests"),
            id="chain-rejected",
        ),
    ],
)
def test_a_refusal_is_raised_with_the_host_s_reason(
    status: int, message: str, errors: list[dict] | None
) -> None:
    """Typed, so the caller can record it and move on rather than parse a
    message; and not concurrent, so it is not retried."""
    host = GitHubHost(routes={("POST", STACKS): refusal(status, message, errors)})

    with pytest.raises(StackRefused) as refused:
        forge(host).create_stack(REPO, [11, 12])

    assert refused.value.concurrent is False
    assert str(status) in refused.value.reason
    if errors:
        assert errors[0]["message"] in refused.value.reason


def test_a_stack_being_changed_by_another_request_is_a_concurrent_refusal() -> None:
    """409 on append: ticks overlap deliberately, so this is the ordinary case
    that is retried, not a failure."""
    conflict = refusal(409, "Stack is being modified by another request")
    host = GitHubHost(routes={("POST", f"{STACKS}/4/add"): conflict})

    with pytest.raises(StackRefused) as refused:
        forge(host).add_to_stack(REPO, 4, [13])

    assert refused.value.concurrent is True


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(answer({}), id="empty-object"),
        pytest.param(
            httpx.Response(200, content="<html>ok</html>", headers={"content-type": "text/html"}),
            id="not-json",
        ),
        pytest.param(answer({"number": "four", "pull_requests": []}), id="mis-typed"),
        pytest.param(answer({"number": 4, "pull_requests": [{}]}), id="pull-without-number"),
    ],
)
def test_a_2xx_answer_that_is_not_a_stack_is_a_refusal(reply: httpx.Response) -> None:
    """The pull request is already open when this is asked, so an answer that
    cannot be read is a refusal the caller records, never a crash that fails
    the unit."""
    host = GitHubHost(routes={("POST", STACKS): reply, ("POST", f"{STACKS}/4/add"): reply})

    with pytest.raises(StackRefused):
        forge(host).create_stack(REPO, [11, 12])
    with pytest.raises(StackRefused):
        forge(host).add_to_stack(REPO, 4, [13])


def test_a_listing_holding_a_mis_shaped_stack_is_a_refusal() -> None:
    host = GitHubHost(routes={("GET", STACKS): answer([{}])})

    with pytest.raises(StackRefused):
        forge(host).stack_of(REPO, 12)


def test_a_host_that_cannot_be_reached_is_left_for_the_retry_layer() -> None:
    host = GitHubHost(routes={("POST", STACKS): httpx.ConnectError("no route to host")})

    with pytest.raises(HostError):
        forge(host).create_stack(REPO, [11, 12])
