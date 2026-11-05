"""Every REST request the GitHub forge makes speaks the one API version the client
library is built for.

The generated methods of the client send `X-GitHub-Api-Version` themselves; a raw
request (the stacks one) sends nothing unless the forge asks. A host that is sent
no version answers in its own default one, so a request that names none can read a
different payload from the rest. The expected version is read from the library's
generated module, never written here, so an upgrade moves the test and the forge
together.

GraphQL is not versioned this way and the signed job-log fetch goes to storage,
not to the GitHub API; both are exempt.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
from githubkit.versions import LATEST_VERSION

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges.base import Label, PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.settings import settings
from tests.check_lists import failed_list
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost, answer, urlhost
from tests.forges.github_logs import JOB, RUN
from tests.forges.github_routes import GRAPHQL, STORAGE, Seen

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
HEADER = "x-github-api-version"

# Public operations that make no REST request, each with its reason. Every other public
# operation is driven below and must make at least one. Each name here is checked to exist and,
# driven, to add no REST request, so one that moves to REST stops escaping the version check.
GRAPHQL_ONLY = {
    "list_prs": "one GraphQL query per page",
    "merge_commit": "one GraphQL read",
}
NO_REQUEST = {
    "api_url": "reads settings",
    "parse_remote": "parses a URL",
    "identity": "reads configuration",
    "config_entry": "builds a dict",
    "web_url": "builds a URL",
    "browse_url": "builds a URL",
    "check_access": "reads the credential only",
    "access_fix": "returns text",
}


def observed_version() -> str:
    """The version a generated method sends, read off its request over the mock transport
    (`find_pr` is `pulls.list`), not off the library's constants."""
    host = GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([])})
    GitHubForge(http=host).find_pr(REPO, head="spec/x/1")
    [call] = host.calls("GET", f"{BASE}/pulls")
    sent = call.headers.get(HEADER)
    assert sent, "a generated request carries a version"
    return sent


def test_the_library_s_latest_version_is_what_its_generated_methods_send() -> None:
    """The forge's raw request takes `LATEST_VERSION`; this ties it to what the generated
    methods really send, so the two cannot drift apart."""
    assert str(LATEST_VERSION) == observed_version()


def host_with_everything() -> GitHubHost:
    rollup = [
        gh.check_run("CI", "CANCELLED", run=123, job=9),
        gh.check_run("pre-commit", "FAILURE", run=RUN, job=JOB),
    ]
    return GitHubHost(
        gh.pull(7, checks=rollup),
        gh.pull(8),
        jobs={RUN: [gh.job(JOB, "pre-commit", "failure", RUN)]},
        job_logs={JOB: gh.JOB_LOG},
        paged={
            f"{BASE}/issues/7/comments": [],
            f"{BASE}/pulls/7/comments": [],
            f"{BASE}/pulls/7/files": [],
            f"{BASE}/pulls/7/reviews": [],
        },
        routes={
            ("PUT", f"{BASE}/pulls/7/merge"): answer({"sha": "b" * 40, "merged": True}),
            ("DELETE", f"{BASE}/git/refs/heads/spec/x/1"): httpx.Response(204),
            ("PATCH", f"{BASE}/pulls/7"): answer({"number": 7, "node_id": "PR_7"}),
            ("POST", f"{BASE}/pulls/7/comments/11/replies"): answer(
                {"id": 12, "node_id": "PRRC_12", "body": "b"}, 201
            ),
            ("POST", f"{BASE}/issues/7/comments"): answer({"id": 13, "node_id": "IC_13"}, 201),
            ("GET", f"{BASE}/commits/{'c' * 40}/check-runs"): answer(
                {"total_count": 0, "check_runs": []}
            ),
        },
    )


def drive(host: GitHubHost) -> dict[str, list[Seen]]:
    """Each driven public operation, by name, with the REST requests it made."""
    forge = GitHubForge(http=host)
    pull = PullRequest(
        number=7, head="spec/x/1", base="main", state="open", checks=failed_list("pre-commit")
    )
    label = Label(name="running", color="d97706", description="Building")
    calls = {
        "find_pr": lambda: forge.find_pr(REPO, head="spec/x/1"),
        "comment_exists": lambda: forge.comment_exists(REPO, 7, "m", "m body"),
        "create_pr": lambda: forge.create_pr(
            REPO, head="spec/x/1", base="main", title="t", body="b"
        ),
        "update_pr": lambda: forge.update_pr(REPO, 7, base="main", body="b"),
        "stack_of": lambda: forge.stack_of(REPO, 7),
        "create_stack": lambda: forge.create_stack(REPO, [7, 8]),
        "add_to_stack": lambda: forge.add_to_stack(REPO, 1, [8]),
        "post_status": lambda: forge.post_status(
            REPO, sha="abc", ok=True, context="c", description="d"
        ),
        "merge_guard": lambda: forge.merge_guard(REPO, branch="main"),
        "pr_files": lambda: forge.pr_files(REPO, 7),
        "pr_changes": lambda: forge.pr_changes(REPO, 7),
        "review_notes": lambda: forge.review_notes(REPO, 7),
        "post_reply": lambda: forge.post_reply(REPO, 7, note_id="11", body="b"),
        "post_comment": lambda: forge.post_comment(REPO, 7, body="b"),
        "rerun_checks": lambda: forge.rerun_checks(REPO, pull),
        "failed_check_logs": lambda: forge.failed_check_logs(REPO, pull),
        "commit_checks": lambda: forge.commit_checks(REPO, "c" * 40),
        "add_label": lambda: forge.add_label(REPO, 7, label),
        "set_exclusive_label": lambda: forge.set_exclusive_label(REPO, 7, label, family=("a",)),
        "remove_label": lambda: forge.remove_label(REPO, 7, "running"),
        "labels_on": lambda: forge.labels_on(REPO, 7),
        "set_draft": lambda: forge.set_draft(REPO, 7, True),
        "merge_pr": lambda: forge.merge_pr(REPO, 7, head="a" * 40),
        "close_pr": lambda: forge.close_pr(REPO, 7),
        "delete_remote_branch": lambda: forge.delete_remote_branch(REPO, "spec/x/1"),
    }
    made: dict[str, list[Seen]] = {}
    for name, call in calls.items():
        before = len(host.seen)
        try:
            call()
        except Exception:  # noqa: BLE001, S110 - a refusal still sent its request
            pass
        made[name] = rest_requests(host, host.seen[before:])
    return made


def rest_requests(host: GitHubHost, seen: list[Seen] | None = None) -> list[Seen]:
    """What reached the GitHub API over REST: not GraphQL, not the log storage."""
    return [
        s
        for s in (host.seen if seen is None else seen)
        if s.path != GRAPHQL and s.host != urlhost(STORAGE)
    ]


def test_every_public_operation_is_driven_or_named_as_making_no_rest_request() -> None:
    # Only what GitHubForge itself defines: not the helpers it inherits from the Forge base.
    public = {
        name
        for name, member in inspect.getmembers(GitHubForge, inspect.isfunction)
        if not name.startswith("_") and member.__qualname__.startswith("GitHubForge.")
    }
    driven = set(drive(host_with_everything()))

    exempt = set(GRAPHQL_ONLY) | set(NO_REQUEST)
    assert not public - driven - exempt, (
        f"neither driven nor exempt: {sorted(public - driven - exempt)}"
    )
    assert not exempt - public, (
        f"exempt names that are not operations now: {sorted(exempt - public)}"
    )
    assert not driven & exempt, f"driven and exempt: {sorted(driven & exempt)}"


def test_every_driven_operation_makes_a_rest_request() -> None:
    made = drive(host_with_everything())

    silent = [name for name, requests in made.items() if not requests]
    assert not silent, (
        f"operations that sent no REST request, so are never version-checked: {silent}"
    )


def test_the_exempt_operations_make_no_rest_request() -> None:
    host = host_with_everything()
    forge = GitHubForge(http=host)
    repo = RepoConfig(path=".", forge="github", slug="example/app")
    calls = {
        "list_prs": lambda: forge.list_prs(REPO),
        "merge_commit": lambda: forge.merge_commit(REPO, 7),
        "api_url": lambda: forge.api_url(settings),
        "parse_remote": lambda: forge.parse_remote("git@github.com:example/app.git"),
        "identity": lambda: forge.identity(repo),
        "config_entry": lambda: forge.config_entry(REPO),
        "web_url": lambda: forge.web_url(REPO, pr=7),
        "browse_url": lambda: forge.browse_url(REPO, branch="main", path="a"),
        "check_access": lambda: forge.check_access(REPO),
        "access_fix": lambda: forge.access_fix(REPO),
    }
    assert set(calls) == set(GRAPHQL_ONLY) | set(NO_REQUEST)

    for name, call in calls.items():
        before = len(host.seen)
        call()
        assert not rest_requests(host, host.seen[before:]), f"{name} made a REST request"


def test_every_rest_request_carries_the_version_the_client_sends() -> None:
    host = host_with_everything()
    expected = observed_version()

    drive(host)

    seen = rest_requests(host)
    assert len(seen) >= 20, "the operations reached the host"
    wrong = [
        f"{s.method} {s.path}: {s.headers.get(HEADER)!r}"
        for s in seen
        if s.headers.get(HEADER) != expected
    ]
    assert not wrong, f"requests without the client's API version {expected}: {wrong}"


def test_the_stacks_requests_are_among_those_checked() -> None:
    host = host_with_everything()

    made = drive(host)

    stacks = [s for name in ("stack_of", "create_stack", "add_to_stack") for s in made[name]]
    assert {s.method for s in stacks} == {"GET", "POST"}
    assert len(stacks) == 3
    assert {s.headers.get(HEADER) for s in stacks} == {observed_version()}


def test_the_job_log_fetch_is_the_one_request_to_the_storage_host() -> None:
    host = host_with_everything()

    drive(host)

    stored = [s for s in host.seen if s.host == urlhost(STORAGE)]
    assert stored, "the log redirect was followed to the storage host"
    assert all(HEADER not in s.headers for s in stored), "the storage host is sent no GitHub header"
