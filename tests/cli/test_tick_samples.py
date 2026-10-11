"""The running pass samples its slots each refresh and stamps when a unit became ready
(spec: unit-timeline-is-recorded).

A tick is driven as `test_tick_slot_wait` drives it: two units, one slot, each build
taking thirty seconds of a fake clock, so the pass wakes once per completion.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import build_report, render_json
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.fake_clock import START, FakeClock, install
from tests.ledger_lines import write_ledger
from tests.otlp import Collector, enabled

pytestmark = pytest.mark.usefixtures("scripted_engine")

SAMPLE_COUNTS = {"running", "in_review", "blocked", "queued", "free_workers", "limit", "cap"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        yield collector


class Build:
    """Stands in for `build_runner`: each build takes `seconds` of the fake clock."""

    def __init__(self, store: UnitStore, clock: FakeClock, seconds: float) -> None:
        self.store = store
        self.clock = clock
        self.seconds = seconds
        self.started: list[str] = []

    def __call__(self, unit, **kwargs) -> Build:
        return self

    def run(self, unit, *, base, graph) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.clock.advance(self.seconds)
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))


class Pass:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = install(monkeypatch)
        self.inst: Installation = make_installation(
            tmp_path,
            planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
            limits={"max_concurrent_stacks": 1, "max_units_in_progress": 50},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit("first/1"), new_unit("second/1", repo="platform")])
        self.build = Build(self.store, self.clock, seconds=30)
        monkeypatch.setattr(cli, "build_runner", self.build)

    @property
    def ledger(self) -> Path:
        return self.inst.state_dir / LEDGER_NAME

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False), self.inst)

    def samples(self) -> list[dict]:
        lines = [json.loads(line) for line in self.ledger.read_text().splitlines() if line]
        return [line for line in lines if line.get("kind") == "sample"]


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pass:
    return Pass(tmp_path, monkeypatch)


def test_each_refresh_of_the_pass_writes_one_sample_row_with_the_named_counts(run: Pass) -> None:
    assert run.tick() == 0

    first, last = run.samples()
    assert set(first) >= SAMPLE_COUNTS | {"kind", "at"}
    assert set(last) >= SAMPLE_COUNTS
    assert (last["running"], last["in_review"], last["blocked"], last["queued"]) == (0, 2, 0, 0)
    assert (last["free_workers"], last["limit"], last["cap"]) == (1, 50, 1)


def test_a_sample_is_stamped_with_the_time_of_its_refresh(run: Pass) -> None:
    run.tick()

    first, last = run.samples()
    assert first["at"] == (START + timedelta(seconds=30)).isoformat()
    assert last["at"] == (START + timedelta(seconds=60)).isoformat()


def test_a_ledger_reader_skips_the_sample_rows(run: Pass, tmp_path: Path) -> None:
    run.tick()
    assert run.samples(), "the pass wrote none"
    without = write_ledger(
        tmp_path / "without.jsonl",
        *[
            line
            for line in run.ledger.read_text().splitlines()
            if json.loads(line).get("kind") != "sample"
        ],
    )

    with_samples = build_report(run.ledger, run.store.all(), group_by="unit")
    assert render_json(with_samples) == render_json(
        build_report(without, run.store.all(), group_by="unit")
    )


def test_the_slot_gauges_are_set_without_a_unit_or_change_attribute(
    run: Pass, exported: Collector
) -> None:
    run.tick()

    for name in ("abk.slots.free", "abk.slots.idle_with_ready"):
        points = exported.metric(name)
        assert points, f"{name} was never set"
        assert all(point.attributes == {} for point in points)


# --- ready_at -------------------------------------------------------------------------------


def test_a_unit_that_waits_for_a_slot_is_stamped_ready_from_when_it_first_could_have_run(
    run: Pass,
) -> None:
    run.tick()

    first, second = (run.store.get(uid) for uid in ("first/1", "second/1"))
    assert first.ready_at == START
    assert second.ready_at == START, "ready when the pass saw it, not when it got a slot"
    assert second.started_at == START + timedelta(seconds=30)
