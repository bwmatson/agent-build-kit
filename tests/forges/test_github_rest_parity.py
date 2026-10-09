"""Over the typed client the forge lists what it listed over the CLI.

Each case is a trap the CLI-era forge closed and its tests pinned, put again to
the GraphQL answers GitHub sends. Moving the wire must not move a field of
`PullRequest`, and listing is one query per page.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import (
    Check,
    CheckStatus,
    PullRequest,
    RepoId,
    cancelled_names,
    failing_names,
)
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.units import CLOSED, MERGED
from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost, listing_of

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")

RUN_LINK = f"{gh.WEB}/actions/runs/1/job/2"


def listing(host: GitHubHost, **kwargs) -> list[PullRequest]:
    return GitHubForge(http=host).list_prs(REPO, **kwargs)


def one(**overrides) -> PullRequest:
    [found] = listing(GitHubHost(gh.pull(16, **overrides)))
    return found


# --- the whole record -------------------------------------------------------------


def test_a_repository_s_listing_is_the_same_records_as_before() -> None:
    host = GitHubHost(
        gh.pull(
            162,
            comments=(("IC_1", "looks close"), ("IC_2", "one more thing")),
            reviews=(
                ("PRR_1", "CHANGES_REQUESTED", "needs work"),
                ("PRR_2", "PENDING", ""),
                ("PRR_3", "COMMENTED", ""),
            ),
            review_decision="CHANGES_REQUESTED",
            labels=("in-review", "abk"),
            mergeable="CONFLICTING",
            draft=True,
            checks=[
                gh.check_run("lint", "SUCCESS"),
                gh.check_run("CI", "FAILURE"),
                gh.check_run("slow", "TIMED_OUT"),
                gh.check_run("flaky", "CANCELLED"),
                gh.check_run("later", None, status="IN_PROGRESS"),
                gh.STATUS_CONTEXT,
            ],
        ),
        gh.pull(
            157,
            head="spec/other/1",
            base="spec/other/0",
            state="MERGED",
            merged_at="2026-09-23T12:00:00Z",
        ),
        gh.pull(158, state="CLOSED"),
        gh.pull(159),
    )

    found = listing(host)

    assert found == [
        PullRequest(
            number=162,
            head="spec/add-marker/162",
            base="main",
            state="open",
            draft=True,
            labels=("abk", "in-review"),
            conversation=("IC_1", "IC_2", "PRR_1", "PRR_3"),
            comment_bodies=("looks close", "one more thing"),
            review_decision="changes_requested",
            checks=(
                Check(name="lint", status=CheckStatus.PASSED, url=RUN_LINK),
                Check(name="CI", status=CheckStatus.FAILED, url=RUN_LINK),
                Check(name="slow", status=CheckStatus.FAILED, url=RUN_LINK),
                Check(name="flaky", status=CheckStatus.CANCELLED, url=RUN_LINK),
                Check(name="later", status=CheckStatus.PENDING, url=RUN_LINK),
            ),
            mergeable=False,
        ),
        PullRequest(
            number=157,
            head="spec/other/1",
            base="spec/other/0",
            state=MERGED,
            mergeable=True,
        ),
        PullRequest(
            number=158, head="spec/add-marker/158", base="main", state=CLOSED, mergeable=True
        ),
        PullRequest(
            number=159, head="spec/add-marker/159", base="main", state="open", mergeable=True
        ),
    ]


# --- one query per page -----------------------------------------------------------


def test_listing_is_one_graphql_query_and_no_rest_call() -> None:
    host = GitHubHost(*listing_of(3))

    listing(host)

    assert [(s.method, s.path) for s in host.seen] == [("POST", "/graphql")]


def test_the_query_asks_for_everything_a_record_is_made_of() -> None:
    host = GitHubHost(gh.pull(16))

    listing(host)

    [query] = [s.query for s in host.graphql()]
    for field in (
        "headRefName",
        "baseRefName",
        "state",
        "isDraft",
        "mergedAt",
        "labels",
        "comments",
        "reviews",
        "statusCheckRollup",
        "conclusion",
        "reviewDecision",
        "mergeable",
    ):
        assert field in query, f"the listing does not ask for {field}"


def test_the_listing_names_its_repository() -> None:
    host = GitHubHost(gh.pull(16))

    listing(host)

    [call] = host.graphql()
    sent = f"{call.query} {call.body.get('variables')}"
    assert "example" in sent and "app" in sent


def test_a_repository_with_more_than_a_page_is_read_by_the_cursor() -> None:
    host = GitHubHost(*listing_of(5), page_size=2)

    found = listing(host)

    assert [p.number for p in found] == [1, 2, 3, 4, 5]
    assert len(host.graphql()) == 3, "a query a page, no more"


def test_a_repository_with_no_pull_requests_lists_none() -> None:
    assert listing(GitHubHost()) == []


def test_only_the_branches_with_the_prefix_are_kept() -> None:
    host = GitHubHost(
        gh.pull(1, head="spec/add-marker/1"),
        gh.pull(2, head="feature/other"),
        gh.pull(3, head="spec/add-marker/2"),
    )

    found = listing(host, head_prefix="spec/")

    assert [p.number for p in found] == [1, 3]


# --- the traps --------------------------------------------------------------------


def test_an_inline_review_counts_as_a_comment() -> None:
    """A reviewer commenting on a line is reviewing; reading only issue-level
    comments meant an entire diff review registered as silence."""
    assert one(reviews=(("PRR_r1", "COMMENTED", "this needs a look"),)).conversation == ("PRR_r1",)


def test_a_review_still_being_written_is_not_a_comment() -> None:
    """A PENDING review is the reviewer's unsubmitted draft; counting it would
    send the unit back for rework mid-review, with nothing to act on."""
    assert one(reviews=(("PRR_r1", "PENDING", ""),)).conversation == ()


def test_only_a_merged_at_means_merged() -> None:
    """Reading an open pull request as merged restacks its children and
    deletes their branches."""
    assert one(merged_at="2026-09-23T12:00:00Z", state="MERGED").state == MERGED
    assert one(state="CLOSED").state == CLOSED
    assert one().state == "open"


def test_only_a_failing_conclusion_is_a_failing_check() -> None:
    pull = one(
        checks=[
            gh.check_run("CI", "FAILURE"),
            gh.check_run("lint", "SUCCESS"),
            gh.check_run("slow", "TIMED_OUT"),
            gh.STATUS_CONTEXT,
        ]
    )

    assert failing_names(pull.checks) == ("CI", "slow")


def test_changes_requested_is_the_only_decision_that_reworks() -> None:
    assert one(review_decision="CHANGES_REQUESTED").review_decision == "changes_requested"
    assert one(review_decision="APPROVED").review_decision == ""
    assert one(review_decision="REVIEW_REQUIRED").review_decision == ""
    assert one(review_decision=None).review_decision == ""


@pytest.mark.parametrize(
    ("said", "means"),
    [("MERGEABLE", True), ("CONFLICTING", False), ("UNKNOWN", None)],
)
def test_the_hosts_three_words_for_mergeability(said: str, means: bool | None) -> None:
    """UNKNOWN is what the host says for a while after every push; it is not a
    conflict."""
    assert one(mergeable=said).mergeable is means


# --- a cancelled check ------------------------------------------------------------


def test_a_cancelled_check_is_cancelled_and_not_failing() -> None:
    pull = one(checks=[gh.check_run("CI", "CANCELLED"), gh.check_run("lint", "SUCCESS")])

    assert cancelled_names(pull.checks) == ("CI",)
    assert failing_names(pull.checks) == ()


def test_a_failed_and_a_cancelled_check_are_told_apart() -> None:
    pull = one(
        checks=[
            gh.check_run("CI", "FAILURE"),
            gh.check_run("slow", "TIMED_OUT"),
            gh.check_run("lint", "CANCELLED"),
        ]
    )

    assert failing_names(pull.checks) == ("CI", "slow")
    assert cancelled_names(pull.checks) == ("lint",)


def test_a_check_with_no_conclusion_is_neither() -> None:
    pull = one(checks=[gh.check_run("CI", None, status="IN_PROGRESS")])

    assert failing_names(pull.checks) == ()
    assert cancelled_names(pull.checks) == ()


def test_a_commit_with_no_checks_has_none() -> None:
    pull = one(checks=None)

    assert failing_names(pull.checks) == ()
    assert cancelled_names(pull.checks) == ()
