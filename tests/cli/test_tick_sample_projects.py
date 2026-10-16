"""The sample a refresh writes totals the limit, the cap and the free workers over the projects
that have a unit not yet finished (spec: unit-scheduling, the running pass samples its slots).

A tick is driven as `test_tick_samples` drives it: each build takes thirty seconds of a fake
clock, so the pass wakes once per completion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, RUNNING
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import build_wait_report
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.fake_clock import FakeClock, install
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

LIMIT = 5
CAP = 4


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


class Build:
    """Stands in for `build_runner`: each build takes thirty seconds of the fake clock."""

    def __init__(self, store: UnitStore, clock: FakeClock) -> None:
        self.store = store
        self.clock = clock
        self.started: list[str] = []

    def __call__(self, unit, **kwargs) -> Build:
        return self

    def run(self, unit, *, base, graph) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.clock.advance(30)
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))


def tick_over_two_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock = install(monkeypatch)
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_concurrent_stacks": CAP, "max_units_in_progress": LIMIT},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            new_unit("first/1", project="web"),
            new_unit("second/1", project="api"),
            new_unit("done/1", repo="platform"),
        ]
    )
    store.set_state("done/1", MERGED)
    monkeypatch.setattr(cli, "build_runner", Build(store, clock))
    assert cli.cmd_tick(argparse.Namespace(dry_run=False), inst) == 0
    ledger = inst.state_dir / LEDGER_NAME
    lines = [json.loads(line) for line in ledger.read_text().splitlines() if line]
    return ledger, store, [line for line in lines if line.get("kind") == "sample"]


def test_a_sample_totals_the_limit_the_cap_and_the_free_workers_over_live_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger, _store, samples = tick_over_two_projects(tmp_path, monkeypatch)

    assert samples, "the pass wrote no sample"
    # web and api have unfinished units; platform's one unit is merged and adds nothing.
    assert {(s["limit"], s["cap"]) for s in samples} == {(2 * LIMIT, 2 * CAP)}
    assert samples[-1]["free_workers"] == 2 * CAP


def test_the_usage_reports_idle_hours_read_the_totals_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger, store, samples = tick_over_two_projects(tmp_path, monkeypatch)

    assert samples[0]["limit"] == 2 * LIMIT, "the row does not carry the totals"
    idle = build_wait_report(ledger, ledger.with_name(DECISIONS_NAME), store.all()).idle
    assert idle.observed_h > 0
    assert idle.idle_h == 0
