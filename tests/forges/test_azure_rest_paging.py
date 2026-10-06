"""Listing reads every page, in one process, within a bound, and no more than it
needs for a pull request that is finished."""

from __future__ import annotations

from copy import deepcopy

import pytest

from agent_build_kit.forges.azure_devops import READ_POOL, AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.transport import TransportError
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, refusal

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def pulls(count: int, *, status: str = "active", first: int = 100) -> list[dict]:
    return [
        {
            **deepcopy(azure_answers.OPEN),
            "status": status,
            "pullRequestId": first + n,
            "sourceRefName": f"refs/heads/spec/add-marker/{n}",
        }
        for n in range(count)
    ]


def thread_of(pr: int) -> dict:
    note = {**azure_answers.REVIEW_THREAD["comments"][0], "content": f"note on {pr}"}
    return azure_answers.thread(id=pr, comments=[note])


# --- paging -----------------------------------------------------------------------


def test_a_listing_longer_than_a_page_is_read_to_the_end() -> None:
    host = RestHost(*pulls(230, status="completed"))

    found = AzureDevOpsForge(http=host).list_prs(REPO)

    assert [p.number for p in found] == list(range(100, 330))
    assert len(host.calls("GET", "pullrequests")) >= 3


def test_each_page_asks_for_the_next_one_by_skipping_what_it_has() -> None:
    host = RestHost(*pulls(230, status="completed"))

    AzureDevOpsForge(http=host).list_prs(REPO)

    skips = [int(c.params.get("$skip", 0)) for c in host.calls("GET", "pullrequests")]
    assert skips[:3] == [0, 100, 200]


def test_a_listing_of_exactly_a_page_is_read_to_the_end() -> None:
    host = RestHost(*pulls(100, status="abandoned"))

    assert len(AzureDevOpsForge(http=host).list_prs(REPO)) == 100


def test_evaluations_paged_by_top_and_skip_are_all_read() -> None:
    """The failing ones are on the last pages: a reader that stops at the first
    page reports a green pull request."""
    evaluations = [azure_answers.evaluation("approved", f"check {n}") for n in range(25)]
    for n in (22, 24):
        evaluations[n] = azure_answers.evaluation("broken", f"check {n}")
        evaluations[n]["context"] = None
    host = RestHost(azure_answers.OPEN, policies={162: evaluations}, policy_page=10)

    [pull] = AzureDevOpsForge(http=host).list_prs(REPO)

    assert pull.failing_checks == ("check 22", "check 24")
    skips = [int(c.params["$skip"]) for c in host.calls("GET", "policy/evaluations")]
    assert skips == [0, 10, 20, 25], "the skip is what has been read so far"


def test_changes_paged_by_skip_are_all_read() -> None:
    entries = [
        {"changeType": "add", "item": {"path": f"/src/file{n}.py", "isFolder": False}}
        for n in range(5)
    ]
    host = RestHost(azure_answers.OPEN, changes=entries, change_page=2)

    files = AzureDevOpsForge(http=host).pr_files(REPO, 162)

    assert files == [f"src/file{n}.py" for n in range(5)]


# --- one process, a bound ---------------------------------------------------------


def test_the_reads_for_open_pull_requests_overlap() -> None:
    host = RestHost(*pulls(5), delay=0.05)

    AzureDevOpsForge(http=host).list_prs(REPO)

    assert host.peak > 1, "the reads ran one after another"


def test_twenty_open_pull_requests_never_exceed_the_bound() -> None:
    listing = pulls(20)
    host = RestHost(
        *listing,
        threads={p["pullRequestId"]: [thread_of(p["pullRequestId"])] for p in listing},
        delay=0.02,
    )

    found = AzureDevOpsForge(http=host).list_prs(REPO)

    assert len(found) == 20
    assert 1 < host.peak <= READ_POOL


def test_each_pull_request_keeps_its_own_conversation_in_listing_order() -> None:
    listing = pulls(8)
    host = RestHost(
        *listing,
        threads={p["pullRequestId"]: [thread_of(p["pullRequestId"])] for p in listing},
        delay=0.01,
    )

    found = AzureDevOpsForge(http=host).list_prs(REPO)

    assert [p.number for p in found] == [p["pullRequestId"] for p in listing]
    for pull in found:
        assert pull.comment_bodies == (f"note on {pull.number}",)
        assert pull.conversation == (f"{pull.number}.1",)


def test_one_failed_read_fails_the_poll_with_no_partial_list() -> None:
    listing = pulls(6)
    host = RestHost(*listing, delay=0.01)
    host.refuse[("GET", "pullrequests/103/threads")] = refusal(400, "TF400898: boom")

    with pytest.raises(TransportError):
        AzureDevOpsForge(http=host).list_prs(REPO)


# --- what a finished pull request costs -------------------------------------------


def test_a_completed_or_abandoned_pull_request_costs_only_the_list_call() -> None:
    host = RestHost(azure_answers.COMPLETED, azure_answers.ABANDONED)

    AzureDevOpsForge(http=host).list_prs(REPO)

    assert {c.route for c in host.seen} == {"pullrequests"}


def test_a_finished_pull_request_beside_an_open_one_is_not_read() -> None:
    host = RestHost(azure_answers.OPEN, azure_answers.COMPLETED, azure_answers.ABANDONED)

    AzureDevOpsForge(http=host).list_prs(REPO)

    assert {c.route for c in host.seen} == {
        "pullrequests",
        "pullrequests/162/threads",
        "pullrequests/162/statuses",
        "policy/evaluations",
    }


def test_an_open_pull_request_reads_its_evaluations_once_by_artifact() -> None:
    host = RestHost(azure_answers.OPEN, azure_answers.COMPLETED)

    AzureDevOpsForge(http=host).list_prs(REPO)

    [call] = host.calls("GET", "policy/evaluations")
    assert call.params["artifactId"].endswith("/162")
    assert call.params["artifactId"].startswith("vstfs:///CodeReview/CodeReviewId/")


def test_a_build_is_read_only_behind_a_failing_evaluation() -> None:
    failing = azure_answers.evaluation("broken")
    host = RestHost(
        azure_answers.OPEN,
        policies={162: [azure_answers.evaluation("approved", "lint"), failing]},
        builds={41: "failed"},
    )

    AzureDevOpsForge(http=host).list_prs(REPO)

    assert [c.route for c in host.calls(route="build/builds/41")] == ["build/builds/41"]
    assert len(host.calls(route="build/builds/41")) == 1
