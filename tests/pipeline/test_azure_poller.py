"""The poller on Azure DevOps: a conflict sends a unit back, and only a conflict.

The poller has always sent a unit back when `mergeable` turns `False`; the
Azure forge never set it, so the feature did nothing. These drive the poller
through the Azure forge's own reading of recorded pull request documents, so
the wiring between the two is what is tested.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON, Poller
from tests.forges import azure_answers
from tests.forges.azure_host import AzureHost

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def watch(tmp_path: Path, *merge_statuses: str):
    """A poller over one Azure pull request whose `mergeStatus` is each of
    these in turn, the last repeating, and what it dispatched."""
    host = AzureHost(azure_answers.pull(mergeStatus=merge_statuses[0]))
    sent: list[tuple[str, int, str]] = []
    turn = iter(merge_statuses)

    def list_prs() -> list[PullRequest]:
        host.pulls = [azure_answers.pull(mergeStatus=next(turn, merge_statuses[-1]))]
        return FORGE.list_prs(REPO, run=host)

    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=list_prs,
        dispatch=lambda action, number, **kw: sent.append((action, number, kw.get("reason", ""))),
    )
    return poller, sent


def test_a_pull_request_that_starts_conflicting_goes_back_for_rework(tmp_path: Path) -> None:
    poller, sent = watch(tmp_path, "succeeded", "conflicts")

    poller.poll()  # records it as mergeable
    poller.poll()

    assert sent == [("rework", 162, CONFLICT_REASON)]


def test_a_queued_merge_status_is_not_a_conflict(tmp_path: Path) -> None:
    """The host answers `queued` for a while after every push, the pipeline's
    own included. It is undetermined, not conflicting."""
    poller, sent = watch(tmp_path, "succeeded", "queued", "queued")

    poller.poll()
    poller.poll()
    poller.poll()

    assert sent == []


def test_an_undetermined_answer_between_conflicts_is_not_a_second_conflict(
    tmp_path: Path,
) -> None:
    """The last definite answer stands across `queued`, so a conflicted unit
    is reworked once rather than once per trunk merge."""
    poller, sent = watch(tmp_path, "succeeded", "conflicts", "queued", "conflicts")

    for _ in range(4):
        poller.poll()

    assert sent == [("rework", 162, CONFLICT_REASON)]


def test_a_policy_rejection_is_not_a_conflict(tmp_path: Path) -> None:
    """`rejectedByPolicy` says nothing about conflicts, and a rework cannot
    fix a policy."""
    poller, sent = watch(tmp_path, "succeeded", "rejectedByPolicy")

    poller.poll()
    poller.poll()

    assert sent == []
