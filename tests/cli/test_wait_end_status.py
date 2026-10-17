"""The status says what a wait's end did: a closed prerequisite left the unit failed, and how
many failed units were resumed today because their wait ended."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import CLOSED, FAILED, UnitState
from tests import fake_clock
from tests.factories import new_unit
from tests.wait_end_support import CHILD, PARENT, Pipeline, pipeline

COUNT = "failed units resumed when their wait ended"


def status(pipe: Pipeline, monkeypatch: pytest.MonkeyPatch, capsys) -> list[str]:
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), pipe.inst) == 0
    return capsys.readouterr().out.splitlines()


def close_prerequisite(pipe: Pipeline) -> None:
    """The wait ends because the prerequisite was closed and the `Needs:` line dropped."""
    pipe.store.set_state(PARENT, CLOSED)
    pipe.store.set_dependencies(CHILD, ())


def test_a_closed_prerequisite_leaves_the_unit_failed_and_says_so_in_the_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    close_prerequisite(pipe)

    pipe.passes(2)

    assert pipe.store.get(CHILD).state == FAILED
    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).waited_on == ()
    lines = status(pipe, monkeypatch, capsys)
    assert any("wait ended: base group 1 closed, requeue to retry" in line for line in lines)


def test_a_later_requeue_clears_the_closed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    pipe.pass_()
    close_prerequisite(pipe)
    pipe.pass_()

    assert cli.requeue(pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None) == 0

    assert pipe.store.get(CHILD).wait_ended == ""
    assert not any("wait ended:" in line for line in status(pipe, monkeypatch, capsys))


def test_the_status_counts_the_requeues_made_when_a_wait_ended_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clock.install(monkeypatch)
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.store.upsert(
        [
            *(new_unit(f"p{n}/1") for n in (1, 2)),
            *(new_unit(f"kid{n}/1", depends_on=(f"p{n}/1",)) for n in (1, 2)),
        ]
    )
    for n in (1, 2):
        pipe.store.set_state(f"p{n}/1", UnitState.RUNNING)
        pipe.store.set_state(f"kid{n}/1", FAILED, branch=f"spec/kid{n}/1", cause=Cause.FAILED)
    pipe.pass_()
    pipe.merge("p1/1", "p2/1")
    pipe.pass_()

    lines = status(pipe, monkeypatch, capsys)

    assert any(f"{COUNT}: 2 today" in line for line in lines)


def test_a_requeue_by_a_person_is_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clock.install(monkeypatch)
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    pipe.pass_()
    pipe.store.set_state(CHILD, UnitState.FAILED, cause=Cause.FAILED)
    assert cli.requeue(pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None) == 0

    lines = status(pipe, monkeypatch, capsys)

    assert any(f"{COUNT}: 1 today" in line for line in lines)


def test_the_count_is_left_out_at_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.waiting_failed()
    pipe.pass_()

    assert not any(COUNT in line for line in status(pipe, monkeypatch, capsys))


def test_off_leaves_the_count_out_even_with_such_a_requeue_in_the_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False, wait_end_requeue="off")
    pipe.waiting_failed()
    pipe.store.set_state(
        CHILD,
        UnitState.PLANNED,
        note="requeue: its wait ended (waiting on x)",
        cause=Cause.REQUEUED,
    )

    assert not any(COUNT in line for line in status(pipe, monkeypatch, capsys))


def test_a_requeue_made_on_an_earlier_day_is_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = fake_clock.install(monkeypatch)
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    pipe.store.upsert(
        [
            *(new_unit(f"p{n}/1") for n in (1, 2)),
            *(new_unit(f"kid{n}/1", depends_on=(f"p{n}/1",)) for n in (1, 2)),
        ]
    )
    for n in (1, 2):
        pipe.store.set_state(f"p{n}/1", UnitState.RUNNING)
        pipe.store.set_state(f"kid{n}/1", FAILED, branch=f"spec/kid{n}/1", cause=Cause.FAILED)
    pipe.pass_()
    pipe.merge("p1/1")
    pipe.pass_()
    clock.advance(26 * 3600)
    pipe.merge("p2/1")
    pipe.pass_()

    lines = status(pipe, monkeypatch, capsys)

    assert any(f"{COUNT}: 1 today" in line for line in lines)


def test_the_count_includes_a_requeue_delivered_to_a_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_clock.install(monkeypatch)
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    pipe.pass_()
    pipe.merge()
    pipe.pass_()

    assert len(pipe.host.deliveries) == 1
    assert any(f"{COUNT}: 1 today" in line for line in status(pipe, monkeypatch, capsys))


def left_by_a_closed_prerequisite(pipe: Pipeline) -> None:
    pipe.waiting_failed()
    pipe.pass_()
    close_prerequisite(pipe)
    pipe.pass_()
    assert pipe.store.get(CHILD).wait_ended == "base group 1"


def test_a_refused_requeue_leaves_the_closed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, threads=False)
    left_by_a_closed_prerequisite(pipe)

    refused = cli.requeue(
        pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None, note="start from the date"
    )

    assert refused == 1
    assert pipe.store.get(CHILD).wait_ended == "base group 1"
    assert any(
        "wait ended: base group 1 closed" in line for line in status(pipe, monkeypatch, capsys)
    )


def test_a_requeue_refused_for_a_busy_branch_leaves_the_closed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    left_by_a_closed_prerequisite(pipe)
    pipe.host.busy = True

    refused = cli.requeue(pipe.inst, CHILD, "resume", say=lambda *args, **kwargs: None)

    assert refused == 1
    assert pipe.store.get(CHILD).wait_ended == "base group 1"
    assert any(
        "wait ended: base group 1 closed" in line for line in status(pipe, monkeypatch, capsys)
    )
