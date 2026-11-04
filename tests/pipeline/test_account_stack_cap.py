"""An account's `max_concurrent_stacks` caps the units of that account building at once across its
projects, beside each project's own cap (spec: account-project-limits).

`ready_units` counts running units per slot against a `slot_stack_limit`, which
`slot_stack_limit(inst)` builds from the accounts that set the field: an account that does not
set it, and the default account, add no cap.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Sequence
from pathlib import Path

from agent_build_kit.pipeline.slots import slot_of, slot_stack_limit
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import PLANNED, RUNNING, Unit, ready_units
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked
from tests.pipeline.test_limits_for import installation

# The repo `app` runs on the account `kit`, as do `platform` and `web` below.
ON_KIT = {"app": "kit", "platform": "kit", "web": "kit"}


def account_of(unit: Unit) -> str | None:
    """Every unit of `app`, `platform` and `web` counts under `kit`; any other repo under the
    default account."""
    return "kit" if unit.repo in ON_KIT else None


def starts(
    graph: Sequence[StoredUnit],
    *,
    stacks: int | None = 2,
    workers: int = 4,
    no_worker: Collection[str] = (),
) -> list[str]:
    """The ids `ready_units` starts when the account `kit` allows `stacks` builds at once (no cap
    when `None`) and each project `workers`."""

    def cap(slot: Hashable) -> int | None:
        return stacks if slot == "kit" else None

    return [
        unit.id
        for unit in ready_units(
            graph,
            max_concurrent=workers,
            depth_cap=9,
            max_units_in_progress=50,
            slot_of=account_of,
            slot_limit=lambda slot: 50,
            slot_stack_limit=cap,
            no_worker=no_worker,
        )
    ]


def ready(repo: str, count: int = 1, prefix: str = "") -> list[StoredUnit]:
    return [new(f"{prefix or repo}{n}/1", repo=repo) for n in range(count)]


def building(repo: str, count: int = 1, prefix: str = "") -> list[StoredUnit]:
    return [worked(f"{prefix or repo}-run{n}/1", state=RUNNING, repo=repo) for n in range(count)]


def test_three_projects_of_an_account_with_two_stacks_start_two() -> None:
    graph = [*ready("app"), *ready("platform"), *ready("web")]

    assert starts(graph) == ["app0/1", "platform0/1"]


def test_a_unit_running_in_one_project_takes_one_of_the_accounts_two_stacks() -> None:
    graph = [*building("app"), *ready("platform"), *ready("web")]

    assert starts(graph) == ["platform0/1"]


def test_two_units_running_in_the_accounts_projects_leave_no_stack_for_the_third() -> None:
    graph = [*building("app"), *building("platform"), *ready("web")]

    assert starts(graph) == []


def test_each_unit_started_is_also_held_to_its_projects_own_cap() -> None:
    graph = [*ready("app", 3), *ready("platform")]

    assert starts(graph, stacks=3, workers=1) == ["app0/1", "platform0/1"]


def test_a_project_at_its_own_cap_does_not_use_up_the_accounts_room_for_another() -> None:
    graph = [*building("app"), *ready("app"), *ready("platform", 2)]

    # `app` holds its one worker; the account still has one of its two stacks for `platform`.
    assert starts(graph, workers=1) == ["platform0/1"]


def test_an_account_that_sets_no_stack_cap_adds_none() -> None:
    graph = [*ready("app"), *ready("platform"), *ready("web")]

    assert starts(graph, stacks=None) == ["app0/1", "platform0/1", "web0/1"]


def test_another_accounts_units_neither_count_nor_are_held() -> None:
    graph = [*building("app"), *building("platform"), *ready("web"), *ready("other", 3)]

    assert starts(graph) == ["other0/1", "other1/1", "other2/1"]


def test_a_running_unit_paused_for_usage_holds_no_worker_and_so_no_stack() -> None:
    graph = [*building("app"), *building("platform"), *ready("web")]

    assert starts(graph, no_worker={"app-run0/1"}) == ["web0/1"]


def test_a_started_planned_unit_draws_on_the_accounts_stacks_like_a_new_one() -> None:
    resumed = worked("app-resume/1", state=PLANNED, repo="app")
    graph = [resumed, *ready("platform"), *ready("web")]

    assert starts(graph) == ["app-resume/1", "platform0/1"]


def test_an_account_stack_cap_of_one_starts_the_first_in_start_order_only() -> None:
    graph = [*ready("web"), *ready("app")]

    assert starts(graph, stacks=1) == ["web0/1"]


def test_no_cap_function_means_no_account_cap() -> None:
    graph = [*ready("app"), *ready("platform"), *ready("web")]

    started = ready_units(
        graph, max_concurrent=4, depth_cap=9, slot_of=account_of, slot_limit=lambda slot: 50
    )

    assert len(started) == 3


def test_the_accounts_that_set_a_stack_cap_are_the_only_ones_capped(tmp_path: Path) -> None:
    accounts = {
        "kit": {"project_limits": {"max_concurrent_stacks": 2}},
        "plain": {"project_limits": {"max_units_in_progress": 3}},
    }
    inst = installation(tmp_path, accounts=accounts, labels={"app": "kit", "platform": "plain"})

    cap = slot_stack_limit(inst)

    assert cap("kit") == 2
    assert cap("plain") is None
    assert cap(None) is None
    assert slot_of(inst)(new("a/1", repo="app")) == "kit"


def test_an_installation_with_no_accounts_has_no_stack_cap(tmp_path: Path) -> None:
    inst = installation(tmp_path, project={"max_concurrent_stacks": 1}, labels={})

    cap = slot_stack_limit(inst)

    assert cap(None) is None
