"""A round holds an account's units to its `max_concurrent_stacks` across its projects, counts a
unit running in the restack lane, and says which cap held a unit: in the wait reason and in the
admission record (spec: account-project-limits).

Three repos run on the account `kit`; a round is `run_round` over a store, as in the emergency-lane
round tests, with the builds in flight named by the test.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import ADMISSIONS_NAME, read_admissions
from agent_build_kit.pipeline.resolution_lane import ResolutionLanes
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.conftest import make_installation
from tests.emergency_lane_support import build, fresh, seeded, started_by_round
from tests.pipeline.test_slots_per_account import kit, repos
from tests.restack_lane_fakes import WAIT, Restacks
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

ON_KIT = {"app": "kit", "platform": "kit", "web": "kit"}


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def workspace(
    tmp_path: Path,
    *,
    account: dict | None = None,
    project: dict | None = None,
    labels: dict[str, str] | None = None,
) -> Installation:
    """Three repos, those in `labels` (all on `kit` by default) on the account `kit`, which has
    `account` as its `project_limits`; the project's own limits are `project`."""
    accounts = kit(tmp_path, **({} if account is None else {"project_limits": account}))
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_units_in_progress": 20, **(project or {})},
        repos=repos(tmp_path, ON_KIT if labels is None else labels),
        runtimes={"claude_code": {"accounts": accounts}},
    )


def ready_in_each(*repo_names: str):
    return [fresh(f"{name}-new/1", repo=name) for name in repo_names]


def test_three_projects_of_an_account_with_two_stacks_start_two_in_a_round(
    tmp_path: Path,
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    store = seeded(inst, tmp_path, ready_in_each("app", "platform", "web"))

    assert started_by_round(inst, store, building=()) == ["app-new/1", "platform-new/1"]


def test_a_build_in_flight_in_one_project_leaves_one_stack_for_the_others(tmp_path: Path) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    units = [build("app-run/1", repo="app"), *ready_in_each("platform", "web")]
    store = seeded(inst, tmp_path, units)

    assert started_by_round(inst, store, building={"app-run/1"}) == ["platform-new/1"]


def test_an_account_that_sets_only_its_places_adds_no_stack_cap(tmp_path: Path) -> None:
    inst = workspace(
        tmp_path, account={"max_units_in_progress": 20}, project={"max_concurrent_stacks": 4}
    )
    store = seeded(inst, tmp_path, ready_in_each("app", "platform", "web"))

    assert len(started_by_round(inst, store, building=())) == 3


def test_a_project_cap_below_the_accounts_still_holds(tmp_path: Path) -> None:
    inst = workspace(
        tmp_path, account={"max_concurrent_stacks": 3}, project={"max_concurrent_stacks": 1}
    )
    units = [fresh("app-a/1", repo="app"), fresh("app-b/1", repo="app"), *ready_in_each("web")]
    store = seeded(inst, tmp_path, units)

    assert started_by_round(inst, store, building=()) == ["app-a/1", "web-new/1"]


def test_the_default_accounts_units_are_not_held_by_a_capped_account(tmp_path: Path) -> None:
    inst = workspace(
        tmp_path, account={"max_concurrent_stacks": 1}, labels={"app": "kit", "platform": "kit"}
    )
    units = [build("app-run/1", repo="app"), *ready_in_each("platform", "web")]
    store = seeded(inst, tmp_path, units)

    assert started_by_round(inst, store, building={"app-run/1"}) == ["web-new/1"]


@contextmanager
def lane_running(inst: Installation, store: UnitStore, *unit_ids: str) -> Iterator[ResolutionLanes]:
    """The restack lane `abk tick` builds, holding a run for each unit until the block ends."""
    runs = Restacks()
    lanes = cli.build_restack_lane(inst, store)
    try:
        for unit_id in unit_ids:
            store.set_moved_base_run(unit_id, True)
            unit = store.get(unit_id)
            lanes.hand_over(unit, partial(runs, unit), claimed=False)
            assert runs.begun[unit_id].wait(WAIT), unit_id + " never began"
        yield lanes
    finally:
        runs.release_all()
        lanes.drain()


def test_a_unit_running_in_the_restack_lane_counts_toward_the_accounts_stacks(
    tmp_path: Path,
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    units = [
        build("app-run/1", repo="app"),
        build("platform-run/1", repo="platform"),
        *ready_in_each("web"),
    ]
    store = seeded(inst, tmp_path, units)

    with lane_running(inst, store, "platform-run/1") as lanes:
        started = cli.run_round(
            inst, store, building={"app-run/1"}, only=frozenset(), submit=True, lane=lanes
        )

    assert [unit.id for unit in started] == []


def held_by_the_account(
    tmp_path: Path, *, building: Collection[str] = ("app-run/1", "platform-run/1")
) -> tuple[Installation, UnitStore]:
    """`kit` allows two stacks, two are building and `web-new/1` is ready."""
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    units = [
        build("app-run/1", repo="app"),
        build("platform-run/1", repo="platform"),
        *ready_in_each("web"),
    ]
    store = seeded(inst, tmp_path, units)
    assert started_by_round(inst, store, building=building) == []
    return inst, store


def test_a_unit_held_by_the_accounts_stack_cap_waits_for_a_slot_and_names_the_account_and_cap(
    tmp_path: Path,
) -> None:
    inst, store = held_by_the_account(tmp_path)

    waits = cli.wait_reasons(
        inst,
        store.all(),
        started=set(),
        building={"app-run/1", "platform-run/1"},
        only=frozenset(),
    )

    wait = waits["web-new/1"]
    assert wait.reason is WaitReason.SLOT
    assert "account kit" in wait.detail
    assert "max_concurrent_stacks" in wait.detail
    assert "2/2" in wait.detail


def test_a_unit_held_by_its_projects_own_cap_does_not_name_the_account(tmp_path: Path) -> None:
    inst = workspace(
        tmp_path, account={"max_concurrent_stacks": 3}, project={"max_concurrent_stacks": 1}
    )
    units = [build("app-run/1", repo="app"), fresh("app-new/1", repo="app")]
    store = seeded(inst, tmp_path, units)

    waits = cli.wait_reasons(
        inst, store.all(), started=set(), building={"app-run/1"}, only=frozenset()
    )

    assert waits["app-new/1"].reason is WaitReason.SLOT
    assert waits["app-new/1"].detail == ""


def test_the_admission_record_of_a_held_unit_names_the_cap_the_account_and_who_counted(
    tmp_path: Path,
) -> None:
    inst, _store = held_by_the_account(tmp_path)

    [record] = [
        found
        for found in read_admissions(inst.state_dir / ADMISSIONS_NAME)
        if found.unit == "web-new/1"
    ]

    assert record.kind == "slot"
    assert record.slot == "kit"
    assert record.held_by == "max_concurrent_stacks"
    assert record.limit == 2
    assert sorted(counted.id for counted in record.counted) == ["app-run/1", "platform-run/1"]
