"""A login rejected while a conflict is being resolved is not a conflict.

The same as for an outage: the resolver's run could not be served, which says nothing about the
branch, so the child of a merge is deferred and the note says why.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.runtimes import LoginRejected
from tests.factories import stored_unit as stored

pytestmark = pytest.mark.usefixtures("scripted_engine")


def rejected(*args: Any, **kwargs: Any) -> NoReturn:
    raise LoginRejected(Account.default(), "OAuth access token has expired")


def test_a_merge_event_restack_that_meets_a_rejected_login_is_deferred_not_a_conflict(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored("c/2")])
    store.set_state("c/2", IN_REVIEW, pr=2, branch="spec/c/2")

    restack_child = events.build_restack(
        repos={"app": tmp_path},
        store=store,
        root=tmp_path,
        move=rejected,
        unit_test=lambda **k: (True, ""),
        push=lambda *a, **k: "x",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "d",
        head_of=lambda repo, branch: "h",
    )

    restack_child(
        branch="spec/c/2",
        old_base="spec/c/1",
        new_base="main",
        child=stored("c/2", pr=2, branch="spec/c/2", approved="h"),
        parent=stored("c/1", pr=1, branch="spec/c/1"),
    )

    last = store.get("c/2").history[-1]
    assert last["state"] == PLANNED
    assert last["cause"] == Cause.RESTACK_DEFERRED
    assert "a rejected login" in last["note"]
