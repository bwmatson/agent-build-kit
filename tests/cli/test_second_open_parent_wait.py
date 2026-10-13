"""A unit waiting for a second open parent is shown as waiting, from the scheduler's own answer.

The status names the parent that must merge and says it is the second open parent, the
ready-queue reason and the graph read the unit as blocked, and waiting stores nothing
(spec: a-unit-waits-for-all-but-one-open-parent).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from agent_build_kit.pipeline.vocabulary import WaitReason, effective_state
from tests.cli.test_wait_reasons import installation, waits_of
from tests.conftest import status_lines
from tests.factories import new_unit as new
from tests.factories import stored_unit


def siblings(store: UnitStore, *_unused) -> None:
    store.upsert([new("sib-a/1"), new("sib-b/1"), new("kid/1", depends_on=("sib-a/1", "sib-b/1"))])
    for uid, pr in (("sib-a/1", 1), ("sib-b/1", 2)):
        store.set_state(uid, IN_REVIEW, branch=f"spec/{uid}", pr=pr)


def review(uid: str, pr: int):
    return new(uid, state=IN_REVIEW, branch=f"spec/{uid}", pr=pr)


def test_the_status_says_which_parent_the_unit_waits_for_to_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            review("sib-a/1", 1),
            review("sib-b/1", 2),
            stored_unit("kid/1", change="kid", depends_on=("sib-a/1", "sib-b/1")),
        ],
    )

    said = [line for line in lines if "kid/1" in line and "second open parent" in line]
    assert len(said) == 1
    assert "waiting for sib-a group 1 to merge (second open parent)" in said[0]
    assert "sib-b" not in said[0], "the base is not something it waits for"


def test_the_ready_queue_does_not_list_the_waiting_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            review("sib-a/1", 1),
            review("sib-b/1", 2),
            stored_unit("kid/1", change="kid", depends_on=("sib-a/1", "sib-b/1")),
        ],
    )

    assert not any(line.lstrip().startswith("1. kid/1") for line in lines)
    assert any("kid/1" in line and "second open parent" in line for line in lines)


def test_the_wait_reason_is_blocked_on_the_parent_that_is_not_the_base(tmp_path: Path) -> None:
    waits = waits_of(tmp_path, siblings)

    assert waits["kid/1"].reason is WaitReason.BLOCKED
    assert waits["kid/1"].waits_on == ("sib-a/1",)


def test_the_graph_draws_the_unit_as_blocked_and_it_reads_blocked(tmp_path: Path) -> None:
    graph = [review("sib-a/1", 1), review("sib-b/1", 2)]
    graph.append(new("kid/1", depends_on=("sib-a/1", "sib-b/1")))

    assert effective_state(graph[2], graph) == "blocked"
    assert "class kid_1 blocked" in render_mermaid(graph)


def test_once_the_wait_ends_the_unit_reads_planned_with_nothing_stored_changed(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    siblings(store, inst)
    before = store.all()

    assert effective_state(next(u for u in before if u.id == "kid/1"), before) == "blocked"
    assert store.all() == before, "reading the wait writes nothing"

    store.set_state("sib-a/1", MERGED)
    after = store.all()

    kid = next(u for u in after if u.id == "kid/1")
    assert kid.state == PLANNED
    assert effective_state(kid, after) == PLANNED
    assert kid == next(u for u in before if u.id == "kid/1")
