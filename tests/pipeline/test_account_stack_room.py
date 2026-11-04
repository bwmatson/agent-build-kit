"""An account's `max_concurrent_stacks` holds in the occupancy and in admission, which count from
the durable facts under the admission lock: the units a run holds across the account's projects
leave no more room than the cap, every unit needs that room (a resume as much as a new start; only
the units in progress limit is bypassed by one already in progress), and the emergency lane's
places do not get past it (spec: account-project-limits).
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.admission import admit
from agent_build_kit.pipeline.occupancy import Limits, free, occupied
from agent_build_kit.pipeline.unit_store import Starting, UnitStore
from agent_build_kit.pipeline.units import ProjectKey, Unit
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_account_stack_cap_tick import workspace
from tests.emergency_lane_support import build, fresh, seeded
from tests.pipeline.test_occupancy import NOW, on_branch, paused_unit
from tests.pipeline.test_occupancy import key as project

TTL = timedelta(minutes=10)
CAP = Limits(stacks=4, account_stacks={"kit": 2})


def account_of(unit: Unit) -> str | None:
    """`app` and `platform` run on the account `kit`; `web` on the default account."""
    return "kit" if unit.repo in ("app", "platform") else None


def held(*units: Unit, running: set[str] = frozenset(), **kwargs):
    return occupied(
        units, locks=(), leases=(), now=NOW, held=running, account_of=account_of, **kwargs
    )


def test_the_runs_held_in_an_accounts_projects_are_counted_for_the_account() -> None:
    units = [
        on_branch("a/1", repo="app"),
        on_branch("p/1", repo="platform"),
        on_branch("w/1", repo="web"),
    ]

    found = held(*units, running={"a/1", "p/1", "w/1"})

    assert found.account_workers == {"kit": 2, None: 1}


def test_a_unit_running_in_the_lane_is_counted_for_its_account() -> None:
    lane_run = on_branch("run/1", repo="app")

    found = held(lane_run, running={"run/1"}, lane={"run/1"})

    assert found.account_workers == {"kit": 1}


def test_a_unit_paused_for_usage_holds_no_worker_for_its_account() -> None:
    found = held(paused_unit("a/1", repo="app"))

    assert found.account_workers == {}


def test_an_account_at_its_cap_leaves_no_room_for_a_unit_of_another_project() -> None:
    found = held(
        on_branch("a/1", repo="app"), on_branch("p/1", repo="platform"), running={"a/1", "p/1"}
    )

    assert free(found, CAP, ProjectKey(repo="platform"), "kit") == 0


def test_an_account_below_its_cap_has_the_room_left() -> None:
    found = held(on_branch("a/1", repo="app"), running={"a/1"})

    assert free(found, CAP, ProjectKey(repo="platform"), "kit") == 1


def test_a_unit_already_in_progress_is_held_to_the_accounts_cap_too() -> None:
    found = held(
        on_branch("a/1", repo="app"), on_branch("p/1", repo="platform"), running={"a/1", "p/1"}
    )

    assert free(found, CAP, ProjectKey(repo="platform"), "kit", new=False) == 0


def test_a_unit_of_the_default_account_is_not_held_by_a_capped_account() -> None:
    found = held(
        on_branch("a/1", repo="app"), on_branch("p/1", repo="platform"), running={"a/1", "p/1"}
    )

    assert free(found, CAP, project("web"), None) == 4


def test_an_account_that_sets_no_cap_leaves_the_projects_room() -> None:
    found = held(
        on_branch("a/1", repo="app"), on_branch("p/1", repo="platform"), running={"a/1", "p/1"}
    )

    assert free(found, Limits(stacks=4), ProjectKey(repo="platform"), "kit") == 3


def admitted(inst, store: UnitStore, *candidates: str) -> list[str]:
    ids = set(candidates)
    return [
        unit.id
        for unit in admit(
            inst,
            store,
            [unit for unit in store.all() if unit.id in ids],
            worker="w1",
            now=datetime.now(UTC),
            ttl=TTL,
        )
    ]


def test_admission_refuses_a_third_unit_of_an_account_that_allows_two_builds(
    tmp_path: Path,
) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    store = seeded(
        inst,
        tmp_path,
        [build("a/1", repo="app"), build("p/1", repo="platform"), fresh("w/1", repo="web")],
    )

    with ExitStack() as stack:
        for uid in ("a/1", "p/1"):
            stack.enter_context(branch_lock(store.get(uid).branch, root=inst.locks_dir))
        assert admitted(inst, store, "w/1") == []

    assert store.get("w/1").starting is None


def test_a_priority_zero_unit_the_lane_would_take_is_refused_when_the_account_is_full(
    tmp_path: Path,
) -> None:
    """Another tick admitted the account's second unit after this one's round chose the
    candidate: the lane has a place, but the account has no room."""
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    store = seeded(
        inst,
        tmp_path,
        [build("a/1", repo="app"), fresh("p/1", repo="platform"), fresh("w/1", repo="web")],
    )
    store.set_starting("p/1", Starting(worker="tick-2", until=datetime.now(UTC) + TTL))
    candidate = fresh("c/1", repo="platform", priority=0)[0]
    store.upsert([candidate])
    emergency_lane.enter(inst.state_dir, store.get("c/1"))

    with branch_lock(store.get("a/1").branch, root=inst.locks_dir):
        assert admitted(inst, store, "c/1") == []

    assert store.get("c/1").starting is None


def test_a_lane_unit_is_admitted_while_the_account_has_room(tmp_path: Path) -> None:
    inst = workspace(tmp_path, account={"max_concurrent_stacks": 2})
    store = seeded(inst, tmp_path, [build("a/1", repo="app")])
    store.upsert([fresh("c/1", repo="platform", priority=0)[0]])
    emergency_lane.enter(inst.state_dir, store.get("c/1"))

    with branch_lock(store.get("a/1").branch, root=inst.locks_dir):
        assert admitted(inst, store, "c/1") == ["c/1"]
