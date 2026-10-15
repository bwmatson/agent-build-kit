"""A merge is repeated only after the commit read shows it did not happen (spec: forge-merge).

The inner forge is the shared stand-in, which can fail before or after the host merged."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import MergeRefused, RepoId
from agent_build_kit.forges.operations import OPERATIONS
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import HostError, HostUnavailable
from tests.fake_clock import FakeClock
from tests.forges.stand_in import StandInForge

REPO = RepoId(forge="github", account="example", name="app")
HEAD = "a" * 40
ATTEMPTS = 3


def layer(inner: StandInForge) -> ResilientForge:
    clock = FakeClock()
    return ResilientForge(
        inner,
        RetryPolicy(attempts=ATTEMPTS, deadline_seconds=1000.0),
        clock,
        clock.advance,
    )


def down() -> HostError:
    return HostError("PUT /merge: host answered 503")


def test_a_merge_that_failed_after_the_host_merged_returns_the_commit_it_finds() -> None:
    inner = StandInForge(
        merge_sha="squashed", merge_failures=[down()], merge_lands_before_failing=True
    )

    assert layer(inner).merge_pr(REPO, 7, head=HEAD) == "squashed"

    assert inner.merge_calls == [(7, HEAD)]


def test_a_merge_that_failed_before_the_host_did_anything_is_tried_again() -> None:
    inner = StandInForge(merge_sha="squashed", merge_failures=[down()])

    assert layer(inner).merge_pr(REPO, 7, head=HEAD) == "squashed"

    assert inner.merge_calls == [(7, HEAD), (7, HEAD)]


def test_a_refusal_is_raised_on_the_first_call_and_never_repeated() -> None:
    # A create, so a failure of another kind would be asked about and repeated.
    assert OPERATIONS["merge_pr"].kind == "create"
    inner = StandInForge(merge_refusal="Pull Request is not mergeable")

    with pytest.raises(MergeRefused) as refused:
        layer(inner).merge_pr(REPO, 7, head=HEAD)

    assert "not mergeable" in str(refused.value)
    assert inner.merge_calls == [(7, HEAD)]


def test_a_host_that_stays_unavailable_raises_the_error_the_other_creates_raise() -> None:
    inner = StandInForge(merge_failures=[down()] * 10)

    with pytest.raises(HostUnavailable) as caught:
        layer(inner).merge_pr(REPO, 7, head=HEAD)

    assert caught.value.operation == "merge_pr"
    assert inner.merged == {}
