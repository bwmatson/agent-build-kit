"""What a full account's queue says in the tick's reason for starting nothing, and in the status
(spec: claude-accounts, usage and slots are per account): its own blocked units, and the
emergency-lane note only while a lane of its projects has room."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline import emergency_lane, spans
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, PLANNED
from tests.cli.test_tick_scheduling import open_pr
from tests.conftest import make_installation, status_lines
from tests.factories import new_unit
from tests.pipeline.test_slots_per_account import kit, repos
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

LANE_NOTE = "a priority-0 unit may still start while the emergency lane has room"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warm_unit_graphs(tmp_path)
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


def test_a_full_account_queue_in_the_nothing_started_reason_lists_its_blocked_units(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=2)}},
    )
    open_pr(builder, "one/1", 11)
    open_pr(builder, "two/1", 12)
    builder.store.upsert([stored("new/1"), stored("blocked/1", depends_on=("new/1",))])
    builder.store.set_state("blocked/1", PLANNED, branch="spec/blocked/1")

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    assert "account kit: 2 units in progress, limit 2" in out
    assert "blocked: blocked/1 (app) waits on new/1" in out


def lane_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    lane: tuple[str, ...],
) -> str:
    """The `kit` account's queue-full line, its two places held by failed `app` units of which
    `lane` are recorded in the emergency lane."""

    def record(store: UnitStore) -> None:
        ids = ("held0/1", "held1/1")
        store.upsert([new_unit(uid, repo="app") for uid in ids])
        for uid in ids:
            store.set_state(uid, FAILED, note="broke", branch=f"spec/{uid}")
        for uid in lane:
            emergency_lane.enter(tmp_path, store.get(uid))

    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [new_unit("ready/1", repo="app")],
        repos=repos(tmp_path, {"app": "kit"}),
        record=record,
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=2)}},
    )
    [line] = [line for line in lines if "queue is full" in line]
    return line


def test_a_full_account_slot_with_a_full_emergency_lane_does_not_say_a_priority_zero_may_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = lane_status(tmp_path, monkeypatch, capsys, lane=("held0/1",))

    assert "account kit" in line
    assert LANE_NOTE not in line


def test_a_full_account_slot_with_a_free_emergency_lane_says_a_priority_zero_may_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = lane_status(tmp_path, monkeypatch, capsys, lane=())

    assert line.endswith(LANE_NOTE)


def test_a_full_default_account_queue_does_not_list_another_accounts_blocked_units(
    builder: Builder, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_units_in_progress": 2},
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=5)}},
    )
    open_pr(builder, "one/1", 11, repo="web")
    open_pr(builder, "two/1", 12, repo="web")
    builder.store.upsert(
        [
            stored("ready/1", repo="web"),
            stored("parent/1", repo="app"),
            stored("blocked/1", repo="app", depends_on=("parent/1",)),
        ]
    )
    builder.store.set_state("parent/1", FAILED, note="broke", branch="spec/parent/1")
    builder.store.set_state("blocked/1", PLANNED, branch="spec/blocked/1")

    assert tick(inst) == 0

    out = capsys.readouterr().out
    assert builder.started == []
    [line] = [line for line in out.splitlines() if "default account: 2 units in progress" in line]
    assert "blocked" not in line
    assert "blocked: blocked/1" not in out


def test_the_slot_sample_limit_is_the_sum_of_the_limits_of_the_accounts_in_use(
    builder: Builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_units_in_progress": 5},
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=2)}},
    )
    builder.store.upsert([stored("a/1", repo="app"), stored("w/1", repo="web")])
    recorded: list[spans.Sample] = []
    real = spans.record_sample

    def record(sample: spans.Sample, log: Callable[[str], None]) -> None:
        recorded.append(sample)
        real(sample, log)

    monkeypatch.setattr(spans, "record_sample", record)

    assert tick(inst) == 0

    assert recorded
    assert {sample.limit for sample in recorded} == {7}
