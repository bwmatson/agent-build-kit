"""The GitHub forge: registering a chain of pull requests as a stack.

GitHub's stacks are an explicit object. Pull requests whose bases happen to
chain are only a candidate, so the forge has to say, in three calls, which
stack a pull request is in, create one from an ordered list, and append to
one. The fake here is `gh` itself: argv in, what `gh api` prints out, shaped
like the REST reference for pull request stacks (every field, nulls included).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from agent_build_kit.forges import RepoId, Stack, StackRefused
from agent_build_kit.forges.github import FORGE

REPO = RepoId(forge="github", account="example", name="app")
STACKS = "repos/example/app/stacks"
# The hosts the API's own links point at, kept apart from the path so the
# no-installation-leaks check does not read a link as a repo slug.
API = "https://api.github.com"
DOCS = "https://docs.github.com"


def _pull(number: int, ref: str, *, merged_at: str | None = None) -> dict[str, Any]:
    return {
        "number": number,
        "state": "closed" if merged_at else "open",
        "draft": False,
        "merged_at": merged_at,
        "head": {"ref": ref, "sha": f"{number:040x}"},
    }


def _stack(number: int, *pulls: dict[str, Any], open_: bool = True) -> dict[str, Any]:
    return {
        "id": 4200 + number,
        "number": number,
        "node_id": f"PRS_kwDOAAAAAc4AAB{number:03d}",
        "url": f"{API}/{STACKS}/{number}",
        "base": {"ref": "main"},
        "open": open_,
        "created_at": "2026-09-28T14:02:11Z",
        "pull_requests": list(pulls),
    }


def _error(status: int, message: str, anchor: str, errors: list | None = None) -> dict:
    body: dict[str, Any] = {
        "message": message,
        "documentation_url": f"{DOCS}/rest/pulls/stacks#{anchor}",
        "status": str(status),
    }
    if errors is not None:
        body["errors"] = errors
    return body


class Request:
    """One `gh api` call, read back the way GitHub would receive it."""

    def __init__(self, args: list[str], stdin: str | None) -> None:
        self.method = ""
        self.path = ""
        self.fields: dict[str, Any] = {}
        rest = iter(args[2:])
        for arg in rest:
            if arg in ("-X", "--method"):
                self.method = next(rest).upper()
            elif arg in ("-f", "-F", "--field", "--raw-field"):
                name, _, value = next(rest).partition("=")
                parsed: Any = int(value) if value.isdigit() else value
                if name.endswith("[]"):
                    self.fields.setdefault(name[:-2], []).append(parsed)
                else:
                    self.fields[name] = parsed
            elif arg in ("-H", "--header", "--jq", "-q", "--template", "-t"):
                next(rest)
            elif arg == "--input":
                self.fields.update(json.loads(stdin or "{}"))
                next(rest)
            elif not arg.startswith("-") and not self.path:
                self.path = arg
        path, _, query = self.path.partition("?")
        self.path = path.lstrip("/")
        for pair in filter(None, query.split("&")):
            name, _, value = pair.partition("=")
            self.fields[name] = int(value) if value.isdigit() else value
        self.method = self.method or ("POST" if self.fields and not query else "GET")


class FakeGh:
    """Answers `gh api` from a table of (method, path) -> responses, in turn.

    A response is `(status, body)`: 2xx prints the body and exits 0, anything
    else prints the error body and `gh: <message> (HTTP <status>)` on stderr and
    exits 1, as `gh api` does.
    """

    def __init__(self, routes: dict[tuple[str, str], list[tuple[int, Any]]]) -> None:
        self.routes = routes
        self.requests: list[Request] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(args, 0, "gho_token\n", "")
        assert args[:2] == ["gh", "api"], f"stacks are REST calls, not {args[:3]}"
        request = Request(args, kwargs.get("input"))
        self.requests.append(request)
        answers = self.routes.get((request.method, request.path))
        assert answers, f"no answer recorded for {request.method} {request.path}"
        status, body = answers.pop(0) if len(answers) > 1 else answers[0]
        text = json.dumps(body)
        if status < 300:
            return subprocess.CompletedProcess(args, 0, text, "")
        return subprocess.CompletedProcess(
            args, 1, text, f"gh: {body['message']} (HTTP {status})\n"
        )


@pytest.fixture
def fake_gh(monkeypatch: pytest.MonkeyPatch):
    def install(routes: dict[tuple[str, str], list[tuple[int, Any]]]) -> FakeGh:
        fake = FakeGh(routes)
        monkeypatch.setattr("agent_build_kit.pipeline.shell.subprocess.run", fake)
        return fake

    return install


def test_github_declares_that_it_has_stacks() -> None:
    """Declared the way `deletes_head_branch_on_merge` is, so no caller has to
    know which host it is talking to."""
    assert FORGE.supports_stacks is True


def test_the_stack_a_pull_request_is_in_is_asked_of_the_host(fake_gh) -> None:
    """Asked, not remembered: the host is the only one that knows whether a
    person has restructured or merged the stack since."""
    fake = fake_gh(
        {
            ("GET", STACKS): [
                (200, [_stack(3, _pull(11, "spec/feature/1"), _pull(12, "spec/feature/2"))])
            ]
        }
    )

    stack = FORGE.stack_of(REPO, 12)

    assert stack == Stack(number=3, open=True, pulls=(11, 12))
    assert fake.requests[0].fields.get("pull_request") == 12


def test_a_pull_request_in_no_stack_is_in_none(fake_gh) -> None:
    fake_gh({("GET", STACKS): [(200, [])]})

    assert FORGE.stack_of(REPO, 11) is None


def test_a_stack_whose_pull_requests_have_all_merged_reads_as_closed(fake_gh) -> None:
    merged = "2026-09-27T09:15:40Z"
    fake_gh(
        {
            ("GET", STACKS): [
                (
                    200,
                    [
                        _stack(
                            2,
                            _pull(8, "spec/feature/1", merged_at=merged),
                            _pull(9, "spec/feature/2", merged_at=merged),
                            open_=False,
                        )
                    ],
                )
            ]
        }
    )

    stack = FORGE.stack_of(REPO, 9)

    assert stack is not None
    assert stack.open is False
    assert stack.pulls == (8, 9)


def test_a_stack_is_created_bottom_first(fake_gh) -> None:
    """The host checks each pull request's base against the head below it, so
    the order is the chain's, bottom to top."""
    fake = fake_gh(
        {
            ("POST", STACKS): [
                (201, _stack(4, _pull(11, "spec/feature/1"), _pull(12, "spec/feature/2")))
            ]
        }
    )

    stack = FORGE.create_stack(REPO, [11, 12])

    assert fake.requests[0].fields["pull_requests"] == [11, 12]
    assert stack == Stack(number=4, open=True, pulls=(11, 12))


def test_a_pull_request_is_appended_to_the_stack_it_names(fake_gh) -> None:
    fake = fake_gh(
        {
            ("POST", f"{STACKS}/4/add"): [
                (
                    200,
                    _stack(
                        4,
                        _pull(11, "spec/feature/1"),
                        _pull(12, "spec/feature/2"),
                        _pull(13, "spec/feature/3"),
                    ),
                )
            ]
        }
    )

    stack = FORGE.add_to_stack(REPO, 4, [13])

    assert fake.requests[0].fields["pull_requests"] == [13]
    assert stack.pulls == (11, 12, 13)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(
            404,
            _error(404, "Not Found", "create-a-pull-request-stack"),
            id="feature-unavailable",
        ),
        pytest.param(
            422,
            _error(
                422,
                "Validation Failed",
                "create-a-pull-request-stack",
                [
                    {
                        "resource": "PullRequestStack",
                        "code": "custom",
                        "message": "Stacks are not enabled for this repository",
                    }
                ],
            ),
            id="repository-ineligible",
        ),
        pytest.param(
            422,
            _error(
                422,
                "Validation Failed",
                "create-a-pull-request-stack",
                [
                    {
                        "resource": "PullRequestStack",
                        "field": "pull_requests",
                        "code": "invalid",
                        "message": "Pull request #12 base ref does not match #11 head ref",
                    }
                ],
            ),
            id="chain-rejected",
        ),
    ],
)
def test_a_refusal_is_raised_with_the_host_s_reason(fake_gh, status: int, body: dict) -> None:
    """Typed, so the caller can record it and move on rather than parse gh's
    stderr; and not concurrent, so it is not retried."""
    fake_gh({("POST", STACKS): [(status, body)]})

    with pytest.raises(StackRefused) as refused:
        FORGE.create_stack(REPO, [11, 12])

    assert refused.value.concurrent is False
    assert str(status) in refused.value.reason
    if "errors" in body:
        assert body["errors"][0]["message"] in refused.value.reason


def test_a_stack_being_changed_by_another_request_is_a_concurrent_refusal(fake_gh) -> None:
    """409 on append: ticks overlap deliberately, so this is the ordinary case
    that is retried, not a failure."""
    fake_gh(
        {
            ("POST", f"{STACKS}/4/add"): [
                (
                    409,
                    _error(409, "Stack is being modified by another request", "add-pull-requests"),
                )
            ]
        }
    )

    with pytest.raises(StackRefused) as refused:
        FORGE.add_to_stack(REPO, 4, [13])

    assert refused.value.concurrent is True


def _answer_every_call(monkeypatch: pytest.MonkeyPatch, answer) -> None:
    """`gh api` answered by `answer(args)`; the token lookup still succeeds."""

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(args, 0, "gho_token\n", "")
        return answer(args)

    monkeypatch.setattr("agent_build_kit.pipeline.shell.subprocess.run", run)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("{}", id="empty-object"),
        pytest.param("<html>502 Bad Gateway</html>", id="not-json"),
        pytest.param(json.dumps({"number": "four", "pull_requests": []}), id="mis-typed"),
        pytest.param(json.dumps({"number": 4, "pull_requests": [{}]}), id="pull-without-number"),
    ],
)
def test_a_2xx_answer_that_is_not_a_stack_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    """The pull request is already open when this is asked, so an answer that
    cannot be read is a refusal the caller records, never a crash that fails
    the unit."""
    _answer_every_call(monkeypatch, lambda args: subprocess.CompletedProcess(args, 0, text, ""))

    with pytest.raises(StackRefused):
        FORGE.create_stack(REPO, [11, 12])
    with pytest.raises(StackRefused):
        FORGE.add_to_stack(REPO, 4, [13])


def test_a_listing_holding_a_mis_shaped_stack_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer_every_call(monkeypatch, lambda args: subprocess.CompletedProcess(args, 0, "[{}]", ""))

    with pytest.raises(StackRefused):
        FORGE.stack_of(REPO, 12)


def test_a_host_that_cannot_be_reached_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(args: list[str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, 30)

    _answer_every_call(monkeypatch, timeout)

    with pytest.raises(StackRefused):
        FORGE.create_stack(REPO, [11, 12])
