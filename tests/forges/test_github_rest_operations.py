"""Every write and read the GitHub forge makes is a call through the typed
client, and none starts a process.

The host is the GitHub stand-in, so what is checked is the request the forge
sends (method, resource, body) and what it makes of the answer. The `github_env`
fixture fails the test if a subprocess is started.
"""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.base import BaseMissing, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
HEAD = "spec/add-marker/1"


def forge(host: GitHubHost) -> GitHubForge:
    return GitHubForge(http=host)


# --- creating and finding ---------------------------------------------------------


def created(number: int = 7) -> httpx.Response:
    return answer(
        {
            "number": number,
            "node_id": f"PR_kwDOAAAAAc{number:08d}",
            "state": "open",
            "html_url": f"https://github.com/example/app/pull/{number}",
            "head": {"ref": HEAD},
            "base": {"ref": "main"},
        },
        201,
    )


def test_creating_a_pull_request_posts_its_head_base_title_and_body() -> None:
    host = GitHubHost(routes={("POST", f"{BASE}/pulls"): created(7)})

    number = forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert number == 7
    [call] = host.calls("POST", f"{BASE}/pulls")
    assert call.body == {"head": HEAD, "base": "main", "title": "t", "body": "b"}


def test_a_base_the_host_does_not_have_is_its_own_error() -> None:
    """A parent's branch removed on merge: the unit moves onto its current base
    rather than failing. Another refusal is still a plain failure."""
    missing = refusal(
        422,
        "Validation Failed",
        [{"resource": "PullRequest", "field": "base", "code": "invalid"}],
    )
    host = GitHubHost(routes={("POST", f"{BASE}/pulls"): missing})

    with pytest.raises(BaseMissing):
        forge(host).create_pr(REPO, head=HEAD, base="spec/x/0", title="t", body="b")


def test_another_refusal_is_a_failure_that_is_not_a_missing_base() -> None:
    exists = refusal(
        422,
        "Validation Failed",
        [
            {
                "resource": "PullRequest",
                "code": "custom",
                "message": "A pull request already exists for example:spec/add-marker/1.",
            }
        ],
    )
    host = GitHubHost(routes={("POST", f"{BASE}/pulls"): exists})

    with pytest.raises(RuntimeError) as refused:
        forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert not isinstance(refused.value, BaseMissing)
    assert "already exists" in str(refused.value)


def test_a_title_quoting_the_missing_base_does_not_make_another_refusal_one() -> None:
    """What the host said decides whether the base is missing, not what was
    sent."""
    exists = refusal(
        422,
        "Validation Failed",
        [
            {
                "resource": "PullRequest",
                "code": "custom",
                "message": "A pull request already exists.",
            }
        ],
    )
    host = GitHubHost(routes={("POST", f"{BASE}/pulls"): exists})

    with pytest.raises(RuntimeError) as refused:
        forge(host).create_pr(
            REPO,
            head=HEAD,
            base="main",
            title="Base ref must be a branch",
            body="Base sha can't be blank, field base invalid",
        )

    assert not isinstance(refused.value, BaseMissing)


def test_finding_a_pull_request_by_branch_asks_for_it_in_the_repository() -> None:
    host = GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([{"number": 11}])})

    assert forge(host).find_pr(REPO, head=HEAD) == 11

    [call] = host.calls("GET", f"{BASE}/pulls")
    assert call.params["head"] == f"example:{HEAD}"
    assert call.params["state"] == "all"


def test_a_lookup_that_finds_nothing_or_nothing_usable_reads_as_no_pull_request_yet() -> None:
    """A malformed answer must not read as a number: a second pull request for
    the same branch is the failure this prevents."""
    assert (
        forge(GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([])})).find_pr(REPO, head=HEAD)
        is None
    )
    odd = GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([{"unexpected": True}])})
    assert forge(odd).find_pr(REPO, head=HEAD) is None


# --- editing ----------------------------------------------------------------------


def test_retargeting_patches_the_base() -> None:
    host = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): answer({"number": 7})})

    forge(host).update_pr(REPO, 7, base="main")

    [call] = host.calls("PATCH", f"{BASE}/pulls/7")
    assert call.body == {"base": "main"}


def test_a_new_body_is_patched_and_an_unchanged_one_is_not_sent() -> None:
    host = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): answer({"number": 7})})

    forge(host).update_pr(REPO, 7, body="Now with a diagram.")

    [call] = host.calls("PATCH", f"{BASE}/pulls/7")
    assert call.body == {"body": "Now with a diagram."}


def test_an_update_the_host_refuses_does_not_raise() -> None:
    """Not worth failing a restack over."""
    host = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): refusal(422, "Validation Failed")})

    forge(host).update_pr(REPO, 7, base="main")

    assert host.calls("PATCH", f"{BASE}/pulls/7")


def test_closing_patches_the_state_and_a_refusal_raises() -> None:
    host = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): answer({"number": 7})})
    forge(host).close_pr(REPO, 7)
    [call] = host.calls("PATCH", f"{BASE}/pulls/7")
    assert call.body == {"state": "closed"}

    gone = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): refusal(404, "Not Found")})
    with pytest.raises(RuntimeError):
        forge(gone).close_pr(REPO, 7)


# --- files, notes, replies and comments -------------------------------------------


def test_the_files_of_a_pull_request_are_read_across_pages() -> None:
    files = [{"filename": f"src/f{i}.py", "status": "modified", "sha": "0" * 40} for i in range(5)]
    host = GitHubHost(paged={f"{BASE}/pulls/7/files": files}, page_size=2)

    found = forge(host).pr_files(REPO, 7)

    assert found == [f"src/f{i}.py" for i in range(5)]


def inline(id_: int, *, line: int | None, body: str) -> dict:
    return {
        "id": id_,
        "node_id": f"PRRC_{id_}",
        "pull_request_review_id": 900 + id_,
        "path": "src/app.py",
        "line": line,
        "original_line": 10,
        "body": body,
        "user": {"login": "reviewer"},
        "created_at": "2026-09-28T10:00:00Z",
    }


def test_the_reviewers_words_are_review_bodies_then_inline_comments_across_pages() -> None:
    reviews = [
        {"id": 31, "node_id": "PRR_31", "state": "CHANGES_REQUESTED", "body": "needs work"},
        {"id": 32, "node_id": "PRR_32", "state": "COMMENTED", "body": None},
    ]
    comments = [
        inline(11, line=12, body="rename this"),
        inline(12, line=None, body="already addressed"),
        inline(13, line=40, body="and this"),
    ]
    host = GitHubHost(
        paged={f"{BASE}/pulls/17/reviews": reviews, f"{BASE}/pulls/17/comments": comments},
        page_size=2,
    )

    notes = forge(host).review_notes(REPO, 17)

    assert [(n.id, n.body, n.path, n.line, n.live) for n in notes] == [
        ("31", "needs work", "", None, False),
        ("32", "", "", None, False),
        ("11", "rename this", "src/app.py", 12, True),
        ("12", "already addressed", "src/app.py", None, False),
        ("13", "and this", "src/app.py", 40, True),
    ]


def test_a_reply_goes_to_the_comment_s_thread_and_reports_both_ids() -> None:
    """A reply creates a review of its own with an empty body, which the poller
    would read as new feedback: its id comes back too, to be recorded as the
    pipeline's own."""
    reply = {**inline(21, line=12, body="Now a frozen BaseModel."), "node_id": "PRRC_11"}
    reply["pull_request_review_id"] = 911
    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/pulls/17/comments/11/replies"): answer(reply, 201),
            ("GET", f"{BASE}/pulls/17/reviews/911"): answer(
                {"id": 911, "node_id": "PRR_911", "state": "COMMENTED", "body": ""}
            ),
        }
    )

    ids = forge(host).post_reply(REPO, 17, note_id="11", body="Now a frozen BaseModel.")

    assert ids == ["PRRC_11", "PRR_911"]
    [call] = host.calls("POST", f"{BASE}/pulls/17/comments/11/replies")
    assert call.body == {"body": "Now a frozen BaseModel."}


def test_a_summary_is_one_comment_on_the_pull_request() -> None:
    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/issues/17/comments"): answer(
                {"id": 5, "node_id": "IC_summary", "body": "Also dropped the /mcp key."}, 201
            )
        }
    )

    ids = forge(host).post_comment(REPO, 17, body="Also dropped the /mcp key.")

    assert ids == ["IC_summary"]
    [call] = host.calls("POST", f"{BASE}/issues/17/comments")
    assert call.body == {"body": "Also dropped the /mcp key."}


# --- statuses, protection and branches --------------------------------------------


def status_route(sha: str) -> dict:
    return {("POST", f"{BASE}/statuses/{sha}"): answer({"id": 1, "state": "success"}, 201)}


def test_a_status_names_the_tested_commit_and_is_truncated() -> None:
    """GitHub rejects a description over 139 characters outright, which would
    lose the whole status rather than the tail of a sentence."""
    host = GitHubHost(routes=status_route("abc1234def"))

    forge(host).post_status(
        REPO, sha="abc1234def", ok=True, context="local/tier2", description="x" * 200
    )

    [call] = host.calls("POST", f"{BASE}/statuses/abc1234def")
    assert call.body == {"state": "success", "context": "local/tier2", "description": "x" * 139}


def test_a_failed_run_is_a_failure_status() -> None:
    host = GitHubHost(routes=status_route("abc1234def"))

    forge(host).post_status(
        REPO, sha="abc1234def", ok=False, context="local/tier2", description="d"
    )

    [call] = host.calls("POST", f"{BASE}/statuses/abc1234def")
    assert call.body["state"] == "failure"


def test_a_protected_branch_has_a_merge_guard() -> None:
    protection = answer({"url": "https://api.github.com/x", "required_status_checks": None})
    host = GitHubHost(routes={("GET", f"{BASE}/branches/main/protection"): protection})

    assert forge(host).merge_guard(REPO, branch="main") == ""


@pytest.mark.parametrize(
    "reply",
    [
        refusal(404, "Branch not protected"),
        refusal(
            403, "Upgrade to GitHub Pro or make this repository public to enable this feature."
        ),
    ],
    ids=["unprotected", "free-private-repository"],
)
def test_a_branch_without_protection_says_so(reply: httpx.Response) -> None:
    """On a free private repository the honest answer is "nothing", which is
    worth saying out loud: the policy hook is then the only guard."""
    host = GitHubHost(routes={("GET", f"{BASE}/branches/main/protection"): reply})

    assert forge(host).merge_guard(REPO, branch="main") == "no branch protection on main"


def test_deleting_a_remote_branch_deletes_its_ref_and_never_raises() -> None:
    ref = f"{BASE}/git/refs/heads/{HEAD}"
    host = GitHubHost(routes={("DELETE", ref): httpx.Response(204)})
    forge(host).delete_remote_branch(REPO, HEAD)
    assert host.calls("DELETE", ref)

    gone = GitHubHost(routes={("DELETE", ref): refusal(422, "Reference does not exist")})
    forge(gone).delete_remote_branch(REPO, HEAD)
    assert gone.calls("DELETE", ref)
