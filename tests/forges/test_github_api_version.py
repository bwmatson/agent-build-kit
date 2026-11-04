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
from githubkit import GitHub

from agent_build_kit.forges.base import Label, PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.check_lists import failed_list
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost, answer, urlhost
from tests.forges.github_logs import JOB, RUN
from tests.forges.github_routes import GRAPHQL, STORAGE, Seen

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
HEADER = "x-github-api-version"

# Public operations of the forge that make no REST request, each with its reason.
# Every other public operation is driven below and must reach the host over REST.
NO_REST = {
    "api_url": "reads settings",
    "parse_remote": "parses a URL",
    "identity": "reads configuration",
    "config_entry": "builds a dict",
    "web_url": "builds a URL",
    "browse_url": "builds a URL",
    "check_access": "GraphQL only",
    "access_fix": "returns text",
    "list_prs": "GraphQL only",
    "merge_commit": "GraphQL only",
}


def client_version() -> str:
    """The version the client's generated methods send: read off the generated
    namespace `gh.rest` resolves to, which is the one the forge calls."""
    client = GitHub("token")
    return str(client.rest.pulls._REST_API_VERSION)  # pyrefly: ignore[missing-attribute]


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
        },
    )


def drive(forge: GitHubForge) -> dict[str, object]:
    """Each public operation that reaches the host, by name, with what it answered."""
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
        "add_label": lambda: forge.add_label(REPO, 7, label),
        "set_exclusive_label": lambda: forge.set_exclusive_label(REPO, 7, label, family=("a",)),
        "remove_label": lambda: forge.remove_label(REPO, 7, "running"),
        "labels_on": lambda: forge.labels_on(REPO, 7),
        "set_draft": lambda: forge.set_draft(REPO, 7, True),
        "merge_pr": lambda: forge.merge_pr(REPO, 7, head="a" * 40),
        "close_pr": lambda: forge.close_pr(REPO, 7),
        "delete_remote_branch": lambda: forge.delete_remote_branch(REPO, "spec/x/1"),
    }
    answers: dict[str, object] = {}
    for name, call in calls.items():
        try:
            answers[name] = call()
        except Exception as error:  # noqa: BLE001 - a refusal still sent its request
            answers[name] = error
    return answers


def rest_requests(host: GitHubHost) -> list[Seen]:
    """What reached the GitHub API over REST: not GraphQL, not the log storage."""
    return [s for s in host.seen if s.path != GRAPHQL and s.host != urlhost(STORAGE)]


def test_every_public_operation_is_driven_or_named_as_making_no_rest_request() -> None:
    public = {
        name
        for name, member in inspect.getmembers(GitHubForge, inspect.isfunction)
        if not name.startswith("_") and member.__qualname__.startswith("GitHubForge.")
    }
    # The Forge base's own helpers are not the forge's operations.
    probe = drive(GitHubForge(http=host_with_everything()))

    unlisted = public - set(probe) - set(NO_REST)
    assert not unlisted, f"operations neither driven nor exempt, with a reason: {sorted(unlisted)}"


def test_every_rest_request_carries_the_version_the_client_sends() -> None:
    host = host_with_everything()

    drive(GitHubForge(http=host))

    seen = rest_requests(host)
    assert len(seen) >= 20, "the operations reached the host"
    wrong = [
        f"{s.method} {s.path}: {s.headers.get(HEADER)!r}"
        for s in seen
        if s.headers.get(HEADER) != client_version()
    ]
    assert not wrong, f"requests without the client's API version {client_version()}: {wrong}"


def test_the_stacks_requests_are_among_those_checked() -> None:
    host = host_with_everything()

    drive(GitHubForge(http=host))

    stacks = [s for s in rest_requests(host) if "/stacks" in s.path]
    assert {s.method for s in stacks} == {"GET", "POST"}
    assert len(stacks) == 3
    assert {s.headers.get(HEADER) for s in stacks} == {client_version()}


def test_the_job_log_fetch_is_the_one_request_to_the_storage_host() -> None:
    host = host_with_everything()

    drive(GitHubForge(http=host))

    stored = [s for s in host.seen if s.host == urlhost(STORAGE)]
    assert stored, "the log redirect was followed to the storage host"
    assert all(HEADER not in s.headers for s in stored), "the storage host is sent no GitHub header"
