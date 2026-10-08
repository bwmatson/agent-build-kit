"""The reads that make an Azure DevOps create safe to repeat, and the follow-ups
to a create that must not fail the unit once the pull request exists.

The host is the REST stand-in; thread listings carry what the service sends.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import BaseMissing, RepoId
from agent_build_kit.forges.transport import TransportError
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, refusal

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
HEAD = "spec/add-marker/1"
MARKER = "<!-- spec-driven:reply -->"
BODY = f"Fixed in a1b2c3d4e.\n\n<sub>spec-driven rework, in a1b2c3d4e</sub>\n{MARKER}"


def forge(host: RestHost) -> AzureDevOpsForge:
    return AzureDevOpsForge(http=host)


# --- find_pr: none, or could not tell ----------------------------------------------


def test_an_empty_listing_is_no_pull_request() -> None:
    assert forge(RestHost(azure_answers.OPEN)).find_pr(REPO, head="spec/none/1") is None


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_a_lookup_that_could_not_tell_raises(status: int) -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("GET", "pullrequests")] = refusal(status, "unavailable")

    with pytest.raises(TransportError):
        forge(host).find_pr(REPO, head=HEAD)


# --- a create refused as a duplicate -----------------------------------------------


def test_a_create_refused_as_a_duplicate_returns_the_existing_pull_request() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "pullrequests")] = refusal(
        409,
        "TF401179: An active pull request for the source and target branch already exists.",
        type_key="GitPullRequestExistsException",
    )

    number = forge(host).create_pr(REPO, head=HEAD, base="main", title="t", body="b")

    assert number == 162
    assert host.calls("GET", "pullrequests")


def test_a_missing_base_is_still_base_missing() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "pullrequests")] = refusal(
        400, "TF401028: The reference 'refs/heads/spec/x/0' does not exist. Check the name."
    )

    with pytest.raises(BaseMissing):
        forge(host).create_pr(REPO, head=HEAD, base="spec/x/0", title="t", body="b")


def test_a_refusal_that_is_neither_a_duplicate_nor_a_missing_base_is_a_plain_failure() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "pullrequests")] = refusal(
        403, "TF401027: You need the GenericContribute permission.", type_key="AccessDenied"
    )

    with pytest.raises(TransportError) as caught:
        forge(host).create_pr(REPO, head=HEAD, base="main", title="TF401179", body="exists")

    assert not isinstance(caught.value, BaseMissing)
    assert "TF401027" in str(caught.value)


# --- comment_exists over recorded listings -----------------------------------------


def top_level(thread: int, content: str, comment: int = 1) -> dict[str, Any]:
    """A thread the pipeline opened with no file behind it, as the service lists it."""
    return azure_answers.thread(
        id=thread,
        status="active",
        threadContext=None,
        comments=[
            {
                "id": comment,
                "parentCommentId": 0,
                "commentType": "text",
                "content": content,
                "author": {"displayName": "A Bot", "uniqueName": "bot@example.com"},
                "publishedDate": "2026-09-28T09:21:00.000Z",
                "usersLiked": [],
            }
        ],
    )


def with_reply(thread: dict[str, Any], content: str, *, parent: int, comment: int) -> dict:
    reply = {
        "id": comment,
        "parentCommentId": parent,
        "commentType": "text",
        "content": content,
        "author": {"displayName": "A Bot", "uniqueName": "bot@example.com"},
        "publishedDate": "2026-09-28T09:22:00.000Z",
        "usersLiked": [],
    }
    return {**thread, "comments": [*thread["comments"], reply]}


def test_a_comment_is_found_by_its_marker_and_exact_body() -> None:
    host = RestHost(
        azure_answers.OPEN,
        threads={
            162: [
                azure_answers.SYSTEM_PUSH,
                top_level(900, "Looks fine to me."),
                top_level(901, BODY),
            ]
        },
    )

    assert forge(host).comment_exists(REPO, 162, MARKER, BODY) == "901.1"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(BODY.replace("a1b2c3d4e", "ffffffff0"), id="same-marker-other-body"),
        pytest.param(BODY.removesuffix(MARKER), id="same-text-without-the-marker"),
        pytest.param(f"{BODY}\nand more", id="body-only-contains"),
    ],
)
def test_no_matching_comment_is_none(content: str) -> None:
    host = RestHost(azure_answers.OPEN, threads={162: [top_level(900, content)]})

    assert forge(host).comment_exists(REPO, 162, MARKER, BODY) is None


def test_no_threads_is_none() -> None:
    assert forge(RestHost(azure_answers.OPEN)).comment_exists(REPO, 162, MARKER, BODY) is None


def test_a_reply_is_found_under_its_parent_in_the_thread_it_was_written_in() -> None:
    thread = with_reply(azure_answers.thread(), BODY, parent=1, comment=4)
    host = RestHost(azure_answers.OPEN, threads={162: [thread]})

    assert forge(host).comment_exists(REPO, 162, MARKER, BODY, reply_to="478.1") == "478.4"


def test_the_same_body_under_another_parent_is_not_that_parents_reply() -> None:
    thread = with_reply(azure_answers.thread(), BODY, parent=3, comment=4)
    host = RestHost(azure_answers.OPEN, threads={162: [thread]})

    assert forge(host).comment_exists(REPO, 162, MARKER, BODY, reply_to="478.1") is None


def test_the_same_body_in_another_thread_is_not_that_threads_reply() -> None:
    other = with_reply(azure_answers.thread(id=479), BODY, parent=1, comment=4)
    host = RestHost(azure_answers.OPEN, threads={162: [azure_answers.thread(), other]})

    assert forge(host).comment_exists(REPO, 162, MARKER, BODY, reply_to="478.1") is None


def test_the_id_found_is_the_one_a_post_reports_for_recording() -> None:
    """Own-post recording matches on what `post_comment` returned."""
    host = RestHost(azure_answers.OPEN, threads={162: [top_level(900, BODY)]})
    f = forge(host)

    [posted] = f.post_comment(REPO, 162, body=BODY)

    assert f.comment_exists(REPO, 162, MARKER, BODY) == posted


def test_a_listing_that_cannot_be_read_raises_rather_than_reading_as_none() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("GET", "pullrequests/162/threads")] = refusal(403, "forbidden")

    with pytest.raises(TransportError):
        forge(host).comment_exists(REPO, 162, MARKER, BODY)


# --- stacks -------------------------------------------------------------------------


def test_a_pull_request_is_a_member_of_no_stack() -> None:
    assert forge(RestHost(azure_answers.OPEN)).stack_of(REPO, 162) is None


# --- follow-ups to a create are advisory --------------------------------------------


def test_a_body_update_the_host_refuses_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("PATCH", "pullrequests/162")] = refusal(400, "TF401180: not a valid description")

    with caplog.at_level(logging.WARNING):
        forge(host).update_pr(REPO, 162, body="stacked body")

    assert host.calls("PATCH", "pullrequests/162")
    assert "TF401180" in caplog.text


def test_a_status_the_host_refuses_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "commits/abc123/statuses")] = refusal(
        403, "TF401027: You need the PullRequestContribute permission.", type_key="AccessDenied"
    )

    with caplog.at_level(logging.WARNING):
        forge(host).post_status(
            REPO, sha="abc123", ok=True, context="local/tier2", description="d", head=HEAD
        )

    assert host.calls("POST", "commits/abc123/statuses")
    assert "TF401027" in caplog.text
