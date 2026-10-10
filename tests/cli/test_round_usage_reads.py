"""A round asks for a usage reading only on behalf of a unit that can start in it.

A unit left out of the round by `--only`, by a lease another process holds or by a
backoff cannot start, so a decision about it is not a decision: the round asks the
endpoint for nothing and writes no pause. The real guard runs; only the endpoint is
faked (`tests/usage_host.py`).
"""

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.planner import Plan
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.usage_host import Host, payload


@pytest.fixture
def inst(tmp_path: Path, host: Host) -> Installation:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)


def round_of(inst: Installation, store: UnitStore, *, only: frozenset[str] = frozenset()) -> list:
    ready = cli.run_round(inst, store, building=set(), started=set(), only=only, submit=True)
    return [unit.id for unit in ready]


def stored(inst: Installation, *ids: str) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit(uid, change=uid.partition("/")[0]) for uid in ids])
    return store


def test_a_round_whose_only_candidate_is_left_out_by_only_asks_for_no_reading(
    inst: Installation, host: Host
) -> None:
    store = stored(inst, "feature/1")

    assert round_of(inst, store, only=frozenset({"other/1"})) == []

    assert host.asked == 0
    assert is_paused(inst.state_dir / "paused.json") is None


def test_a_round_whose_only_candidate_is_held_by_a_lease_asks_for_no_reading(
    inst: Installation, host: Host
) -> None:
    store = stored(inst, "feature/1")
    assert Leases(lease_dir(inst.state_dir)).take("feature/1", "chat")

    assert round_of(inst, store) == []

    assert host.asked == 0
    assert is_paused(inst.state_dir / "paused.json") is None


def test_a_round_whose_only_candidate_is_in_a_backoff_asks_for_no_reading(
    inst: Installation, host: Host
) -> None:
    store = stored(inst, "feature/1")
    store.record_step("feature/1", "open_pr")
    store.set_state(
        "feature/1",
        PLANNED,
        note="create_pr: host unavailable after 3 attempts",
        cause=Cause.HOST_UNAVAILABLE,
    )

    assert round_of(inst, store) == []

    assert host.asked == 0
    assert is_paused(inst.state_dir / "paused.json") is None


def test_a_round_with_a_candidate_that_is_not_excluded_asks_for_a_reading(
    inst: Installation, host: Host
) -> None:
    store = stored(inst, "feature/1", "other/1")
    host.answers = [payload(session=10.0)]

    started = round_of(inst, store, only=frozenset({"other/1"}))

    assert host.asked == 1
    assert started == ["other/1"]


TASKS = """# Tasks

Acceptance: none — a fixture about rounds, not about the acceptance group

## 1. [app] [tier1] Register the marker

- [ ] 1.1 Test: it selects only marked tests.
- [ ] 1.2 Register it.
"""


def test_a_round_with_a_change_to_plan_plans_it_though_every_planned_unit_is_left_out(
    inst: Installation, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(inst, "feature/1")
    change = inst.root / "openspec" / "changes" / "add-marker"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    planned: list[tuple[str, ...]] = []

    def plan(**kwargs) -> Plan:
        planned.append(tuple(kwargs["changes"]))
        return Plan(units=(stored_unit("add-marker/1", change="add-marker"),))

    monkeypatch.setattr(cli, "plan_round", plan)
    host.answers = [payload(session=10.0)]

    started = round_of(inst, store, only=frozenset({"add-marker/1"}))

    assert planned == [("add-marker",)]
    assert started == ["add-marker/1"]
