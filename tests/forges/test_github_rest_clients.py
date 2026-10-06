"""How the GitHub forge reaches the host: no process for any operation, a client
per owner with that owner's credential, no HTTP caching, and a timeout on every
call.

All of it is read off the requests that arrive at the stand-in host, and off
the processes that were or were not started.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from githubkit import GitHub

from agent_build_kit.forges.base import Label, PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.settings import settings
from tests.forges import github_answers as gh
from tests.forges.conftest import GH_TOKEN
from tests.forges.github_host import HOSTS, GitHubHost, answer

REPO = RepoId(forge="github", account="example", name="app")
OTHER = RepoId(forge="github", account="other", name="platform")
BASE = "/repos/example/app"


# --- no process -------------------------------------------------------------------


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    """Every process started, recorded rather than refused, so the operations
    that fail for want of an answer still count."""
    launched: list[object] = []

    def record(argv, *args, **kwargs):
        launched.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(settings, "gh_token", GH_TOKEN)
    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setattr(subprocess, "Popen", record)
    HOSTS.clear()
    clear_credentials()
    yield launched
    clear_credentials()
    HOSTS.clear()


def operations(forge: GitHubForge) -> dict[str, Callable[[], object]]:
    pull = PullRequest(number=7, head="spec/x/1", base="main", state="open", failing_checks=("CI",))
    label = Label(name="running", color="d97706", description="Building")
    return {
        "find_pr": lambda: forge.find_pr(REPO, head="spec/x/1"),
        "create_pr": lambda: forge.create_pr(
            REPO, head="spec/x/1", base="main", title="t", body="b"
        ),
        "update_pr": lambda: forge.update_pr(REPO, 7, base="main", body="b"),
        "list_prs": lambda: forge.list_prs(REPO),
        "pr_files": lambda: forge.pr_files(REPO, 7),
        "review_notes": lambda: forge.review_notes(REPO, 7),
        "post_reply": lambda: forge.post_reply(REPO, 7, note_id="11", body="b"),
        "post_comment": lambda: forge.post_comment(REPO, 7, body="b"),
        "post_status": lambda: forge.post_status(
            REPO, sha="abc", ok=True, context="c", description="d"
        ),
        "merge_guard": lambda: forge.merge_guard(REPO, branch="main"),
        "rerun_checks": lambda: forge.rerun_checks(REPO, pull),
        "failed_check_logs": lambda: forge.failed_check_logs(REPO, pull),
        "add_label": lambda: forge.add_label(REPO, 7, label),
        "set_exclusive_label": lambda: forge.set_exclusive_label(REPO, 7, label, family=("a",)),
        "remove_label": lambda: forge.remove_label(REPO, 7, "running"),
        "set_draft": lambda: forge.set_draft(REPO, 7, True),
        "close_pr": lambda: forge.close_pr(REPO, 7),
        "delete_remote_branch": lambda: forge.delete_remote_branch(REPO, "spec/x/1"),
        "stack_of": lambda: forge.stack_of(REPO, 7),
        "create_stack": lambda: forge.create_stack(REPO, [7, 8]),
        "add_to_stack": lambda: forge.add_to_stack(REPO, 1, [9]),
    }


def test_no_operation_starts_a_process(started: list[object]) -> None:
    host = GitHubHost()  # every route is unknown: each call is refused, and that is enough
    forge = GitHubForge(http=host)

    for name, call in operations(forge).items():
        try:
            call()
        except Exception as error:  # noqa: BLE001 - the answer is not what is being checked
            assert "subprocess" not in str(error), name
    host.unrouted.clear()

    assert started == [], f"a process was started: {started}"
    assert len(host.seen) >= len(operations(forge)), "every operation reached the host"


# --- a client per owner -----------------------------------------------------------


class Cli:
    """`gh` as a subprocess stand-in that only knows how to print a token: one
    per logged-in owner, and anything else it is asked is a failure."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self.tokens = tokens
        self.commands: list[list[str]] = []

    def __call__(self, argv, *args, **kwargs):
        self.commands.append(list(argv))
        assert argv[:3] == ["gh", "auth", "token"], f"only a credential is read from gh: {argv}"
        token = self.tokens.get(argv[argv.index("--user") + 1])
        if token is None:
            return subprocess.CompletedProcess(argv, 1, "", "no account")
        return subprocess.CompletedProcess(argv, 0, f"{token}\n", "")


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> Iterator[Cli]:
    fake = Cli({"example": "tok-example", "other": "tok-other"})
    monkeypatch.setattr(settings, "gh_token", "")
    monkeypatch.setattr("agent_build_kit.pipeline.shell.subprocess.run", fake)
    HOSTS.clear()
    clear_credentials()
    yield fake
    clear_credentials()
    HOSTS.clear()


def two_owners() -> GitHubHost:
    return GitHubHost(
        routes={
            ("GET", "/repos/example/app/pulls"): answer([{"number": 1}]),
            ("GET", "/repos/other/platform/pulls"): answer([{"number": 2}]),
        }
    )


def token_of(call) -> str:
    return call.headers["authorization"].split()[-1]


def test_each_owner_s_calls_carry_that_owner_s_credential(cli: Cli) -> None:
    host = two_owners()
    forge = GitHubForge(http=host)

    assert forge.find_pr(REPO, head="spec/x/1") == 1
    assert forge.find_pr(OTHER, head="spec/x/1") == 2

    [mine] = host.calls("GET", "/repos/example/app/pulls")
    [theirs] = host.calls("GET", "/repos/other/platform/pulls")
    assert token_of(mine) == "tok-example"
    assert token_of(theirs) == "tok-other"


def test_units_for_two_owners_at_once_each_use_their_own_credential(cli: Cli) -> None:
    host = two_owners()
    forge = GitHubForge(http=host)

    def ask(repo: RepoId) -> int | None:
        return forge.find_pr(repo, head="spec/x/1")

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(ask, [REPO, OTHER] * 8))

    assert found == [1, 2] * 8
    for call in host.seen:
        owner = call.path.split("/")[2]
        assert token_of(call) == f"tok-{owner}", call


def test_an_owner_s_credential_is_read_from_the_cli_once(cli: Cli) -> None:
    host = two_owners()
    forge = GitHubForge(http=host)

    for _ in range(3):
        forge.find_pr(REPO, head="spec/x/1")
        forge.find_pr(OTHER, head="spec/x/1")

    users = sorted(c[c.index("--user") + 1] for c in cli.commands)
    assert users == ["example", "other"]


def test_the_configured_token_is_used_for_every_owner(
    cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "gh_token", "tok-setting")
    clear_credentials()
    host = two_owners()
    forge = GitHubForge(http=host)

    forge.find_pr(REPO, head="spec/x/1")
    forge.find_pr(OTHER, head="spec/x/1")

    assert {token_of(c) for c in host.seen} == {"tok-setting"}
    assert cli.commands == []


# --- determinism ------------------------------------------------------------------


@pytest.mark.usefixtures("github_env")
def test_http_caching_is_off() -> None:
    """A conditional request answered 304 would hand back an earlier answer: the
    second read must be a full one, and say what the host says now."""
    turns = iter(
        [
            [{"id": 1, "node_id": "PRR_1", "state": "COMMENTED", "body": "first"}],
            [{"id": 2, "node_id": "PRR_2", "state": "COMMENTED", "body": "second"}],
        ]
    )

    def reviews(request: httpx.Request) -> httpx.Response:
        if "if-none-match" in request.headers or "if-modified-since" in request.headers:
            return httpx.Response(304)
        return answer(next(turns), headers={"etag": '"same"', "last-modified": "Mon, 28 Sep 2026"})

    host = GitHubHost(
        routes={
            ("GET", f"{BASE}/pulls/7/reviews"): reviews,
            ("GET", f"{BASE}/pulls/7/comments"): answer([]),
        }
    )
    forge = GitHubForge(http=host)

    first = forge.review_notes(REPO, 7)
    second = forge.review_notes(REPO, 7)

    assert [n.body for n in first] == ["first"]
    assert [n.body for n in second] == ["second"]
    for call in host.seen:
        assert "if-none-match" not in call.headers
        assert "if-modified-since" not in call.headers


@pytest.mark.usefixtures("github_env")
def test_the_client_is_built_with_caching_off_and_the_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[dict] = []

    def spy(*args, **kwargs):
        built.append(kwargs)
        return GitHub(*args, **kwargs)

    monkeypatch.setattr("agent_build_kit.forges.github.GitHub", spy)
    monkeypatch.setattr(settings, "forge_timeout_seconds", 7.0)
    forge = GitHubForge(http=two_owners())

    forge.find_pr(REPO, head="spec/x/1")
    forge.find_pr(REPO, head="spec/x/2")

    assert len(built) == 1, "one client for the owner, however many calls"
    [kwargs] = built
    assert kwargs["http_cache"] is False
    assert kwargs["timeout"] == 7.0


@pytest.mark.usefixtures("github_env")
def test_every_call_has_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "forge_timeout_seconds", 7.0)
    host = GitHubHost(gh.pull(1), routes={("GET", f"{BASE}/pulls"): answer([{"number": 1}])})
    forge = GitHubForge(http=host)

    forge.list_prs(REPO)
    forge.find_pr(REPO, head="spec/x/1")

    assert len(host.seen) == 2
    for call in host.seen:
        timeout = call.request.extensions["timeout"]
        assert timeout == {"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}
