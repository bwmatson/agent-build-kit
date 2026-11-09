"""A round starts a priority-0 unit in the emergency lane only when its project's and its
account's lane use are both under their extras, and marks it a lane start exactly when its normal
start would have been refused (spec: account-project-limits).

Three repos run on the account `kit`, each with one worker, which a running build holds; a ready
priority-0 unit in each can start only in the lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission import limits_of
from agent_build_kit.pipeline.occupancy import capacity
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.test_account_stack_cap_tick import workspace
from tests.emergency_lane_support import build, fresh, seeded, started_by_round
from tests.tick_pass import isolate

pytestmark = pytest.mark.usefixtures("scripted_engine")

REPOS = ("app", "platform", "web")
RUNS = [f"{repo}-run/1" for repo in REPOS]


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


def lane_round(
    tmp_path: Path,
    *,
    account: dict | None = None,
    project: int = 1,
    repos: tuple[str, ...] = REPOS,
    full: tuple[str, ...] = REPOS,
) -> tuple[Installation, UnitStore]:
    """Each repo in `full` holds its one worker with a running build, and a ready priority-0 unit
    `<repo>-zero/1` is in each of `repos`; the projects' lane is `project`, the account's
    `account`."""
    inst = workspace(
        tmp_path,
        account=account,
        project={"max_concurrent_stacks": 1, "emergency_extra": project},
    )
    units = [
        *(build(f"{repo}-run/1", repo=repo) for repo in full),
        *(fresh(f"{repo}-zero/1", repo=repo, priority=0) for repo in repos),
    ]
    return inst, seeded(inst, tmp_path, units)


def test_the_accounts_lane_of_one_place_starts_one_of_its_projects_priority_zero_units(
    tmp_path: Path,
) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 1})

    assert started_by_round(inst, store, building=RUNS) == ["app-zero/1"]


def test_an_accounts_lane_of_two_places_starts_two(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 2})

    assert started_by_round(inst, store, building=RUNS) == ["app-zero/1", "platform-zero/1"]


def test_an_account_that_sets_no_lane_extra_adds_no_lane_limit(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"max_units_in_progress": 20})

    assert len(started_by_round(inst, store, building=RUNS)) == 3


def test_the_projects_lane_still_holds_beside_a_larger_account_lane(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 5}, repos=("app",))
    store.upsert([fresh("app-zero/2", repo="app", priority=0)[0]])

    assert started_by_round(inst, store, building=RUNS) == ["app-zero/1"]


def test_with_the_accounts_extra_at_zero_nothing_starts_past_the_limits(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 0})

    assert started_by_round(inst, store, building=RUNS) == []


def test_with_the_projects_extra_at_zero_nothing_starts_past_the_limits(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 3}, project=0)

    assert started_by_round(inst, store, building=RUNS) == []


def test_a_unit_waiting_for_the_accounts_lane_is_not_marked_a_lane_start(tmp_path: Path) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 1})

    ready, _view, _excluded, _owed, in_the_lane = cli._evaluate_round(
        inst, store.all(), started=set(), building=set(RUNS), only=frozenset()
    )

    assert [unit.id for unit in ready] == ["app-zero/1"]
    assert in_the_lane == {"app-zero/1"}


def test_a_unit_that_fits_the_normal_limits_is_not_a_lane_start_and_leaves_the_lane(
    tmp_path: Path,
) -> None:
    # `platform` and `web` hold no build: their units start normally, and `app`'s lane start
    # still has the account's one place.
    inst, store = lane_round(tmp_path, account={"emergency_extra": 1}, full=("app",))

    ready, _view, _excluded, _owed, in_the_lane = cli._evaluate_round(
        inst, store.all(), started=set(), building={"app-run/1"}, only=frozenset()
    )

    assert {unit.id for unit in ready} >= {"app-zero/1", "platform-zero/1", "web-zero/1"}
    assert in_the_lane == {"app-zero/1"}


def test_the_pool_holds_every_worker_and_lane_place_whatever_the_accounts_extra(
    tmp_path: Path,
) -> None:
    inst, store = lane_round(tmp_path, account={"emergency_extra": 9})

    started = started_by_round(inst, store, building=RUNS)

    # A start past the projects' lane is never made, so the pool (the workers and the projects'
    # own lane places of the live projects) still has a thread for each start and each build.
    assert len(started) + len(RUNS) <= capacity(limits_of(inst), len(REPOS))
