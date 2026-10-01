"""The Azure DevOps forge behaving as GitHub's does, where it used to be silent.

Four behaviours were carried over by name and did nothing: reporting a
conflict, reading a failing build, showing tier 2's result on the pull
request. Each test here is named for the trap it closes. They run against
`AzureHost`, which answers at the wire with documents recorded from real pull
requests, so what is exercised is the argv the forge builds and the JSON it
reads — not a wrapper's idea of them.
"""

from __future__ import annotations

import logging

import pytest

from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.units import MERGED
from tests.forges import azure_answers
from tests.forges.azure_host import AzureHost

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
HEAD = "spec/add-marker/1"


def listed(host: AzureHost) -> list[PullRequest]:
    return FORGE.list_prs(REPO, run=host)


# --- mergeability -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("merge_status", "expected"),
    [
        ("succeeded", True),
        ("conflicts", False),
        # Transient: the host works it out lazily, and the poller carries the
        # last definite answer across it.
        ("queued", None),
        ("notSet", None),
        # Neither says anything about conflicts. Read as `False`, a rework
        # would be sent for a reason a rework cannot fix.
        ("rejectedByPolicy", None),
        ("failure", None),
    ],
)
def test_mergeable_is_read_from_the_merge_status(merge_status: str, expected: bool | None) -> None:
    [pull] = listed(AzureHost(azure_answers.pull(mergeStatus=merge_status)))

    assert pull.mergeable is expected


def test_a_pull_request_with_no_merge_status_is_undetermined() -> None:
    document = azure_answers.pull()
    del document["mergeStatus"]

    [pull] = listed(AzureHost(document))

    assert pull.mergeable is None


def test_an_open_pull_request_that_can_merge_has_not_merged() -> None:
    """`succeeded` and a populated `lastMergeCommit` are on an open pull
    request exactly as on a completed one. Now that the first is read, only
    `status` may still say merged: anything else marks every open PR merged,
    which restacks its children and deletes their branches."""
    document = azure_answers.pull(mergeStatus="succeeded")
    assert document["lastMergeCommit"]["commitId"]

    [pull] = listed(AzureHost(document))

    assert pull.mergeable is True
    assert pull.state == "open"


def test_a_completed_pull_request_is_merged_whatever_its_merge_status() -> None:
    [pull] = listed(AzureHost(azure_answers.COMPLETED))

    assert pull.state == MERGED


# --- build policies ---------------------------------------------------------------


@pytest.mark.parametrize("status", ["rejected", "broken"])
def test_a_failed_build_policy_is_a_failing_check(status: str) -> None:
    host = AzureHost(azure_answers.OPEN, policies={162: [azure_answers.evaluation(status)]})

    [pull] = listed(host)

    [name] = pull.failing_checks
    assert "CI build" in name


@pytest.mark.parametrize("status", ["running", "queued", "approved", "notApplicable"])
def test_a_build_policy_that_is_not_failing_is_not_reported(status: str) -> None:
    """A build still running is waiting, not failing: read as a failure it
    would send the unit back for rework while its build was in progress."""
    host = AzureHost(azure_answers.OPEN, policies={162: [azure_answers.evaluation(status)]})

    [pull] = listed(host)

    assert pull.failing_checks == ()


@pytest.mark.parametrize(
    "policy_type",
    [
        {
            "id": "fa4e907d-c16b-4a4c-9dfa-4906e5d171dd",
            "displayName": "Minimum number of reviewers",
        },
        {"id": "40e92b44-2fe1-4dd6-b3d8-74a9c21d0c6e", "displayName": "Work item linking"},
        {"id": "c6a1889d-b943-4856-b76f-9e46bb6b0df2", "displayName": "Comment requirements"},
        {"id": "cbdc66da-9728-4af8-aada-9a5a32e4a226", "displayName": "Status"},
    ],
    ids=lambda t: t["displayName"],
)
def test_a_rejected_policy_that_is_not_a_build_is_not_a_failing_check(policy_type: dict) -> None:
    """A new pull request waiting for its approval is `rejected` on the
    reviewers policy: a rework cannot fix that."""
    evaluation = azure_answers.evaluation("rejected", policy_type["displayName"], policy_type)
    host = AzureHost(azure_answers.OPEN, policies={162: [evaluation]})

    [pull] = listed(host)

    assert pull.failing_checks == ()


def test_the_logs_of_a_failed_build_policy_name_it_and_link_the_build() -> None:
    host = AzureHost(azure_answers.OPEN, policies={162: [azure_answers.evaluation("rejected")]})
    [pull] = listed(host)

    logs = FORGE.failed_check_logs(REPO, pull, run=host)

    assert "CI build" in logs
    assert "https://dev.azure.com/acme/Some%20Project/_build/results?buildId=41" in logs


def test_the_only_failed_status_is_the_newest_of_its_context() -> None:
    """The listing holds every status posted; a failure a later success of the
    same context superseded is not a failing check."""
    host = AzureHost(azure_answers.OPEN)
    older = {"id": 1, "state": "failed", "context": {"genre": "local", "name": "tier2"}}
    newer = {"id": 2, "state": "succeeded", "context": {"genre": "local", "name": "tier2"}}
    host._pr_statuses[162] = [newer, older]  # noqa: SLF001 - recorded-shape listing

    [pull] = listed(host)

    assert pull.failing_checks == ()


def test_only_the_failing_evaluations_among_several_are_named() -> None:
    host = AzureHost(
        azure_answers.OPEN,
        policies={
            162: [
                azure_answers.evaluation("approved", "lint"),
                azure_answers.evaluation("rejected", "unit tests"),
                azure_answers.evaluation("running", "integration"),
                azure_answers.evaluation("broken", "packaging"),
            ]
        },
    )

    [pull] = listed(host)

    assert len(pull.failing_checks) == 2
    assert any("unit tests" in name for name in pull.failing_checks)
    assert any("packaging" in name for name in pull.failing_checks)


def test_a_repo_with_no_policies_reports_nothing_and_raises_nothing() -> None:
    host = AzureHost(azure_answers.OPEN)

    [pull] = listed(host)

    assert pull.failing_checks == ()


def test_a_failed_policy_and_a_failed_status_are_both_reported() -> None:
    """Statuses and policy evaluations are different resources; one source
    must not hide the other."""
    host = AzureHost(azure_answers.OPEN, policies={162: [azure_answers.evaluation("rejected")]})
    post(host, ok=False)

    [pull] = listed(host)
    assert len(pull.failing_checks) == 2
    assert "local/tier2" in pull.failing_checks


def test_a_completed_or_abandoned_pull_request_makes_no_policy_call() -> None:
    """Every `az` call costs seconds, and what is said on a finished pull
    request changes nothing the pipeline does."""
    host = AzureHost(azure_answers.COMPLETED, azure_answers.ABANDONED)

    pulls = listed(host)

    assert [p.state for p in pulls] == [MERGED, "closed"]
    assert host.asked("policy") == []


def test_an_open_pull_request_makes_exactly_one_policy_call() -> None:
    host = AzureHost(azure_answers.OPEN, azure_answers.COMPLETED)

    listed(host)

    assert len(host.asked("policy")) == 1


# --- tier 2's result on the pull request ------------------------------------------


def post(host: AzureHost, *, ok: bool = True, head: str = HEAD, sha: str = "abc123") -> None:
    FORGE.post_status(
        REPO,
        sha=sha,
        ok=ok,
        context="local/tier2",
        description="4 passed" if ok else "1 failed",
        head=head,
        run=host,
    )


def test_a_result_is_posted_on_the_open_pull_request_for_the_head() -> None:
    host = AzureHost(azure_answers.OPEN)

    post(host)

    [(number, posted)] = host.pr_status_posts
    assert number == 162
    assert posted["state"] == "succeeded"
    assert posted["context"] == {"genre": "local", "name": "tier2"}
    assert posted["description"] == "4 passed"


def test_the_commit_status_is_kept_beside_it() -> None:
    """The commit status is the truthful record of which commit was measured;
    a pull request status follows the branch and would claim a result for
    commits it never measured."""
    host = AzureHost(azure_answers.OPEN)

    post(host, sha="abc123")

    [commit] = host.commit_statuses
    assert commit["commit"] == "abc123"
    assert commit["state"] == "succeeded"
    assert len(host.pr_status_posts) == 1


def test_a_failed_result_is_posted_as_failed_on_the_pull_request() -> None:
    host = AzureHost(azure_answers.OPEN)

    post(host, ok=False)

    assert host.pr_status_posts[0][1]["state"] == "failed"


def test_the_pull_request_is_the_one_for_the_head_not_another_open_one() -> None:
    other = azure_answers.pull(pullRequestId=170, sourceRefName="refs/heads/spec/other/1")
    host = AzureHost(other, azure_answers.OPEN)

    post(host)

    assert [number for number, _ in host.pr_status_posts] == [162]


def test_a_head_with_no_pull_request_posts_only_the_commit_status() -> None:
    host = AzureHost(azure_answers.OPEN)

    post(host, head="spec/nothing-here/1")

    assert host.pr_status_posts == []
    assert len(host.commit_statuses) == 1


def test_no_head_means_no_pull_request_status() -> None:
    host = AzureHost(azure_answers.OPEN)

    post(host, head="")

    assert host.pr_status_posts == []
    assert len(host.commit_statuses) == 1


def test_a_completed_pull_request_is_not_written_to() -> None:
    """Azure will not take a status on a completed pull request, and the unit
    that merged it is not failed for that."""
    completed = azure_answers.pull(status="completed", pullRequestId=157)
    host = AzureHost(completed)

    post(host)

    assert host.pr_status_posts == []
    assert len(host.commit_statuses) == 1, "the commit status is still the record"


def test_an_abandoned_pull_request_is_not_written_to() -> None:
    host = AzureHost(azure_answers.ABANDONED)

    post(host)

    assert host.pr_status_posts == []


def test_a_refused_pull_request_status_is_a_warning_not_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = AzureHost(azure_answers.OPEN, refuse_pr_status="TF401027: GenericContribute required")

    with caplog.at_level(logging.WARNING):
        post(host)  # must not raise

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert len(host.commit_statuses) == 1


def test_a_failing_result_that_a_rework_fixes_stops_being_a_failing_check() -> None:
    """A failed `local/tier2` on the pull request is a failing check, and
    reworks the unit — as it does on GitHub. The rework pushes and the new
    result supersedes it: re-read as a fresh failure, the unit would rework
    for ever."""
    host = AzureHost(azure_answers.OPEN)

    post(host, ok=False, sha="old")
    [failing] = listed(host)
    assert failing.failing_checks == ("local/tier2",)

    post(host, ok=True, sha="new")
    [fixed] = listed(host)

    assert "local/tier2" not in fixed.failing_checks
    assert fixed.failing_checks == ()
