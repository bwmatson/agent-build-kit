"""A tick that builds nothing says why for each candidate unit (spec:
a-failed-live-test-says-what-its-scratch-tick-did, unit-scheduling)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED
from agent_build_kit.pipeline.usage_guard import Decision
from tests.cli.test_tick_scheduling import limit_workspace
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

FIRST_LINE = "nothing ready to build"
UNIT_LINE = re.compile(r"^  \S+ \(\S+\): ")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def lines_of(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """The tick's output lines, without the clock each line opens with."""
    out = capsys.readouterr().out
    return [re.sub(r"^\[\d\d:\d\d:\d\d\] ", "", line) for line in out.splitlines()]


def report(lines: list[str]) -> list[str]:
    """The lines from `nothing ready to build` on."""
    assert FIRST_LINE in lines
    return lines[lines.index(FIRST_LINE) :]


def hold(store: UnitStore, uid: str) -> None:
    store.upsert([stored(uid)])
    store.set_state(uid, HELD, note="a person took over")


def back_off(store: UnitStore, uid: str) -> None:
    store.upsert([stored(uid)])
    store.record_step(uid, "open_pr")
    store.set_state(uid, PLANNED, note="host unavailable", cause=Cause.HOST_UNAVAILABLE)


def baseline_prints_unit_lines(builder: Builder, inst, capsys: pytest.CaptureFixture[str]) -> None:
    """A unit in backoff alone gets its line, so lines missing below are the report's doing."""
    back_off(builder.store, "held/1")
    assert tick(inst) == 0
    assert "  held/1 (app): backoff" in lines_of(capsys)
    builder.store.set_state("held/1", MERGED)


def test_each_candidate_unit_gets_a_line_with_its_reason_and_what_it_waits_on(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    hold(builder.store, "parent/1")
    builder.store.upsert([stored("child/1", depends_on=("parent/1",))])
    back_off(builder.store, "later/1")
    builder.store.upsert([stored("review/1"), stored("done/1")])
    builder.store.set_state("review/1", IN_REVIEW, pr=11, branch="spec/review/1")
    builder.store.set_state("done/1", MERGED)

    assert tick(inst) == 0

    shown = report(lines_of(capsys))
    assert shown[0] == FIRST_LINE
    assert sorted(shown[1:]) == [
        "  child/1 (app): blocked, waits on parent/1",
        "  later/1 (app): backoff",
        "  parent/1 (app): needs_person",
    ]
    # What a person can act on soonest comes first.
    assert shown[1] == "  later/1 (app): backoff"


def test_fourteen_candidates_print_ten_lines_and_a_tail_with_actionable_ones_first(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 99)
    for number in range(12):
        hold(builder.store, f"held/{number}")
    back_off(builder.store, "late/1")
    back_off(builder.store, "late/2")

    assert tick(inst) == 0

    shown = report(lines_of(capsys))
    assert shown[0] == FIRST_LINE
    assert shown[1:3] == ["  late/1 (app): backoff", "  late/2 (app): backoff"]
    assert len([line for line in shown[1:] if UNIT_LINE.match(line)]) == 10
    assert shown[-1] == "  (+4 more)"
    assert len(shown) == 1 + 10 + 1


def test_one_candidate_prints_one_line_and_no_tail(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    back_off(builder.store, "only/1")

    assert tick(inst) == 0

    assert report(lines_of(capsys)) == [FIRST_LINE, "  only/1 (app): backoff"]


def test_a_unit_in_review_alone_leaves_only_the_first_line(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    baseline_prints_unit_lines(builder, inst, capsys)
    builder.store.upsert([stored("review/1")])
    builder.store.set_state("review/1", IN_REVIEW, pr=11, branch="spec/review/1")

    assert tick(inst) == 0

    assert report(lines_of(capsys)) == [FIRST_LINE]


def test_a_deadlock_report_has_no_unit_lines(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    baseline_prints_unit_lines(builder, inst, capsys)
    builder.store.upsert([stored("a/1", depends_on=("b/2",)), stored("b/2", depends_on=("a/1",))])

    assert tick(inst) == 0

    lines = lines_of(capsys)
    assert any(line.startswith("nothing can start: deadlocked: ") for line in lines)
    assert FIRST_LINE not in lines
    assert not [line for line in lines if UNIT_LINE.match(line)]


def test_a_full_queue_report_has_no_unit_lines(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 2)
    baseline_prints_unit_lines(builder, inst, capsys)
    for number, uid in enumerate(("one/1", "two/1"), start=11):
        builder.store.upsert([stored(uid)])
        builder.store.set_state(uid, IN_REVIEW, pr=number, branch=f"spec/{uid}")
    builder.store.upsert([stored("new/1")])

    assert tick(inst) == 0

    lines = lines_of(capsys)
    assert any("units in progress, limit 2" in line for line in lines)
    assert FIRST_LINE not in lines
    assert not [line for line in lines if re.match(r"^  new/1 \(app\): ", line)]


def test_a_rate_limit_pause_prints_its_pause_line_and_no_unit_lines(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = limit_workspace(tmp_path, 9)
    baseline_prints_unit_lines(builder, inst, capsys)
    back_off(builder.store, "later/1")
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="the model refused",
        marker=tmp_path / PAUSE_MARKER,
        kind="rate_limit",
    )

    assert tick(inst) == 0

    lines = lines_of(capsys)
    assert any("the model refused" in line for line in lines)
    assert not [line for line in lines if UNIT_LINE.match(line)]


def test_a_usage_pause_prints_its_pause_line_and_no_unit_lines(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 9)
    baseline_prints_unit_lines(builder, inst, capsys)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=False, reason="session at 88%")
    )
    builder.store.upsert([stored("feature/1")])

    assert tick(inst) == 0

    lines = lines_of(capsys)
    assert any("session at 88%" in line for line in lines)
    assert not [line for line in lines if UNIT_LINE.match(line)]


def test_reasons_that_cannot_be_computed_leave_the_bare_line_and_an_error_line(
    builder: Builder,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = limit_workspace(tmp_path, 9)
    hold(builder.store, "held/1")
    back_off(builder.store, "late/1")
    before = [unit.model_dump() for unit in builder.store.all()]

    def refuse(*args, **kwargs):
        raise RuntimeError("no reasons today")

    monkeypatch.setattr(cli, "wait_reasons", refuse)

    assert tick(inst) == 0

    shown = report(lines_of(capsys))
    assert shown[0] == FIRST_LINE
    assert len(shown) == 2
    assert "RuntimeError" in shown[1]
    assert builder.started == []
    assert [unit.model_dump() for unit in builder.store.all()] == before
