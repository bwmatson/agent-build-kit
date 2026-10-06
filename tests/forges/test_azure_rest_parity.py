"""Over REST the forge returns what it returned over the CLI.

Each case here is a trap the CLI-era forge closed and its tests pinned, put
again to the same recorded documents arriving as HTTP bodies. Moving the wire
must not move a field of `PullRequest`.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.units import MERGED
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def listing(host: RestHost, **kwargs) -> list[PullRequest]:
    return AzureDevOpsForge(http=host).list_prs(REPO, **kwargs)


def one(*pulls: dict, **host: object) -> PullRequest:
    [found] = listing(RestHost(*pulls, **host))  # type: ignore[arg-type]
    return found


def evaluated(status: str, name: str, build: int | None) -> dict:
    document = azure_answers.evaluation(status, name)
    document["context"] = {"buildId": build, "isExpired": False} if build else None
    return document


# --- the whole record -------------------------------------------------------------


def test_a_project_s_listing_is_the_same_records_as_before() -> None:
    reviewed = azure_answers.pull(
        pullRequestId=170,
        sourceRefName="refs/heads/spec/other/1",
        targetRefName="refs/heads/spec/other/0",
        isDraft=True,
        mergeStatus="conflicts",
        labels=[{"id": "x", "name": "in-review"}, {"id": "y", "name": "abk"}],
        reviewers=[azure_answers.reviewer(-10)],
    )
    host = RestHost(
        azure_answers.OPEN,
        reviewed,
        azure_answers.COMPLETED,
        azure_answers.ABANDONED,
        threads={162: [azure_answers.REVIEW_THREAD, azure_answers.SYSTEM_PUSH]},
        policies={
            162: [
                azure_answers.evaluation("approved", "lint"),
                evaluated("rejected", "CI build", 41),
                evaluated("rejected", "slow build", 42),
            ]
        },
        builds={41: "failed", 42: "canceled"},
        statuses={162: [azure_answers.FAILED_STATUS, azure_answers.PASSED_STATUS]},
    )

    found = listing(host)

    assert found == [
        PullRequest(
            number=162,
            head="spec/add-marker/1",
            base="main",
            state="open",
            mergeable=True,
            conversation=("478.1", "478.2", "478.3"),
            comment_bodies=(
                "The declared schema does not match what extraction stores.",
                "Addressed in a1b2c3d.",
                "Confirmed against real data, thanks.",
            ),
            failing_checks=("CI build", "continuous-integration/build"),
            cancelled_checks=("slow build",),
        ),
        PullRequest(
            number=170,
            head="spec/other/1",
            base="spec/other/0",
            state="open",
            draft=True,
            mergeable=False,
            labels=("abk", "in-review"),
            review_decision="changes_requested",
        ),
        PullRequest(
            number=157, head="spec/add-marker/1", base="main", state=MERGED, mergeable=True
        ),
        PullRequest(
            number=158, head="spec/add-marker/1", base="main", state="closed", mergeable=True
        ),
    ]


# --- state ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "state"), [("active", "open"), ("completed", MERGED), ("abandoned", "closed")]
)
def test_only_a_completed_status_means_merged(status: str, state: str) -> None:
    """`succeeded` and a populated `lastMergeCommit` are on an open pull request
    exactly as on a completed one."""
    document = azure_answers.pull(status=status, mergeStatus="succeeded")
    assert document["lastMergeCommit"]["commitId"]

    assert one(document).state == state


@pytest.mark.parametrize(
    ("merge_status", "expected"),
    [
        ("succeeded", True),
        ("conflicts", False),
        ("queued", None),
        ("notSet", None),
        ("rejectedByPolicy", None),
        ("failure", None),
    ],
)
def test_mergeability_is_definite_or_unknown(merge_status: str, expected: bool | None) -> None:
    assert one(azure_answers.pull(mergeStatus=merge_status)).mergeable is expected


def test_a_pull_request_with_no_merge_status_is_undetermined() -> None:
    document = azure_answers.pull()
    del document["mergeStatus"]

    assert one(document).mergeable is None


def test_branch_names_lose_their_ref_prefix_and_labels_may_be_null() -> None:
    pull = one(azure_answers.OPEN)

    assert (pull.head, pull.base) == ("spec/add-marker/1", "main")
    assert pull.labels == ()


def test_listing_can_be_narrowed_to_the_pipeline_s_own_branches() -> None:
    other = azure_answers.pull(pullRequestId=170, sourceRefName="refs/heads/feature/x")
    host = RestHost(azure_answers.OPEN, other)

    found = listing(host, head_prefix="spec/")

    assert [p.number for p in found] == [162]


def test_merged_and_abandoned_pull_requests_are_listed_too() -> None:
    """A merge is precisely what the poller waits for."""
    host = RestHost(azure_answers.COMPLETED, azure_answers.ABANDONED)

    assert [p.state for p in listing(host)] == [MERGED, "closed"]
    [call] = host.calls("GET", "pullrequests")
    assert call.params["searchCriteria.status"] == "all"


# --- changes requested ------------------------------------------------------------


@pytest.mark.parametrize(
    ("vote", "container", "decision"),
    [
        (-10, False, "changes_requested"),
        (-5, False, "changes_requested"),
        (0, False, ""),
        (5, False, ""),
        (10, False, ""),
        (-5, True, ""),
    ],
)
def test_changes_requested_comes_from_the_votes(vote: int, container: bool, decision: str) -> None:
    reviewers = [azure_answers.reviewer(vote, container=container)]

    assert one(azure_answers.pull(reviewers=reviewers)).review_decision == decision


# --- checks -----------------------------------------------------------------------


@pytest.mark.parametrize("status", ["rejected", "broken"])
def test_a_failed_build_policy_is_a_failing_check(status: str) -> None:
    pull = one(
        azure_answers.OPEN,
        policies={162: [evaluated(status, "CI build", 41)]},
        builds={41: "failed"},
    )

    assert pull.failing_checks == ("CI build",)
    assert pull.cancelled_checks == ()


@pytest.mark.parametrize("status", ["running", "queued", "approved", "notApplicable"])
def test_a_build_policy_that_is_not_finished_badly_is_not_reported(status: str) -> None:
    pull = one(azure_answers.OPEN, policies={162: [azure_answers.evaluation(status)]})

    assert pull.failing_checks == pull.cancelled_checks == ()


def test_a_rejected_policy_that_is_not_a_build_is_not_a_failing_check() -> None:
    reviewers = {"id": "fa4e907d-c16b-4a4c-9dfa-4906e5d171dd", "displayName": "Reviewers"}
    evaluation = azure_answers.evaluation("rejected", "Reviewers", reviewers)

    assert one(azure_answers.OPEN, policies={162: [evaluation]}).failing_checks == ()


def test_a_cancelled_build_is_cancelled_and_not_failing() -> None:
    pull = one(
        azure_answers.OPEN,
        policies={162: [evaluated("rejected", "CI build", 41)]},
        builds={41: "canceled"},
    )

    assert pull.cancelled_checks == ("CI build",)
    assert pull.failing_checks == ()


def test_a_mixed_outcome_is_reported_in_both_lists() -> None:
    pull = one(
        azure_answers.OPEN,
        policies={
            162: [evaluated("rejected", "CI build", 41), evaluated("rejected", "lint build", 42)]
        },
        builds={41: "canceled", 42: "failed"},
    )

    assert pull.cancelled_checks == ("CI build",)
    assert pull.failing_checks == ("lint build",)


def test_an_evaluation_with_no_build_to_ask_about_is_a_failure() -> None:
    pull = one(azure_answers.OPEN, policies={162: [evaluated("broken", "CI build", None)]})

    assert pull.failing_checks == ("CI build",)


def test_the_newest_status_of_each_genre_and_name_is_the_one_in_force() -> None:
    older = {"id": 1, "state": "failed", "context": {"genre": "local", "name": "tier2"}}
    newer = {"id": 2, "state": "succeeded", "context": {"genre": "local", "name": "tier2"}}
    still = {"id": 3, "state": "error", "context": {"genre": "ci", "name": "lint"}}
    pending = {"id": 4, "state": "pending", "context": {"genre": "ci", "name": "deploy"}}

    pull = one(azure_answers.OPEN, statuses={162: [newer, still, pending, older]})

    assert pull.failing_checks == ("ci/lint",)


def test_a_status_with_no_genre_is_named_by_its_name() -> None:
    status = {"id": 1, "state": "failed", "context": {"genre": None, "name": "smoke"}}

    assert one(azure_answers.OPEN, statuses={162: [status]}).failing_checks == ("smoke",)


# --- conversation -----------------------------------------------------------------


def test_the_servers_own_comments_are_not_conversation() -> None:
    pull = one(
        azure_answers.OPEN,
        threads={162: [azure_answers.SYSTEM_PUSH, azure_answers.SYSTEM_REVIEWER_ADDED]},
    )

    assert pull.conversation == pull.comment_bodies == ()


def test_a_comment_with_no_type_is_still_a_comment_and_ids_carry_the_thread() -> None:
    pull = one(azure_answers.OPEN, threads={162: [azure_answers.REVIEW_THREAD]})

    assert pull.conversation == ("478.1", "478.2", "478.3")
    assert "Addressed in a1b2c3d." in pull.comment_bodies


def test_a_deleted_comment_is_not_conversation() -> None:
    gone = {**azure_answers.REVIEW_THREAD["comments"][0], "isDeleted": True}
    thread = azure_answers.thread(comments=[gone, azure_answers.REVIEW_THREAD["comments"][2]])

    pull = one(azure_answers.OPEN, threads={162: [thread]})

    assert pull.conversation == ("478.3",)


def test_review_notes_carry_thread_file_line_and_whether_they_are_live() -> None:
    host = RestHost(azure_answers.OPEN, threads={162: [azure_answers.REVIEW_THREAD]})
    forge = AzureDevOpsForge(http=host)

    [first, *_] = forge.review_notes(REPO, 162)

    assert (first.id, first.path, first.line) == ("478.1", "poc/validate/effective_schema.py", 14)
    assert not first.live, "the reviewer resolved the thread"


def test_an_active_thread_is_live() -> None:
    host = RestHost(azure_answers.OPEN, threads={162: [azure_answers.thread(status="active")]})

    notes = AzureDevOpsForge(http=host).review_notes(REPO, 162)

    assert notes and all(n.live for n in notes)


def test_the_logs_of_a_failed_check_name_it_and_link_the_build() -> None:
    host = RestHost(
        azure_answers.OPEN,
        policies={162: [evaluated("rejected", "CI build", 41)]},
        builds={41: "failed"},
    )
    forge = AzureDevOpsForge(http=host)
    [pull] = forge.list_prs(REPO)

    logs = forge.failed_check_logs(REPO, pull)

    assert "CI build" in logs
    assert "https://dev.azure.com/acme/Some%20Project/_build/results?buildId=41" in logs


def test_the_logs_name_only_the_failed_build_of_a_mixed_outcome() -> None:
    host = RestHost(
        azure_answers.OPEN,
        policies={
            162: [evaluated("rejected", "CI build", 41), evaluated("rejected", "lint build", 42)]
        },
        builds={41: "canceled", 42: "failed"},
    )
    forge = AzureDevOpsForge(http=host)
    [pull] = forge.list_prs(REPO)

    logs = forge.failed_check_logs(REPO, pull)

    assert "lint build" in logs and "buildId=42" in logs
    assert "CI build" not in logs and "buildId=41" not in logs


def test_a_pull_request_with_nothing_failing_has_no_logs() -> None:
    forge = AzureDevOpsForge(http=RestHost(azure_answers.OPEN))
    [pull] = forge.list_prs(REPO)

    assert forge.failed_check_logs(REPO, pull) == ""
