"""A superseded unit's pull request is closed after a comment naming its pieces, the close is
retried until it is made, and the host's closed event leaves the unit as it is (spec:
unit-superseding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.pipeline.wiring import build_close_pr
from tests.factories import superseded_store
from tests.forges.stand_in import StandInForge, lookup

OLD, FIRST, LAST = "app/3", "app/3-s1", "app/3-s2"
PR = 17


def test_the_comment_names_the_pieces_the_lines_the_ceiling_and_the_tier_and_comes_first(
    tmp_path: Path,
) -> None:
    store = superseded_store(tmp_path)
    pending = store.get(OLD).close_pending
    assert pending is not None and pending.pr == PR
    host = StandInForge(close_error="502 Bad Gateway")
    close = build_close_pr(for_repo=lookup(host))

    with pytest.raises(RuntimeError):
        close(store.get(OLD), PR, pending.reason)

    [comment] = host.comments
    assert host.closed == [], "the comment was posted although the close failed"
    for named in (FIRST, LAST, "950", "750", "full"):
        assert named in comment

    host.close_error = ""
    close(store.get(OLD), PR, pending.reason)

    assert host.closed == [PR]


def test_a_close_that_fails_is_kept_and_a_later_pass_closes_it_and_clears_the_record(
    tmp_path: Path,
) -> None:
    store = superseded_store(tmp_path)
    pending = store.get(OLD).close_pending
    assert pending is not None
    calls: list[tuple[str, int, str]] = []

    def refuse(u: Unit, pr: int, reason: str) -> None:
        raise RuntimeError("502 Bad Gateway")

    def close(u: Unit, pr: int, reason: str) -> None:
        calls.append((u.id, pr, reason))

    cli.retry_closes(store, close_pr=refuse)
    assert store.get(OLD).close_pending == pending

    cli.retry_closes(store, close_pr=close)

    assert calls == [(OLD, PR, pending.reason)]
    assert store.get(OLD).close_pending is None
    assert store.get(OLD).state == UnitState.CLOSED


def test_the_closed_event_for_its_pull_request_leaves_the_cause_superseded(tmp_path: Path) -> None:
    store = superseded_store(tmp_path)

    events.on_closed(PR, repo="app", store=store)

    old = store.get(OLD)
    assert (old.state, old.cause) == (UnitState.CLOSED, Cause.SUPERSEDED)
    assert old.superseded_by == (FIRST, LAST)
