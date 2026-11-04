"""An account's `emergency_extra` caps the units of that account in the emergency lane across its
projects, beside each project's own `emergency_extra`: a priority-0 unit blocked only by room
starts in the lane when both counts are under their extras (spec: account-project-limits).

`ready_units` counts the lane's units per slot against a `slot_emergency_extra` that
`extra_of(inst)` builds from the accounts that set the field; occupancy and admission count the
same from the durable facts. An account that does not set it, and the default account, add no
lane limit.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import admit, limits_of
from agent_build_kit.pipeline.occupancy import Limits, emergency_free, occupied
from agent_build_kit.pipeline.slots import extra_of
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, ProjectKey, Unit, ready_units
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_account_stack_cap_tick import workspace
from tests.emergency_lane_support import build, fresh, seeded
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked
from tests.pipeline.test_limits_for import installation
from tests.pipeline.test_occupancy import NOW, on_branch

TTL = timedelta(minutes=10)

# `app`, `platform` and `web` run on the account `kit`; any other repo on the default account.
ON_KIT = {"app", "platform", "web"}


def account_of(unit: Unit) -> str | None:
    return "kit" if unit.repo in ON_KIT else None


def starts(
    graph: Sequence[StoredUnit],
    *,
    account: int | None = 1,
    project: int = 1,
    lane: Collection[str] = (),
    stacks: int | None = None,
) -> list[str]:
    """The ids `ready_units` starts with one worker in each project (so a project holding a run
    is full), a lane of `project` units in each project and `account` units in the account `kit`'s
    lane across its projects (no limit when `None`), and the account's builds at once `stacks`."""

    def extra(slot: Hashable) -> int | None:
        return account if slot == "kit" else None

    def cap(slot: Hashable) -> int | None:
        return stacks if slot == "kit" else None

    return [
        unit.id
        for unit in ready_units(
            graph,
            max_concurrent=1,
            depth_cap=9,
            max_units_in_progress=50,
            emergency_extra=project,
            in_lane=lane,
            slot_of=account_of,
            slot_limit=lambda slot: 50,
            slot_stack_limit=cap,
            slot_emergency_extra=extra,
        )
    ]


def running(repo: str, name: str = "run") -> StoredUnit:
    return worked(f"{repo}-{name}/1", state=RUNNING, repo=repo)


def urgent(repo: str, name: str = "zero") -> StoredUnit:
    return new(f"{repo}-{name}/1", repo=repo, priority=0)


def full_projects(*repos: str) -> list[StoredUnit]:
    """A run in each of `repos`, so each is at its one worker."""
    return [running(repo) for repo in repos]


def test_two_projects_of_an_account_with_one_lane_place_start_one_priority_zero_unit() -> None:
    graph = [*full_projects("app", "platform"), urgent("app"), urgent("platform")]

    assert starts(graph, account=1) == ["app-zero/1"]


def test_two_lane_places_for_the_account_start_both() -> None:
    graph = [*full_projects("app", "platform"), urgent("app"), urgent("platform")]

    assert starts(graph, account=2) == ["app-zero/1", "platform-zero/1"]


def test_a_lane_unit_in_one_project_takes_the_accounts_place_from_the_other() -> None:
    lane_run = worked("app-lane/1", state=RUNNING, repo="app", priority=0)
    graph = [*full_projects("app", "platform"), lane_run, urgent("platform")]

    assert starts(graph, account=1, lane={"app-lane/1"}) == []


def test_the_project_whose_own_lane_is_full_waits_though_the_account_has_room() -> None:
    lane_run = worked("app-lane/1", state=RUNNING, repo="app", priority=0)
    graph = [*full_projects("app", "platform"), lane_run, urgent("app"), urgent("platform")]

    assert starts(graph, account=3, lane={"app-lane/1"}) == ["platform-zero/1"]


def test_an_account_that_sets_no_lane_extra_adds_no_lane_limit() -> None:
    graph = [*full_projects("app", "platform", "web"), *(urgent(r) for r in ("app", "platform"))]

    assert starts(graph, account=None) == ["app-zero/1", "platform-zero/1"]


def test_an_account_extra_of_zero_starts_nothing_past_the_limits() -> None:
    graph = [*full_projects("app", "platform"), urgent("app"), urgent("platform")]

    assert starts(graph, account=0, project=1) == []


def test_a_project_extra_of_zero_starts_nothing_past_the_limits_whatever_the_account_allows() -> (
    None
):
    graph = [*full_projects("app", "platform"), urgent("app"), urgent("platform")]

    assert starts(graph, account=5, project=0) == []


def test_a_unit_that_fits_the_normal_limits_does_not_use_the_accounts_lane() -> None:
    # `platform` has no run: its priority-0 unit takes a worker, and the lane's one place is
    # left for `app`, which is full.
    graph = [running("app"), urgent("platform"), urgent("app")]

    assert starts(graph, account=1) == ["platform-zero/1", "app-zero/1"]


def test_the_default_accounts_units_are_not_held_by_a_full_account_lane() -> None:
    lane_run = worked("app-lane/1", state=RUNNING, repo="app", priority=0)
    graph = [running("app"), running("other"), lane_run, urgent("other")]

    assert starts(graph, account=1, lane={"app-lane/1"}) == ["other-zero/1"]


def test_a_unit_the_accounts_stack_cap_holds_stays_held_with_lane_places_free() -> None:
    graph = [*full_projects("app"), urgent("platform")]

    assert starts(graph, account=2, project=2, stacks=1) == []


def test_the_lane_places_are_counted_for_the_unit_in_progress_that_uses_them() -> None:
    # A lane unit that is in review still uses its place until it is finished.
    reviewing = worked("app-lane/1", state=IN_REVIEW, repo="app", priority=0, pr=1)
    graph = [*full_projects("app", "platform"), reviewing, urgent("platform")]

    assert starts(graph, account=1, lane={"app-lane/1"}) == []


# --- the accounts that set the extra -----------------------------------------------------------


def test_extra_of_gives_the_extra_of_the_accounts_that_set_it(tmp_path: Path) -> None:
    accounts = {
        "kit": {"project_limits": {"emergency_extra": 2}},
        "plain": {"project_limits": {"max_units_in_progress": 3}},
    }
    inst = installation(tmp_path, accounts=accounts, labels={"app": "kit", "platform": "plain"})

    extra = extra_of(inst)

    assert extra("kit") == 2
    assert extra("plain") is None
    assert extra(None) is None


def test_an_account_may_set_its_extra_to_zero(tmp_path: Path) -> None:
    accounts = {"kit": {"project_limits": {"emergency_extra": 0}}}
    inst = installation(tmp_path, accounts=accounts, labels={"app": "kit"})

    assert extra_of(inst)("kit") == 0


def test_an_installation_with_no_accounts_has_no_account_extra(tmp_path: Path) -> None:
    inst = installation(tmp_path, project={"emergency_extra": 2}, labels={})

    assert extra_of(inst)(None) is None
    assert extra_of(inst)(ProjectKey(repo="app")) is None


# --- occupancy and admission -------------------------------------------------------------------


def test_the_lane_units_are_counted_for_their_account() -> None:
    units = [
        on_branch("a/1", repo="app"),
        on_branch("p/1", repo="platform"),
        on_branch("o/1", repo="other"),
    ]

    found = occupied(
        units,
        locks=(),
        leases=(),
        now=NOW,
        held={"a/1", "p/1", "o/1"},
        lane={"a/1", "p/1", "o/1"},
        account_of=account_of,
    )

    assert found.account_emergency == {"kit": 2, None: 1}


def test_a_unit_outside_the_lane_is_not_counted_for_the_accounts_lane() -> None:
    found = occupied(
        [on_branch("a/1", repo="app")],
        locks=(),
        leases=(),
        now=NOW,
        held={"a/1"},
        account_of=account_of,
    )

    assert found.account_emergency == {}


def test_the_lane_has_no_room_for_a_project_when_its_accounts_is_full() -> None:
    limits = Limits(stacks=1, emergency_extra=1, accounts={"kit": 9}, account_extras={"kit": 1})
    found = occupied(
        [on_branch("a/1", repo="app")],
        locks=(),
        leases=(),
        now=NOW,
        held={"a/1"},
        lane={"a/1"},
        account_of=account_of,
    )

    assert emergency_free(found, limits, ProjectKey(repo="platform"), "kit") == 0
    assert emergency_free(found, limits, ProjectKey(repo="platform"), None) == 1
    assert emergency_free(found, limits, ProjectKey(repo="platform")) == 1


def test_limits_of_carries_the_extra_of_each_account_that_sets_one(tmp_path: Path) -> None:
    inst = workspace(tmp_path, account={"emergency_extra": 2})

    assert limits_of(inst).account_extras == {"kit": 2}


def test_limits_of_carries_none_for_an_account_that_sets_none(tmp_path: Path) -> None:
    inst = workspace(tmp_path, account={"max_units_in_progress": 20})

    assert limits_of(inst).account_extras == {}


def admitted(inst: Installation, store: UnitStore, *candidates: str) -> list[str]:
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


def lane_candidate(
    tmp_path: Path, *, account: dict, project: int = 1
) -> tuple[Installation, UnitStore, ExitStack]:
    """`app` and `platform` each hold one worker and `lane/1` (of `app`) uses the lane; `c/1`
    of `platform` is the priority-0 candidate in the lane, with its own project's lane empty.
    The branch locks are held until the returned stack is closed."""
    inst = workspace(
        tmp_path,
        account=account,
        project={"max_concurrent_stacks": 1, "emergency_extra": project},
    )
    store = seeded(
        inst,
        tmp_path,
        [
            build("a/1", repo="app"),
            build("p/1", repo="platform"),
            build("lane/1", repo="app", priority=0),
            fresh("c/1", repo="platform", priority=0),
        ],
        lane=["lane/1", "c/1"],
    )
    stack = ExitStack()
    for uid in ("a/1", "p/1", "lane/1"):
        stack.enter_context(branch_lock(store.get(uid).branch, root=inst.locks_dir))
    return inst, store, stack


def test_admission_refuses_a_lane_start_when_the_accounts_lane_is_full(tmp_path: Path) -> None:
    inst, store, stack = lane_candidate(tmp_path, account={"emergency_extra": 1})

    with stack:
        assert admitted(inst, store, "c/1") == []

    assert store.get("c/1").starting is None


def test_admission_admits_a_lane_start_while_the_accounts_lane_has_room(tmp_path: Path) -> None:
    inst, store, stack = lane_candidate(tmp_path, account={"emergency_extra": 2})

    with stack:
        assert admitted(inst, store, "c/1") == ["c/1"]


def test_admission_adds_no_lane_limit_for_an_account_that_sets_no_extra(tmp_path: Path) -> None:
    inst, store, stack = lane_candidate(tmp_path, account={"max_units_in_progress": 20})

    with stack:
        assert admitted(inst, store, "c/1") == ["c/1"]


def test_admission_admits_nothing_in_the_lane_with_the_accounts_extra_at_zero(
    tmp_path: Path,
) -> None:
    inst, store, stack = lane_candidate(tmp_path, account={"emergency_extra": 0})

    with stack:
        assert admitted(inst, store, "c/1") == []


def test_admission_admits_nothing_in_the_lane_with_the_projects_extra_at_zero(
    tmp_path: Path,
) -> None:
    inst, store, stack = lane_candidate(tmp_path, account={"emergency_extra": 5}, project=0)

    with stack:
        assert admitted(inst, store, "c/1") == []
