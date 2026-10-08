"""The reads that make a GitHub create safe to repeat: a lookup that says "none"
only when the host did, a duplicate create that finds the pull request already
there, and a question whether a comment already landed.

The host is the GitHub stand-in, so what is checked is the request the forge
sends and what it makes of the raw answer.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agent_build_kit.forges.base import BaseMissing, RepoId, Stack
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import TransportError
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
HEAD = "spec/add-marker/1"
MARKER = "<!-- spec-driven:reply -->"
API = "https://api.github.com"


def forge(host: GitHubHost) -> GitHubForge:
    return GitHubForge(http=host)


# --- find_pr: none, or could not tell ----------------------------------------------


def test_an_empty_answer_is_no_pull_request() -> None:
    host = GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([])})

    assert forge(host).find_pr(REPO, head=HEAD) is None


def test_the_pull_request_the_host_lists_is_found() -> None:
    host = GitHubHost(routes={("GET", f"{BASE}/pulls"): answer([{"number": 11}])})

    assert forge(host).find_pr(REPO, head=HEAD) == 11


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(refusal(403, "Resource not accessible by personal access token"), id="403"),
        pytest.param(refusal(404, "Not Found"), id="404"),
        pytest.param(refusal(422, "Validation Failed"), id="422"),
        pytest.param(refusal(500, "Server Error"), id="500"),
        pytest.param(refusal(502, "Bad Gateway"), id="502"),
        pytest.param(httpx.ConnectError("no route to host"), id="unreachable"),
        pytest.param(answer([{"unexpected": True}]), id="not-a-pull-request"),
        pytest.param(answer({"message": "not a list"}), id="not-a-list"),
        pytest.param(
            httpx.Response(200, content="<html>ok</html>", headers={"content-type": "text/html"}),
            id="not-json",
        ),
    ],
)
def test_a_lookup_that_could_not_tell_raises_rather_than_reading_as_none(reply: Any) -> None:
    """A second pull request for the branch is what "none" would let be made."""
    host = GitHubHost(routes={("GET", f"{BASE}/pulls"): reply})

    with pytest.raises(TransportError):
        forge(host).find_pr(REPO, head=HEAD)


# --- a create refused as a duplicate -----------------------------------------------


def exists_refusal() -> httpx.Response:
    return refusal(
        422,
        "Validation Failed",
        [
            {
                "resource": "PullRequest",
                "code": "custom",
                "message": f"A pull request already exists for example:{HEAD}.",
            }
        ],
    )


def test_a_create_refused_as_a_duplicate_returns_the_existing_pull_request() -> None:
    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/pulls"): exists_refusal(),
            ("GET", f"{BASE}/pulls"): answer([{"number": 11}]),
        }
    )

    number = forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert number == 11
    [lookup] = host.calls("GET", f"{BASE}/pulls")
    assert lookup.params["head"] == f"example:{HEAD}"


def test_a_missing_base_is_still_base_missing_when_a_pull_request_exists() -> None:
    missing = refusal(
        422,
        "Validation Failed",
        [{"resource": "PullRequest", "field": "base", "code": "invalid"}],
    )
    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/pulls"): missing,
            ("GET", f"{BASE}/pulls"): answer([{"number": 11}]),
        }
    )

    with pytest.raises(BaseMissing):
        forge(host).create_pr(REPO, head=HEAD, base="spec/x/0", title="t", body="b")

    assert not host.calls("GET", f"{BASE}/pulls")


def test_another_validation_refusal_is_still_a_plain_failure() -> None:
    other = refusal(
        422,
        "Validation Failed",
        [{"resource": "PullRequest", "code": "custom", "message": "No commits between."}],
    )
    host = GitHubHost(routes={("POST", f"{BASE}/pulls"): other})

    with pytest.raises(TransportError) as refused:
        forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert not isinstance(refused.value, BaseMissing)
    assert "No commits between" in str(refused.value)


def test_a_duplicate_whose_lookup_cannot_tell_raises() -> None:
    host = GitHubHost(
        routes={
            ("POST", f"{BASE}/pulls"): exists_refusal(),
            ("GET", f"{BASE}/pulls"): refusal(403, "Forbidden"),
        }
    )

    with pytest.raises(TransportError):
        forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")


# --- comment_exists over recorded listings -----------------------------------------

USER = {
    "login": "example-bot",
    "id": 41898282,
    "node_id": "MDM6Qm90NDE4OTgyODI=",
    "type": "Bot",
    "site_admin": False,
}
REACTIONS = {"url": f"{API}{BASE}/issues/comments/1/reactions", "total_count": 0}
BODY = f"Fixed in a1b2c3d4e.\n\n<sub>spec-driven rework, in a1b2c3d4e</sub>\n{MARKER}"


def issue_comment(number: int, body: str, node: str) -> dict[str, Any]:
    """A pull request conversation comment as the issues API lists it."""
    return {
        "url": f"{API}{BASE}/issues/comments/{number}",
        "html_url": f"https://github.com/example/app/pull/7#issuecomment-{number}",
        "issue_url": f"{API}{BASE}/issues/7",
        "id": number,
        "node_id": node,
        "user": USER,
        "created_at": "2026-09-28T09:21:00Z",
        "updated_at": "2026-09-28T09:21:00Z",
        "author_association": "CONTRIBUTOR",
        "body": body,
        "reactions": REACTIONS,
        "performed_via_github_app": None,
    }


def review_comment(
    number: int, body: str, node: str, *, reply_to: int | None = None
) -> dict[str, Any]:
    """An inline comment as the pulls API lists it: a reply names its parent,
    a top-level comment has no such field at all."""
    found: dict[str, Any] = {
        "url": f"{API}{BASE}/pulls/comments/{number}",
        "pull_request_review_id": 900 + number,
        "id": number,
        "node_id": node,
        "diff_hunk": "@@ -1,3 +1,4 @@",
        "path": "src/app.py",
        "commit_id": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        "original_commit_id": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        "user": USER,
        "body": body,
        "created_at": "2026-09-28T09:20:00Z",
        "updated_at": "2026-09-28T09:20:00Z",
        "html_url": f"https://github.com/example/app/pull/7#discussion_r{number}",
        "pull_request_url": f"{API}{BASE}/pulls/7",
        "author_association": "CONTRIBUTOR",
        "line": None,
        "original_line": 14,
        "side": "RIGHT",
        "reactions": REACTIONS,
    }
    if reply_to is not None:
        found["in_reply_to_id"] = reply_to
    return found


def test_a_comment_is_found_by_its_marker_and_exact_body() -> None:
    listing = [
        issue_comment(101, "Looks fine to me.", "IC_kwDOAAAAAc4AAAAB"),
        issue_comment(102, BODY, "IC_kwDOAAAAAc4AAAAC"),
    ]
    host = GitHubHost(paged={f"{BASE}/issues/7/comments": listing})

    assert forge(host).comment_exists(REPO, 7, MARKER, BODY) == "IC_kwDOAAAAAc4AAAAC"


def test_a_comment_on_a_later_page_is_found() -> None:
    listing = [issue_comment(n, f"note {n}", f"IC_kwDOAAAAAc4AAA{n}") for n in range(101, 106)]
    listing.append(issue_comment(106, BODY, "IC_kwDOAAAAAc4AAAAG"))
    host = GitHubHost(paged={f"{BASE}/issues/7/comments": listing}, page_size=2)

    assert forge(host).comment_exists(REPO, 7, MARKER, BODY) == "IC_kwDOAAAAAc4AAAAG"
    assert len(host.calls("GET", f"{BASE}/issues/7/comments")) == 3


@pytest.mark.parametrize(
    "listing",
    [
        pytest.param([], id="no-comments"),
        pytest.param(
            [issue_comment(101, BODY.replace("a1b2c3d4e", "ffffffff0"), "IC_x")],
            id="same-marker-other-body",
        ),
        pytest.param(
            [issue_comment(101, BODY.removesuffix(MARKER), "IC_x")],
            id="same-text-without-the-marker",
        ),
        pytest.param([issue_comment(101, f"{BODY}\nand more", "IC_x")], id="body-only-contains"),
    ],
)
def test_no_matching_comment_is_none(listing: list[dict[str, Any]]) -> None:
    host = GitHubHost(paged={f"{BASE}/issues/7/comments": listing})

    assert forge(host).comment_exists(REPO, 7, MARKER, BODY) is None


def test_a_reply_is_found_under_its_parent() -> None:
    listing = [
        review_comment(11, "The schema does not match.", "PRRC_kwDOAAAAAc4AAAAL"),
        review_comment(12, BODY, "PRRC_kwDOAAAAAc4AAAAM", reply_to=11),
        review_comment(13, BODY, "PRRC_kwDOAAAAAc4AAAAN", reply_to=14),
    ]
    host = GitHubHost(paged={f"{BASE}/pulls/7/comments": listing})

    found = forge(host).comment_exists(REPO, 7, MARKER, BODY, reply_to="11")

    assert found == "PRRC_kwDOAAAAAc4AAAAM"


def test_the_same_body_under_another_parent_is_not_that_parents_reply() -> None:
    listing = [
        review_comment(11, "The schema does not match.", "PRRC_a"),
        review_comment(13, BODY, "PRRC_b", reply_to=14),
        review_comment(15, BODY, "PRRC_c"),
    ]
    host = GitHubHost(paged={f"{BASE}/pulls/7/comments": listing})

    assert forge(host).comment_exists(REPO, 7, MARKER, BODY, reply_to="11") is None


def test_the_id_found_is_the_one_a_post_reports_for_recording() -> None:
    """Own-post recording matches on what `post_comment` returned."""
    stored = issue_comment(102, BODY, "IC_kwDOAAAAAc4AAAAC")
    host = GitHubHost(
        routes={("POST", f"{BASE}/issues/7/comments"): answer(stored, 201)},
        paged={f"{BASE}/issues/7/comments": [stored]},
    )
    f = forge(host)

    [posted] = f.post_comment(REPO, 7, body=BODY)

    assert f.comment_exists(REPO, 7, MARKER, BODY) == posted


def test_a_listing_that_cannot_be_read_raises_rather_than_reading_as_none() -> None:
    host = GitHubHost(routes={("GET", f"{BASE}/issues/7/comments"): refusal(403, "Forbidden")})

    with pytest.raises(TransportError):
        forge(host).comment_exists(REPO, 7, MARKER, BODY)


# --- stack_of answers membership ----------------------------------------------------

STACKS = f"{BASE}/stacks"


def member(number: int, ref: str) -> dict[str, Any]:
    return {
        "number": number,
        "state": "open",
        "draft": False,
        "merged_at": None,
        "head": {"ref": ref, "sha": f"{number:040x}"},
    }


def stack_doc(number: int, *pulls: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": 4200 + number,
        "number": number,
        "node_id": f"PRS_kwDOAAAAAc4AAB{number:03d}",
        "url": f"{API}{STACKS}/{number}",
        "base": {"ref": "main"},
        "open": True,
        "created_at": "2026-09-28T14:02:11Z",
        "pull_requests": list(pulls),
    }


def test_a_pull_request_is_a_member_of_the_stack_that_holds_it() -> None:
    mine = stack_doc(3, member(11, "spec/feature/1"), member(12, "spec/feature/2"))
    host = GitHubHost(routes={("GET", STACKS): answer([mine])})

    assert forge(host).stack_of(REPO, 12) == Stack(number=3, open=True, pulls=(11, 12))


def test_a_pull_request_is_not_a_member_of_a_stack_that_does_not_hold_it() -> None:
    other = stack_doc(5, member(21, "spec/other/1"), member(22, "spec/other/2"))
    host = GitHubHost(routes={("GET", STACKS): answer([other])})

    assert forge(host).stack_of(REPO, 12) is None
